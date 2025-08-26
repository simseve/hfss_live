"""
Redis-based queue system for batching large point insertions
"""
import json
import logging
import asyncio
from typing import List, Dict, Any
from datetime import datetime, timezone
from uuid import UUID
import redis.asyncio as redis
from config import settings

logger = logging.getLogger(__name__)


class DateTimeEncoder(json.JSONEncoder):
    """Custom JSON encoder that handles datetime and UUID objects."""

    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        elif isinstance(obj, UUID):
            return str(obj)
        return super().default(obj)


class RedisPointQueue:
    def __init__(self):
        self.redis_client = None
        # Process points in batches of 1000    async def connect(self):
        self.batch_size = 1000

    async def connect(self):
        """Initialize Redis connection"""
        try:
            # Use the new get_redis_url method from settings
            redis_url = settings.get_redis_url()
            
            # Use lower default to prevent exhaustion
            max_connections = getattr(settings, 'REDIS_MAX_CONNECTIONS', 10)

            self.redis_client = redis.from_url(
                redis_url,
                decode_responses=True,
                max_connections=max_connections
            )
            await self.redis_client.ping()
            logger.info(f"Redis connection established: {redis_url} (max_connections={max_connections})")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise

    async def disconnect(self):
        """Close Redis connection"""
        if self.redis_client:
            await self.redis_client.aclose()
            await self.redis_client.connection_pool.disconnect()

    async def queue_points(self, queue_name: str, points: List[Dict[str, Any]], priority: int = 0):
        """
        Queue points for batch processing

        Args:
            queue_name: Name of the queue (e.g., 'live_points', 'upload_points', 'flymaster_points')
            points: List of point dictionaries to queue
            priority: Priority score (higher = more priority)
        """
        try:
            # Add metadata
            queue_item = {
                'points': points,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'count': len(points),
                'queue_type': queue_name
            }

            # Add to priority queue (primary storage)
            await self.redis_client.zadd(
                f"queue:{queue_name}",
                {json.dumps(queue_item, cls=DateTimeEncoder): priority}
            )
            
            # Note: Not adding to list anymore to avoid duplication
            # The dequeue_batch method will read from priority queue if list is empty

            logger.info(f"Queued {len(points)} points to {queue_name}")
            return True

        except Exception as e:
            logger.error(f"Failed to queue points: {e}")
            return False
    
    async def queue_points_batch(self, queue_name: str, items: List[tuple], use_pipeline: bool = True):
        """
        Queue multiple items efficiently using pipelining
        
        Args:
            queue_name: Name of the queue
            items: List of tuples (queue_item_dict, priority)
            use_pipeline: Use Redis pipelining for 10-100x performance improvement
        
        Returns:
            Number of items queued successfully
        """
        if not items:
            return 0
            
        try:
            if use_pipeline and len(items) > 1:
                # Use pipeline for massive performance improvement
                pipe = self.redis_client.pipeline(transaction=False)
                
                for queue_item, priority in items:
                    pipe.zadd(
                        f"queue:{queue_name}",
                        {json.dumps(queue_item, cls=DateTimeEncoder): priority}
                    )
                
                # Execute all commands at once
                results = await pipe.execute()
                successful = sum(1 for r in results if r)
                
                logger.info(f"Queued {successful}/{len(items)} items to {queue_name} using pipeline")
                return successful
            else:
                # Fall back to individual operations for small batches
                successful = 0
                for queue_item, priority in items:
                    try:
                        await self.redis_client.zadd(
                            f"queue:{queue_name}",
                            {json.dumps(queue_item, cls=DateTimeEncoder): priority}
                        )
                        successful += 1
                    except Exception:
                        pass
                
                logger.info(f"Queued {successful}/{len(items)} items to {queue_name}")
                return successful
                
        except Exception as e:
            logger.error(f"Failed to queue batch: {e}")
            return 0

    async def dequeue_batch(self, queue_name: str, batch_size: int = None) -> List[Dict[str, Any]]:
        """
        Dequeue a batch of points for processing
        Optimized to use batch operations (ZPOPMIN with count)

        Returns:
            List of point batches ready for database insertion
        """
        if batch_size is None:
            batch_size = self.batch_size

        try:
            # Use batch operation for better performance
            # ZPOPMIN with count is atomic and efficient
            priority_items = await self.redis_client.zpopmin(f"queue:{queue_name}", batch_size)
            
            if not priority_items:
                # Fall back to list queue if it exists (legacy support)
                items = await self.redis_client.rpop(f"list:{queue_name}", batch_size)
                if not items:
                    return []
                items = items if isinstance(items, list) else [items]
            else:
                # Extract just the data (not the scores)
                items = [item for item, score in priority_items]

            # Parse JSON items
            parsed_items = []
            for item in items:
                try:
                    parsed_items.append(json.loads(item))
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse queue item: {e}")
                    continue

            return parsed_items

        except Exception as e:
            logger.error(f"Failed to dequeue batch: {e}")
            return []

    async def get_queue_size(self, queue_name: str) -> int:
        """Get current queue size"""
        try:
            return await self.redis_client.llen(f"list:{queue_name}")
        except Exception as e:
            logger.error(f"Failed to get queue size: {e}")
            return 0

    async def clear_queue(self, queue_name: str):
        """Clear all items from a queue"""
        try:
            await self.redis_client.delete(f"list:{queue_name}")
            await self.redis_client.delete(f"queue:{queue_name}")
            logger.info(f"Cleared queue: {queue_name}")
        except Exception as e:
            logger.error(f"Failed to clear queue: {e}")

    async def initialize(self):
        """Initialize Redis connection (alias for connect)"""
        await self.connect()

    async def close(self):
        """Close Redis connection (alias for disconnect)"""
        await self.disconnect()

    async def is_connected(self) -> bool:
        """Check if Redis is connected"""
        try:
            if self.redis_client:
                await self.redis_client.ping()
                return True
            return False
        except Exception:
            return False
    
    async def cleanup_connections(self):
        """Clean up stale connections from the pool"""
        try:
            if self.redis_client and hasattr(self.redis_client, 'connection_pool'):
                pool = self.redis_client.connection_pool
                # Close all available connections to force recreation
                while pool._available_connections:
                    conn = pool._available_connections.pop()
                    await conn.disconnect()
                logger.info(f"Cleaned up Redis connection pool")
        except Exception as e:
            logger.error(f"Failed to cleanup connections: {e}")

    async def get_queue_stats(self) -> Dict[str, Any]:
        """Get statistics for all queues"""
        try:
            stats = {}
            for queue_type, queue_name in QUEUE_NAMES.items():
                queue_size = await self.get_queue_size(queue_name)
                priority_size = await self.redis_client.zcard(f"queue:{queue_name}")
                stats[queue_type] = {
                    'queue_size': queue_size,
                    'priority_queue_size': priority_size,
                    'total_pending': queue_size + priority_size
                }
            return stats
        except Exception as e:
            logger.error(f"Failed to get queue stats: {e}")
            return {}


# Global queue instance
redis_queue = RedisPointQueue()

# Queue names for different types of points
QUEUE_NAMES = {
    'live': 'live_points',
    'upload': 'upload_points',
    'flymaster': 'flymaster_points',
    'scoring': 'scoring_points'
}
