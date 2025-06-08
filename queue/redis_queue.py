"""
Redis-based queue system for batching large point insertions
"""
import json
import logging
import asyncio
from typing import List, Dict, Any
from datetime import datetime, timezone
import redis.asyncio as redis
from config import settings

logger = logging.getLogger(__name__)


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

            self.redis_client = redis.from_url(
                redis_url,
                decode_responses=True,
                max_connections=getattr(settings, 'REDIS_MAX_CONNECTIONS', 20)
            )
            await self.redis_client.ping()
            logger.info(f"Redis connection established: {redis_url}")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise

    async def disconnect(self):
        """Close Redis connection"""
        if self.redis_client:
            await self.redis_client.close()

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

            # Add to priority queue
            await self.redis_client.zadd(
                f"queue:{queue_name}",
                {json.dumps(queue_item): priority}
            )

            # Also add to a simple list for FIFO processing if needed
            await self.redis_client.lpush(f"list:{queue_name}", json.dumps(queue_item))

            logger.info(f"Queued {len(points)} points to {queue_name}")
            return True

        except Exception as e:
            logger.error(f"Failed to queue points: {e}")
            return False

    async def dequeue_batch(self, queue_name: str, batch_size: int = None) -> List[Dict[str, Any]]:
        """
        Dequeue a batch of points for processing

        Returns:
            List of point batches ready for database insertion
        """
        if batch_size is None:
            batch_size = self.batch_size

        try:
            # Get items from list (FIFO)
            items = await self.redis_client.rpop(f"list:{queue_name}", batch_size)

            if not items:
                return []

            # Parse JSON items
            parsed_items = []
            for item in items if isinstance(items, list) else [items]:
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
