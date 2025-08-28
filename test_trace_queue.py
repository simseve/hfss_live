import asyncio
import logging
from redis_queue_system.redis_queue import redis_queue, QUEUE_NAMES

# Enable debug logging
logging.basicConfig(level=logging.DEBUG)

async def trace_queue():
    """Trace the queue operations step by step"""
    
    await redis_queue.connect()
    print(f"Connected to Redis: {redis_queue.redis_client}")
    
    # Get the actual queue name
    queue_name = QUEUE_NAMES['upload']
    queue_key = f"queue:{queue_name}"
    print(f"Queue name: {queue_name}")
    print(f"Queue key: {queue_key}")
    
    # Clear queue
    await redis_queue.redis_client.delete(queue_key)
    print("Cleared queue")
    
    # Add item directly
    import json
    from datetime import datetime, timezone
    
    test_item = {
        'points': [{'test': 'trace_test'}],
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'count': 1,
        'queue_type': queue_name
    }
    
    # Add using ZADD directly
    result = await redis_queue.redis_client.zadd(
        queue_key,
        {json.dumps(test_item): 0}
    )
    print(f"ZADD result: {result}")
    
    # Check size
    size = await redis_queue.redis_client.zcard(queue_key)
    print(f"Queue size after ZADD: {size}")
    
    # Wait a moment
    await asyncio.sleep(1)
    
    # Check size again
    size = await redis_queue.redis_client.zcard(queue_key)
    print(f"Queue size after 1 second: {size}")
    
    # Check if there's a background task consuming it
    all_keys = await redis_queue.redis_client.keys('*')
    queue_keys = [k for k in all_keys if 'queue' in k or 'upload' in k]
    print(f"Queue-related keys: {queue_keys}")
    
    await redis_queue.disconnect()

asyncio.run(trace_queue())