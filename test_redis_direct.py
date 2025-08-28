import asyncio
import redis.asyncio as redis
from config import settings

async def main():
    print("Testing Redis connection and queue operations...")
    
    # Connect to Redis using the same URL as the app
    redis_url = settings.get_redis_url()
    print(f"Connecting to: {redis_url}")
    
    client = redis.from_url(redis_url, decode_responses=True)
    
    # Test connection
    await client.ping()
    print("✓ Connected to Redis")
    
    # List all keys
    all_keys = await client.keys('*')
    print(f"\nAll Redis keys ({len(all_keys)} total):")
    for key in sorted(all_keys):
        if 'queue:' in key or 'list:' in key:
            print(f"  - {key}")
    
    # Check specific queue keys
    queue_names = ['live_points', 'upload_points', 'flymaster_points', 'scoring_points']
    print("\nQueue sizes:")
    for name in queue_names:
        # Check both formats
        zset_size = await client.zcard(f"queue:{name}")
        list_size = await client.llen(f"list:{name}")
        print(f"  {name}:")
        print(f"    - queue:{name} (ZSET): {zset_size} items")
        print(f"    - list:{name} (LIST): {list_size} items")
    
    # Try to peek at items in queues without removing them
    print("\nPeeking at queue contents (first item):")
    for name in queue_names:
        # Peek at ZSET (sorted set)
        items = await client.zrange(f"queue:{name}", 0, 0, withscores=True)
        if items:
            print(f"  queue:{name}: Found {len(items)} item(s)")
            # Show first item
            data, score = items[0]
            import json
            try:
                parsed = json.loads(data)
                print(f"    Item: {parsed.get('count', 'unknown')} points, timestamp: {parsed.get('timestamp', 'unknown')}")
            except:
                print(f"    Raw: {data[:100]}...")
    
    await client.aclose()

if __name__ == "__main__":
    asyncio.run(main())