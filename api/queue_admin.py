"""
Admin API endpoints for queue management
"""
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from typing import Optional
import logging
from datetime import datetime
from redis_queue_system.redis_queue import redis_queue, QUEUE_NAMES
from redis_queue_system.enhanced_processor import enhanced_processor

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/queue", tags=["Queue Admin"])


@router.get("/health")
async def get_queue_health():
    """
    Get comprehensive health status of all queues
    
    Returns queue sizes, DLQ sizes, and processing statistics
    """
    try:
        health = await enhanced_processor.get_queue_health()
        
        # Add timestamp
        health['timestamp'] = datetime.utcnow().isoformat()
        
        # Determine HTTP status based on health
        if health['status'] == 'healthy':
            status_code = 200
        elif health['status'] == 'degraded':
            status_code = 207  # Multi-status
        else:
            status_code = 503
            
        return JSONResponse(content=health, status_code=status_code)
        
    except Exception as e:
        logger.error(f"Error getting queue health: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/process-dlq/{queue_type}")
async def process_dead_letter_queue(
    queue_type: str,
    dry_run: bool = Query(False, description="If true, only return stats without processing")
):
    """
    Process items in the dead letter queue
    
    Args:
        queue_type: Type of queue (live_points, upload_points, etc.)
        dry_run: If true, only inspect without processing
    """
    if queue_type not in QUEUE_NAMES:
        raise HTTPException(status_code=400, detail=f"Invalid queue type: {queue_type}")
    
    try:
        queue_name = QUEUE_NAMES[queue_type]
        result = await enhanced_processor.process_dlq(queue_name, reprocess=not dry_run)
        
        return {
            "queue_type": queue_type,
            "action": "inspected" if dry_run else "processed",
            "result": result,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error processing DLQ for {queue_type}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/clear/{queue_type}")
async def clear_queue(
    queue_type: str,
    include_dlq: bool = Query(False, description="Also clear the dead letter queue"),
    confirm: bool = Query(False, description="Must be true to confirm deletion")
):
    """
    Clear all items from a specific queue
    
    WARNING: This permanently deletes all queued data!
    """
    if not confirm:
        raise HTTPException(
            status_code=400, 
            detail="Set confirm=true to confirm queue deletion"
        )
    
    if queue_type not in QUEUE_NAMES and queue_type != "all":
        raise HTTPException(status_code=400, detail=f"Invalid queue type: {queue_type}")
    
    try:
        cleared = {}
        
        if queue_type == "all":
            queues_to_clear = QUEUE_NAMES.items()
        else:
            queues_to_clear = [(queue_type, QUEUE_NAMES[queue_type])]
        
        for q_type, q_name in queues_to_clear:
            # Clear list queue
            list_cleared = await redis_queue.redis_client.delete(f"list:{q_name}")
            
            # Clear priority queue
            priority_cleared = await redis_queue.redis_client.delete(f"queue:{q_name}")
            
            # Clear DLQ if requested
            dlq_cleared = 0
            if include_dlq:
                dlq_cleared = await redis_queue.redis_client.delete(f"dlq:{q_name}")
            
            cleared[q_type] = {
                "list_cleared": bool(list_cleared),
                "priority_cleared": bool(priority_cleared),
                "dlq_cleared": bool(dlq_cleared) if include_dlq else "not_cleared"
            }
            
            logger.warning(f"Cleared queue {q_type} (include_dlq={include_dlq})")
        
        return {
            "action": "cleared",
            "queues": cleared,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error clearing queue {queue_type}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cleanup")
async def cleanup_old_items(
    max_age_hours: int = Query(24, ge=1, le=168, description="Maximum age of items to keep (hours)"),
    dry_run: bool = Query(False, description="If true, only show what would be cleaned")
):
    """
    Clean up old items from queues and DLQ
    
    Items older than max_age_hours will be removed
    """
    try:
        if dry_run:
            # Just count old items
            result = {}
            for queue_type, queue_name in QUEUE_NAMES.items():
                # This would require implementing a count method
                result[queue_type] = "Would check for old items"
            
            return {
                "action": "dry_run",
                "max_age_hours": max_age_hours,
                "result": result
            }
        else:
            cleaned = await enhanced_processor.cleanup_old_items(max_age_hours)
            
            total_cleaned = sum(
                v['queue_cleaned'] + v['dlq_cleaned'] 
                for v in cleaned.values()
            )
            
            return {
                "action": "cleaned",
                "max_age_hours": max_age_hours,
                "total_cleaned": total_cleaned,
                "details": cleaned,
                "timestamp": datetime.utcnow().isoformat()
            }
            
    except Exception as e:
        logger.error(f"Error cleaning up old items: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
async def get_queue_stats():
    """
    Get detailed statistics for all queues
    """
    try:
        stats = await redis_queue.get_queue_stats()
        processor_stats = enhanced_processor.stats.copy()
        
        # Calculate additional metrics
        total_pending = sum(
            s.get('total_pending', 0) 
            for s in stats.values()
        )
        
        total_dlq = 0
        for queue_name in QUEUE_NAMES.values():
            dlq_size = await redis_queue.redis_client.zcard(f"dlq:{queue_name}")
            total_dlq += dlq_size
        
        return {
            "queue_stats": stats,
            "processor_stats": processor_stats,
            "summary": {
                "total_pending": total_pending,
                "total_dlq": total_dlq,
                "total_processed": processor_stats.get('processed', 0),
                "total_failed": processor_stats.get('failed', 0),
                "health_status": "healthy" if total_pending < 1000 and total_dlq == 0 else "degraded"
            },
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error getting queue stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/force-process/{queue_type}")
async def force_process_queue(
    queue_type: str,
    batch_size: int = Query(100, ge=1, le=1000, description="Number of items to process")
):
    """
    Force immediate processing of items from a queue
    
    Useful for manually triggering processing of stuck items
    """
    if queue_type not in QUEUE_NAMES:
        raise HTTPException(status_code=400, detail=f"Invalid queue type: {queue_type}")
    
    try:
        queue_name = QUEUE_NAMES[queue_type]
        
        # Dequeue and process items
        items = await redis_queue.dequeue_batch(queue_name, batch_size)
        
        if not items:
            return {
                "queue_type": queue_type,
                "message": "No items to process",
                "processed": 0
            }
        
        # Process with retry logic
        success = await enhanced_processor.process_with_retry(queue_name, items)
        
        return {
            "queue_type": queue_type,
            "items_retrieved": len(items),
            "success": success,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error force processing queue {queue_type}: {e}")
        raise HTTPException(status_code=500, detail=str(e))