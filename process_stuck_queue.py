#!/usr/bin/env python3
"""
Script to process stuck items in Redis priority queue
"""
import asyncio
import json
import logging
from datetime import datetime
from redis.asyncio import Redis
from sqlalchemy.dialects.postgresql import insert
from database.db_conf import Session
from database.models import LiveTrackPoint
from config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def process_stuck_queue():
    """Process stuck items from priority queue"""
    
    # Connect to Redis
    redis_url = settings.get_redis_url()
    redis = await Redis.from_url(redis_url, decode_responses=True)
    
    try:
        # Check priority queue size
        queue_name = "queue:live_points"
        queue_size = await redis.zcard(queue_name)
        logger.info(f"Found {queue_size} items in priority queue: {queue_name}")
        
        if queue_size == 0:
            logger.info("No items to process")
            return
        
        # Process in batches
        batch_size = 100
        total_processed = 0
        total_points = 0
        errors = 0
        
        while True:
            # Get batch from priority queue (lowest scores first)
            items = await redis.zpopmin(queue_name, batch_size)
            
            if not items:
                break
            
            logger.info(f"Processing batch of {len(items)} items")
            
            # Process each item
            for item_data, score in items:
                try:
                    # Parse the JSON data
                    queue_item = json.loads(item_data)
                    points = queue_item.get('points', [])
                    
                    if not points:
                        continue
                    
                    # Insert points into database
                    with Session() as db:
                        try:
                            # Batch insert with conflict handling
                            stmt = insert(LiveTrackPoint).on_conflict_do_nothing(
                                index_elements=['flight_id', 'lat', 'lon', 'datetime']
                            )
                            db.execute(stmt, points)
                            db.commit()
                            
                            total_points += len(points)
                            logger.info(f"Inserted {len(points)} points from queue item")
                            
                        except Exception as e:
                            logger.error(f"Database error: {e}")
                            errors += 1
                            db.rollback()
                            
                            # Put the item back in the queue for retry
                            await redis.zadd(queue_name, {item_data: score})
                            logger.warning(f"Re-queued item due to error")
                            
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse queue item: {e}")
                    errors += 1
                    continue
                except Exception as e:
                    logger.error(f"Unexpected error processing item: {e}")
                    errors += 1
                    continue
            
            total_processed += len(items)
            logger.info(f"Progress: {total_processed}/{queue_size} items processed")
            
            # Small delay between batches
            await asyncio.sleep(0.1)
        
        # Final summary
        remaining = await redis.zcard(queue_name)
        logger.info(f"\n=== Processing Complete ===")
        logger.info(f"Total items processed: {total_processed}")
        logger.info(f"Total points inserted: {total_points}")
        logger.info(f"Errors encountered: {errors}")
        logger.info(f"Items remaining in queue: {remaining}")
        
    finally:
        await redis.close()

async def check_queue_status():
    """Check the current status of all queues"""
    
    # Connect to Redis
    redis_url = settings.get_redis_url()
    redis = await Redis.from_url(redis_url, decode_responses=True)
    
    try:
        queue_types = ['live_points', 'upload_points', 'flymaster_points', 'scoring_points']
        
        print("\n=== Current Queue Status ===")
        for queue_type in queue_types:
            list_size = await redis.llen(f"list:{queue_type}")
            priority_size = await redis.zcard(f"queue:{queue_type}")
            
            print(f"\n{queue_type}:")
            print(f"  List queue size: {list_size}")
            print(f"  Priority queue size: {priority_size}")
            
            if priority_size > 0:
                # Sample one item to check its age
                sample = await redis.zrange(f"queue:{queue_type}", 0, 0, withscores=True)
                if sample:
                    try:
                        item_data = json.loads(sample[0])
                        timestamp = item_data.get('timestamp', 'unknown')
                        print(f"  Oldest item timestamp: {timestamp}")
                    except:
                        pass
        
    finally:
        await redis.close()

async def main():
    """Main function"""
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == '--status':
        await check_queue_status()
    else:
        print("\n=== Redis Queue Processor ===")
        print("This will process stuck items from the priority queue")
        
        # First show status
        await check_queue_status()
        
        response = input("\nDo you want to process the stuck queue items? (yes/no): ")
        if response.lower() in ['yes', 'y']:
            await process_stuck_queue()
        else:
            print("Cancelled")

if __name__ == "__main__":
    asyncio.run(main())