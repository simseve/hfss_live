import asyncio
import logging
from datetime import datetime, timezone
from redis_queue_system.redis_queue import redis_queue, QUEUE_NAMES
import json

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

async def test_queue_operations():
    """Test queue operations directly"""
    
    # Connect to Redis
    await redis_queue.connect()
    print(f"Connected to Redis: {await redis_queue.is_connected()}")
    
    # Create test data
    test_points = [
        {
            'flight_id': 'test_direct_flight',
            'flight_uuid': 'abc123',
            'datetime': datetime.now(timezone.utc),
            'lat': 46.52,
            'lon': 7.45,
            'alt': 1500
        }
    ]
    
    print(f"\n1. Queueing {len(test_points)} points...")
    success = await redis_queue.queue_points(
        QUEUE_NAMES['upload'],
        test_points,
        priority=0
    )
    print(f"   Queue result: {success}")
    
    # Check queue size
    size = await redis_queue.get_queue_size(QUEUE_NAMES['upload'])
    print(f"\n2. Queue size after queueing: {size}")
    
    # Check Redis directly
    zset_size = await redis_queue.redis_client.zcard(f"queue:{QUEUE_NAMES['upload']}")
    print(f"   Direct ZSET size: {zset_size}")
    
    # Try to dequeue
    print(f"\n3. Attempting to dequeue...")
    items = await redis_queue.dequeue_batch(QUEUE_NAMES['upload'], batch_size=10)
    print(f"   Dequeued {len(items)} items")
    
    if items:
        print(f"   First item: {json.dumps(items[0], indent=2, default=str)}")
    
    # Check queue size after dequeue
    size = await redis_queue.get_queue_size(QUEUE_NAMES['upload'])
    print(f"\n4. Queue size after dequeue: {size}")
    
    await redis_queue.disconnect()

if __name__ == "__main__":
    asyncio.run(test_queue_operations())