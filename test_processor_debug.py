import asyncio
import logging
from redis_queue_system.redis_queue import redis_queue, QUEUE_NAMES
from redis_queue_system.point_processor import point_processor

logging.basicConfig(level=logging.DEBUG)

async def main():
    print("Testing queue processor...")
    
    # Connect to Redis
    await redis_queue.connect()
    print(f"Redis connected: {await redis_queue.is_connected()}")
    
    # Check queue contents
    for name in QUEUE_NAMES.values():
        size = await redis_queue.get_queue_size(name)
        print(f"Queue {name}: {size} items")
    
    # Start processor
    await point_processor.start()
    
    # Wait a bit
    await asyncio.sleep(5)
    
    # Stop processor
    await point_processor.stop()
    
    print("Done")

asyncio.run(main())
