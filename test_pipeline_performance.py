#!/usr/bin/env python3
"""
Test to demonstrate pipelining performance improvement
"""
import asyncio
import time
import json
from datetime import datetime, timezone
from redis_queue_system.redis_queue import redis_queue

async def test_pipeline_performance():
    print("\n🚀 PIPELINING PERFORMANCE TEST")
    print("=" * 50)
    
    # Initialize Redis queue
    await redis_queue.initialize()
    
    try:
        # Prepare test data
        num_batches = 100
        points_per_batch = 100
        
        print(f"\nTest Setup:")
        print(f"  Batches: {num_batches}")
        print(f"  Points per batch: {points_per_batch}")
        print(f"  Total points: {num_batches * points_per_batch}")
        
        # Test 1: Standard approach (one by one)
        print("\n1️⃣ STANDARD APPROACH (one by one):")
        await redis_queue.redis_client.delete("queue:test_standard")
        
        start = time.time()
        for i in range(num_batches):
            points = []
            for j in range(points_per_batch):
                points.append({
                    'lat': 47.0 + (i * 0.001),
                    'lon': 8.0 + (j * 0.001),
                    'elevation': 500 + j
                })
            
            # Current method - one zadd per batch
            await redis_queue.queue_points('test_standard', points, priority=i)
        
        elapsed_standard = time.time() - start
        throughput_standard = (num_batches * points_per_batch) / elapsed_standard
        
        print(f"  Time: {elapsed_standard:.2f} seconds")
        print(f"  Throughput: {throughput_standard:.0f} points/sec")
        
        # Test 2: Pipelined approach
        print("\n2️⃣ PIPELINED APPROACH (batch with pipeline):")
        await redis_queue.redis_client.delete("queue:test_pipelined")
        
        # Prepare all items for batch insert
        items = []
        for i in range(num_batches):
            points = []
            for j in range(points_per_batch):
                points.append({
                    'lat': 47.0 + (i * 0.001),
                    'lon': 8.0 + (j * 0.001),
                    'elevation': 500 + j
                })
            
            queue_item = {
                'points': points,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'count': len(points),
                'queue_type': 'test_pipelined'
            }
            items.append((queue_item, i))  # (item, priority)
        
        start = time.time()
        # New pipelined method
        successful = await redis_queue.queue_points_batch('test_pipelined', items, use_pipeline=True)
        elapsed_pipelined = time.time() - start
        throughput_pipelined = (successful * points_per_batch) / elapsed_pipelined
        
        print(f"  Time: {elapsed_pipelined:.2f} seconds")
        print(f"  Throughput: {throughput_pipelined:.0f} points/sec")
        print(f"  Successfully queued: {successful}/{num_batches} batches")
        
        # Calculate improvement
        speedup = throughput_pipelined / throughput_standard
        print(f"\n📊 PERFORMANCE IMPROVEMENT:")
        print(f"  Speed increase: {speedup:.1f}x faster")
        print(f"  Time saved: {elapsed_standard - elapsed_pipelined:.2f} seconds")
        print(f"  Efficiency gain: {((speedup - 1) * 100):.0f}%")
        
        # Test 3: Dequeue performance
        print("\n3️⃣ DEQUEUE PERFORMANCE:")
        
        start = time.time()
        total_dequeued = 0
        while True:
            items = await redis_queue.dequeue_batch('test_pipelined', batch_size=100)
            if not items:
                break
            total_dequeued += len(items)
        
        elapsed_dequeue = time.time() - start
        dequeue_rate = total_dequeued / elapsed_dequeue
        
        print(f"  Dequeued: {total_dequeued} batches")
        print(f"  Time: {elapsed_dequeue:.2f} seconds")
        print(f"  Rate: {dequeue_rate:.0f} batches/sec")
        
        # Clean up
        await redis_queue.redis_client.delete("queue:test_standard")
        await redis_queue.redis_client.delete("queue:test_pipelined")
        
        print("\n✅ CONCLUSION:")
        if speedup > 10:
            print(f"  🎉 Pipelining provides MASSIVE performance improvement!")
            print(f"  📈 {speedup:.0f}x faster queue operations")
            print(f"  💡 This optimization is CRITICAL for production")
        elif speedup > 2:
            print(f"  👍 Pipelining provides significant improvement")
            print(f"  📈 {speedup:.1f}x faster queue operations")
        else:
            print(f"  📊 Pipelining provides modest improvement")
            print(f"  📈 {speedup:.1f}x faster queue operations")
            
    finally:
        await redis_queue.close()

if __name__ == "__main__":
    asyncio.run(test_pipeline_performance())