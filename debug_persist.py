#!/usr/bin/env python3
import json
import redis
import os
from dotenv import load_dotenv

load_dotenv()

# Connect to Redis
r = redis.Redis(host='127.0.0.1', port=6379, db=0, decode_responses=True)

# Check all keys
print("Redis keys:")
for key in r.keys('*'):
    print(f"  {key}")

# Check upload queue
upload_queue = "upload_points"
upload_priority_queue = "upload_points_priority"

print(f"\n{upload_queue} size:", r.llen(upload_queue))
print(f"{upload_priority_queue} size:", r.zcard(upload_priority_queue))

# Get some items from the queue without removing them
items = r.lrange(upload_queue, 0, 5)
if items:
    print(f"\nFirst items in {upload_queue}:")
    for i, item in enumerate(items):
        data = json.loads(item)
        print(f"\nItem {i}:")
        if isinstance(data, list) and len(data) > 0:
            print(f"  Number of points: {len(data)}")
            print(f"  First point keys: {data[0].keys() if data else 'No points'}")
            if data:
                print(f"  First point sample: {json.dumps(data[0], indent=2, default=str)}")
        else:
            print(f"  Data: {json.dumps(data, indent=2, default=str)}")

# Check priority queue
priority_items = r.zrange(upload_priority_queue, 0, 5, withscores=True)
if priority_items:
    print(f"\nFirst items in {upload_priority_queue}:")
    for item, score in priority_items:
        data = json.loads(item)
        print(f"\n  Priority: {score}")
        if isinstance(data, list) and len(data) > 0:
            print(f"  Number of points: {len(data)}")
            print(f"  First point: {json.dumps(data[0], indent=2, default=str) if data else 'No points'}")