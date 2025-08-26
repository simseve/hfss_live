#!/usr/bin/env python3
"""
Script to clear orphaned items from Redis queue (items with missing flight references)
"""
import asyncio
import json
import logging
from redis.asyncio import Redis
from config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def clear_orphaned_queue():
    """Clear orphaned items from priority queue"""
    
    # Connect to Redis
    redis_url = settings.get_redis_url()
    redis = await Redis.from_url(redis_url, decode_responses=True)
    
    try:
        queue_types = {
            'live_points': 'queue:live_points',
            'upload_points': 'queue:upload_points'
        }
        
        for queue_type, queue_name in queue_types.items():
            # Check queue size
            queue_size = await redis.zcard(queue_name)
            
            if queue_size > 0:
                logger.info(f"\nClearing {queue_size} orphaned items from {queue_type}")
                
                # Clear the entire priority queue
                cleared = await redis.delete(queue_name)
                
                if cleared:
                    logger.info(f"✓ Cleared {queue_type} priority queue")
                else:
                    logger.info(f"Failed to clear {queue_type}")
                    
            # Also clear the list queue if any
            list_name = f"list:{queue_type}"
            list_size = await redis.llen(list_name)
            
            if list_size > 0:
                logger.info(f"Clearing {list_size} items from {queue_type} list queue")
                await redis.delete(list_name)
                logger.info(f"✓ Cleared {queue_type} list queue")
        
        logger.info("\n=== Queue Cleanup Complete ===")
        
        # Show final status
        print("\nFinal Queue Status:")
        for queue_type in queue_types.keys():
            list_size = await redis.llen(f"list:{queue_type}")
            priority_size = await redis.zcard(f"queue:{queue_type}")
            print(f"{queue_type}: list={list_size}, priority={priority_size}")
            
    finally:
        await redis.aclose()

async def main():
    """Main function"""
    print("=== Redis Queue Cleanup ===")
    print("This will clear all orphaned items from the Redis queues")
    print("These are track points with missing flight references")
    print("")
    
    response = input("Are you sure you want to clear the orphaned queue items? (yes/no): ")
    if response.lower() in ['yes', 'y']:
        await clear_orphaned_queue()
    else:
        print("Cancelled")

if __name__ == "__main__":
    asyncio.run(main())