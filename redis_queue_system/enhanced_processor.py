"""
Enhanced queue processor with error handling, retry logic, and dead letter queue
"""
import asyncio
import json
import logging
from typing import List, Dict, Optional
from datetime import datetime, timezone, timedelta
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from sqlalchemy.dialects.postgresql import insert
from database.db_conf import Session
from database.models import LiveTrackPoint, UploadedTrackPoint, Flymaster, ScoringTracks, Flight
from redis_queue_system.redis_queue import redis_queue, QUEUE_NAMES

logger = logging.getLogger(__name__)


class EnhancedPointProcessor:
    """
    Enhanced processor with:
    - Dead letter queue for permanently failed items
    - Automatic retry with exponential backoff
    - Foreign key validation
    - Batch processing optimization
    - Monitoring and alerting
    """
    
    def __init__(self):
        self.processing = False
        self.max_retries = 3
        self.retry_delay = 1  # Initial retry delay in seconds
        self.max_retry_delay = 60  # Maximum retry delay
        self.batch_size = 500
        self.dlq_threshold = 3  # Move to DLQ after this many failures
        
        self.stats = {
            'processed': 0,
            'failed': 0,
            'dlq_items': 0,
            'retried': 0,
            'last_processed': None,
            'last_error': None
        }
        
    async def process_with_retry(self, queue_name: str, items: List[Dict]) -> bool:
        """
        Process items with retry logic and error handling
        """
        all_points = []
        for item in items:
            all_points.extend(item.get('points', []))
        
        if not all_points:
            return True
            
        # Track retry attempts per batch
        retry_count = item.get('retry_count', 0) if items else 0
        
        try:
            # First, validate foreign keys
            valid_points, invalid_points = await self._validate_foreign_keys(all_points, queue_name)
            
            if invalid_points:
                logger.warning(f"Found {len(invalid_points)} points with invalid foreign keys")
                # Move invalid points to DLQ
                await self._move_to_dlq(queue_name, invalid_points, "Invalid foreign key")
                self.stats['dlq_items'] += len(invalid_points)
            
            if not valid_points:
                return True  # No valid points to process
            
            # Process valid points based on queue type
            success = await self._process_points_by_type(queue_name, valid_points)
            
            if success:
                self.stats['processed'] += len(valid_points)
                return True
            else:
                # Retry logic
                if retry_count < self.max_retries:
                    retry_count += 1
                    delay = min(self.retry_delay * (2 ** retry_count), self.max_retry_delay)
                    
                    logger.info(f"Retrying batch in {delay} seconds (attempt {retry_count}/{self.max_retries})")
                    
                    # Re-queue with retry count
                    for item in items:
                        item['retry_count'] = retry_count
                        item['next_retry'] = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()
                    
                    # Re-queue to priority queue with delay
                    await self._requeue_with_delay(queue_name, items, delay)
                    self.stats['retried'] += len(all_points)
                    return False
                else:
                    # Max retries exceeded, move to DLQ
                    await self._move_to_dlq(queue_name, all_points, "Max retries exceeded")
                    self.stats['dlq_items'] += len(all_points)
                    return False
                    
        except Exception as e:
            logger.error(f"Unexpected error processing {queue_name}: {e}")
            self.stats['last_error'] = str(e)
            
            # Move to DLQ after threshold
            if retry_count >= self.dlq_threshold:
                await self._move_to_dlq(queue_name, all_points, f"Processing error: {e}")
                self.stats['dlq_items'] += len(all_points)
            
            return False
    
    async def _validate_foreign_keys(self, points: List[Dict], queue_name: str) -> tuple:
        """
        Validate foreign keys before processing
        Returns: (valid_points, invalid_points)
        """
        if queue_name not in [QUEUE_NAMES['live'], QUEUE_NAMES['upload']]:
            return points, []  # No FK validation needed for other types
        
        valid_points = []
        invalid_points = []
        
        # Get unique flight UUIDs
        flight_uuids = set()
        for point in points:
            if 'flight_uuid' in point:
                flight_uuids.add(point['flight_uuid'])
        
        if not flight_uuids:
            return points, []  # No UUIDs to validate
        
        # Check which flights exist
        existing_uuids = set()
        try:
            with Session() as db:
                result = db.query(Flight.id).filter(
                    Flight.id.in_(list(flight_uuids))
                ).all()
                existing_uuids = {str(row[0]) for row in result}
        except Exception as e:
            logger.error(f"Error validating flight UUIDs: {e}")
            # If we can't validate, assume all are valid to avoid data loss
            return points, []
        
        # Separate valid and invalid points
        for point in points:
            if 'flight_uuid' not in point or point['flight_uuid'] in existing_uuids:
                valid_points.append(point)
            else:
                invalid_points.append(point)
                
        return valid_points, invalid_points
    
    async def _process_points_by_type(self, queue_name: str, points: List[Dict]) -> bool:
        """
        Process points based on queue type
        """
        try:
            if queue_name == QUEUE_NAMES['live']:
                return await self._process_live_points(points)
            elif queue_name == QUEUE_NAMES['upload']:
                return await self._process_upload_points(points)
            elif queue_name == QUEUE_NAMES['flymaster']:
                return await self._process_flymaster_points(points)
            elif queue_name == QUEUE_NAMES['scoring']:
                return await self._process_scoring_points(points)
            else:
                logger.error(f"Unknown queue type: {queue_name}")
                return False
        except IntegrityError as e:
            # Handle specific integrity errors
            if "foreign key" in str(e).lower():
                logger.error(f"Foreign key violation: {e}")
                # Points should have been validated, this is unexpected
                return False
            else:
                raise
    
    async def _process_live_points(self, points: List[Dict]) -> bool:
        """Process live tracking points with ON CONFLICT handling"""
        try:
            with Session() as db:
                stmt = insert(LiveTrackPoint).on_conflict_do_nothing(
                    index_elements=['flight_id', 'lat', 'lon', 'datetime']
                )
                db.execute(stmt, points)
                db.commit()
                logger.info(f"Successfully processed {len(points)} live points")
                return True
        except SQLAlchemyError as e:
            logger.error(f"Database error processing live points: {e}")
            return False
            
    async def _process_upload_points(self, points: List[Dict]) -> bool:
        """Process uploaded track points"""
        try:
            with Session() as db:
                stmt = insert(UploadedTrackPoint).on_conflict_do_nothing(
                    index_elements=['flight_id', 'lat', 'lon', 'datetime']
                )
                db.execute(stmt, points)
                db.commit()
                logger.info(f"Successfully processed {len(points)} upload points")
                return True
        except SQLAlchemyError as e:
            logger.error(f"Database error processing upload points: {e}")
            return False
    
    async def _process_flymaster_points(self, points: List[Dict]) -> bool:
        """Process Flymaster device points"""
        try:
            with Session() as db:
                flymaster_data = []
                for point_data in points:
                    flymaster_dict = {
                        'device_id': point_data['device_id'],
                        'date_time': point_data['date_time'],
                        'lat': point_data['lat'],
                        'lon': point_data['lon'],
                        'gps_alt': point_data['gps_alt'],
                        'heading': point_data.get('heading'),
                        'speed': point_data.get('speed'),
                        'uploaded_at': point_data.get('uploaded_at')
                    }
                    flymaster_data.append(flymaster_dict)
                
                stmt = insert(Flymaster).on_conflict_do_nothing(
                    index_elements=['device_id', 'date_time', 'lat', 'lon']
                )
                db.execute(stmt, flymaster_data)
                db.commit()
                logger.info(f"Successfully processed {len(points)} Flymaster points")
                return True
        except SQLAlchemyError as e:
            logger.error(f"Database error processing Flymaster points: {e}")
            return False
    
    async def _process_scoring_points(self, points: List[Dict]) -> bool:
        """Process scoring track points"""
        try:
            with Session() as db:
                stmt = insert(ScoringTracks).on_conflict_do_nothing(
                    index_elements=['flight_uuid', 'date_time', 'lat', 'lon']
                )
                db.execute(stmt, points)
                db.commit()
                logger.info(f"Successfully processed {len(points)} scoring points")
                return True
        except SQLAlchemyError as e:
            logger.error(f"Database error processing scoring points: {e}")
            return False
    
    async def _requeue_with_delay(self, queue_name: str, items: List[Dict], delay: float):
        """
        Re-queue items with delay for retry
        """
        try:
            # Add items back to priority queue with future timestamp as score
            future_time = datetime.now(timezone.utc) + timedelta(seconds=delay)
            priority = int(future_time.timestamp())
            
            for item in items:
                await redis_queue.redis_client.zadd(
                    f"queue:{queue_name}",
                    {json.dumps(item): priority}
                )
            
            logger.info(f"Re-queued {len(items)} items to {queue_name} with {delay}s delay")
        except Exception as e:
            logger.error(f"Failed to re-queue items: {e}")
    
    async def _move_to_dlq(self, queue_name: str, points: List[Dict], reason: str):
        """
        Move failed items to dead letter queue
        """
        try:
            dlq_item = {
                'points': points,
                'original_queue': queue_name,
                'reason': reason,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'count': len(points)
            }
            
            # Add to DLQ with timestamp as score
            await redis_queue.redis_client.zadd(
                f"dlq:{queue_name}",
                {json.dumps(dlq_item): datetime.now(timezone.utc).timestamp()}
            )
            
            logger.warning(f"Moved {len(points)} items to DLQ for {queue_name}: {reason}")
        except Exception as e:
            logger.error(f"Failed to move items to DLQ: {e}")
    
    async def process_dlq(self, queue_name: str, reprocess: bool = False) -> Dict:
        """
        Process or inspect dead letter queue
        """
        dlq_name = f"dlq:{queue_name}"
        dlq_size = await redis_queue.redis_client.zcard(dlq_name)
        
        if not reprocess:
            # Just return stats
            return {
                'queue': queue_name,
                'dlq_size': dlq_size,
                'oldest_item': None
            }
        
        # Reprocess DLQ items
        processed = 0
        failed = 0
        
        while True:
            items = await redis_queue.redis_client.zpopmin(dlq_name, 100)
            if not items:
                break
                
            for item_data, score in items:
                try:
                    dlq_item = json.loads(item_data)
                    points = dlq_item.get('points', [])
                    
                    # Try to process again
                    success = await self._process_points_by_type(queue_name, points)
                    
                    if success:
                        processed += len(points)
                    else:
                        failed += len(points)
                        # Put back in DLQ
                        await redis_queue.redis_client.zadd(dlq_name, {item_data: score})
                        
                except Exception as e:
                    logger.error(f"Error reprocessing DLQ item: {e}")
                    failed += 1
        
        return {
            'queue': queue_name,
            'processed': processed,
            'failed': failed,
            'remaining': await redis_queue.redis_client.zcard(dlq_name)
        }
    
    async def get_queue_health(self) -> Dict:
        """
        Get comprehensive queue health metrics
        """
        health = {
            'status': 'healthy',
            'queues': {},
            'stats': self.stats.copy()
        }
        
        for queue_type, queue_name in QUEUE_NAMES.items():
            list_size = await redis_queue.redis_client.llen(f"list:{queue_name}")
            priority_size = await redis_queue.redis_client.zcard(f"queue:{queue_name}")
            dlq_size = await redis_queue.redis_client.zcard(f"dlq:{queue_name}")
            
            health['queues'][queue_type] = {
                'list_size': list_size,
                'priority_size': priority_size,
                'dlq_size': dlq_size,
                'total_pending': list_size + priority_size,
                'has_issues': dlq_size > 0 or (list_size + priority_size) > 1000
            }
            
            if dlq_size > 0 or (list_size + priority_size) > 1000:
                health['status'] = 'degraded'
        
        return health
    
    async def cleanup_old_items(self, max_age_hours: int = 24):
        """
        Clean up old items from queues and DLQ
        """
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
        cutoff_score = cutoff_time.timestamp()
        cleaned = {}
        
        for queue_type, queue_name in QUEUE_NAMES.items():
            # Clean priority queue
            removed = await redis_queue.redis_client.zremrangebyscore(
                f"queue:{queue_name}", 0, cutoff_score
            )
            
            # Clean DLQ
            dlq_removed = await redis_queue.redis_client.zremrangebyscore(
                f"dlq:{queue_name}", 0, cutoff_score
            )
            
            cleaned[queue_type] = {
                'queue_cleaned': removed,
                'dlq_cleaned': dlq_removed
            }
            
            if removed > 0 or dlq_removed > 0:
                logger.info(f"Cleaned {queue_type}: {removed} from queue, {dlq_removed} from DLQ")
        
        return cleaned


# Global enhanced processor instance
enhanced_processor = EnhancedPointProcessor()