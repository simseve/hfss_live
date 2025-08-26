#!/usr/bin/env python3
"""
Final comprehensive queue test with proper flight creation
"""
import asyncio
import uuid
import time
from datetime import datetime, timezone
from database.db_conf import Session
from database.models import Race, Flight
from redis.asyncio import Redis
from config import settings
import json

async def create_test_data():
    """Create valid test race and flight"""
    with Session() as db:
        # Check if test race exists
        test_race = db.query(Race).filter(Race.name == "Test Race for Queue").first()
        if not test_race:
            test_race = Race(
                id=uuid.uuid4(),
                race_id=f"test-race-{uuid.uuid4().hex[:8]}",
                name="Test Race for Queue",
                date=datetime.now(timezone.utc),
                end_date=datetime.now(timezone.utc),
                timezone="UTC",
                location="Test Location"
            )
            db.add(test_race)
            db.commit()
            print(f"Created test race: {test_race.id}")
        else:
            print(f"Using existing test race: {test_race.id}")
        
        # Create test flight
        test_flight = Flight(
            id=uuid.uuid4(),
            flight_id=f"test-flight-{uuid.uuid4().hex[:8]}",
            race_uuid=test_race.id,
            race_id=str(test_race.id),
            pilot_id="test-pilot-1",
            pilot_name="Test Pilot",
            source="live"
        )
        db.add(test_flight)
        db.commit()
        print(f"Created test flight: {test_flight.id}")
        
        return str(test_race.id), str(test_flight.id)

async def test_queue_processing():
    """Test queue processing with valid and invalid data"""
    print("\n🚀 FINAL QUEUE PROCESSING TEST")
    print("=" * 50)
    
    # Create test data
    race_id, flight_uuid = await create_test_data()
    
    # Connect to Redis
    redis_url = settings.get_redis_url()
    redis = await Redis.from_url(redis_url, decode_responses=True)
    
    try:
        # Clear queues first
        await redis.delete("queue:live_points")
        await redis.delete("dlq:live_points")
        print("✅ Cleared queues")
        
        # Test 1: Valid points (should be processed successfully)
        print("\n📊 Test 1: Valid Flight Points")
        valid_points = []
        for i in range(10):
            point = {
                'datetime': datetime.now(timezone.utc).isoformat(),
                'flight_uuid': flight_uuid,
                'flight_id': f'flight-{flight_uuid[:8]}',
                'lat': 47.0 + (i * 0.001),
                'lon': 8.0 + (i * 0.001),
                'elevation': 500 + (i * 10)
            }
            valid_points.append(point)
        
        valid_item = {
            'points': valid_points,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'count': len(valid_points),
            'queue_type': 'live_points'
        }
        
        await redis.zadd("queue:live_points", {json.dumps(valid_item): 0})
        print(f"  Queued {len(valid_points)} valid points")
        
        # Test 2: Invalid points (should go to DLQ)
        print("\n📊 Test 2: Invalid Flight Points")
        invalid_uuid = "00000000-0000-0000-0000-000000000000"
        invalid_points = []
        for i in range(5):
            point = {
                'datetime': datetime.now(timezone.utc).isoformat(),
                'flight_uuid': invalid_uuid,
                'flight_id': f'invalid-flight',
                'lat': 48.0 + (i * 0.001),
                'lon': 9.0 + (i * 0.001),
                'elevation': 600 + (i * 10)
            }
            invalid_points.append(point)
        
        invalid_item = {
            'points': invalid_points,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'count': len(invalid_points),
            'queue_type': 'live_points'
        }
        
        await redis.zadd("queue:live_points", {json.dumps(invalid_item): 1})
        print(f"  Queued {len(invalid_points)} invalid points")
        
        # Test 3: Mixed batch (some valid, some invalid)
        print("\n📊 Test 3: Mixed Batch")
        mixed_points = []
        for i in range(6):
            if i % 2 == 0:
                # Valid
                point = {
                    'datetime': datetime.now(timezone.utc).isoformat(),
                    'flight_uuid': flight_uuid,
                    'flight_id': f'flight-{flight_uuid[:8]}',
                    'lat': 49.0 + (i * 0.001),
                    'lon': 10.0 + (i * 0.001),
                    'elevation': 700 + (i * 10)
                }
            else:
                # Invalid
                point = {
                    'datetime': datetime.now(timezone.utc).isoformat(),
                    'flight_uuid': invalid_uuid,
                    'flight_id': f'invalid-flight',
                    'lat': 49.0 + (i * 0.001),
                    'lon': 10.0 + (i * 0.001),
                    'elevation': 700 + (i * 10)
                }
            mixed_points.append(point)
        
        mixed_item = {
            'points': mixed_points,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'count': len(mixed_points),
            'queue_type': 'live_points'
        }
        
        await redis.zadd("queue:live_points", {json.dumps(mixed_item): 2})
        print(f"  Queued {len(mixed_points)} mixed points (3 valid, 3 invalid)")
        
        # Check initial queue state
        initial_queue = await redis.zcard("queue:live_points")
        initial_dlq = await redis.zcard("dlq:live_points")
        print(f"\n📈 Initial State:")
        print(f"  Queue size: {initial_queue}")
        print(f"  DLQ size: {initial_dlq}")
        
        # Force processing
        print("\n⚡ Triggering Processing...")
        import aiohttp
        async with aiohttp.ClientSession() as session:
            for _ in range(3):  # Process multiple times
                async with session.post(
                    "http://localhost:8001/admin/queue/force-process/live",
                    params={'batch_size': 10}
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        print(f"  Processed: {data.get('items_retrieved', 0)} items")
                await asyncio.sleep(2)
        
        # Final state
        final_queue = await redis.zcard("queue:live_points")
        final_dlq = await redis.zcard("dlq:live_points")
        
        print(f"\n📊 Final State:")
        print(f"  Queue size: {final_queue}")
        print(f"  DLQ size: {final_dlq}")
        
        # Check what's in DLQ
        if final_dlq > 0:
            dlq_items = await redis.zrange("dlq:live_points", 0, -1)
            print(f"\n🔍 DLQ Contents:")
            for item in dlq_items[:2]:  # Show first 2 items
                dlq_data = json.loads(item)
                print(f"  - Reason: {dlq_data.get('reason', 'Unknown')}")
                print(f"    Points: {dlq_data.get('count', 0)}")
        
        # Verify data in database
        print(f"\n✅ Verifying Database:")
        from database.models import LiveTrackPoint
        with Session() as db:
            count = db.query(LiveTrackPoint).filter(
                LiveTrackPoint.flight_uuid == flight_uuid
            ).count()
            print(f"  Points in database for valid flight: {count}")
        
        # Cleanup test data
        print(f"\n🧹 Cleaning up test data...")
        with Session() as db:
            db.query(Flight).filter(Flight.id == flight_uuid).delete()
            db.query(Race).filter(Race.name == "Test Race for Queue").delete()
            db.commit()
            print("  Test data cleaned")
        
        await redis.delete("queue:live_points")
        await redis.delete("dlq:live_points")
        print("  Queues cleared")
        
        print("\n✅ Test completed successfully!")
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await redis.aclose()

async def test_load_and_performance():
    """Load test with realistic data volume"""
    print("\n🚀 LOAD AND PERFORMANCE TEST")
    print("=" * 50)
    
    # Create test flight
    race_id, flight_uuid = await create_test_data()
    
    redis_url = settings.get_redis_url()
    redis = await Redis.from_url(redis_url, decode_responses=True)
    
    try:
        # Clear queues
        await redis.delete("queue:live_points")
        
        # Generate large batch
        num_batches = 100
        points_per_batch = 50
        
        print(f"📊 Generating {num_batches} batches with {points_per_batch} points each")
        print(f"   Total: {num_batches * points_per_batch} points")
        
        start = time.time()
        tasks = []
        
        for batch_id in range(num_batches):
            points = []
            for i in range(points_per_batch):
                point = {
                    'datetime': datetime.now(timezone.utc).isoformat(),
                    'flight_uuid': flight_uuid if batch_id % 10 != 0 else "00000000-0000-0000-0000-000000000000",
                    'flight_id': f'flight-{flight_uuid[:8]}',
                    'lat': 47.0 + (batch_id * 0.001) + (i * 0.00001),
                    'lon': 8.0 + (batch_id * 0.001) + (i * 0.00001),
                    'elevation': 500 + (i * 10)
                }
                points.append(point)
            
            item = {
                'points': points,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'count': len(points),
                'queue_type': 'live_points',
                'batch_id': batch_id
            }
            
            task = redis.zadd("queue:live_points", {json.dumps(item): batch_id})
            tasks.append(task)
        
        await asyncio.gather(*tasks)
        queue_time = time.time() - start
        
        print(f"✅ Queued in {queue_time:.2f}s ({(num_batches * points_per_batch) / queue_time:.0f} points/sec)")
        
        initial_size = await redis.zcard("queue:live_points")
        print(f"📈 Queue size: {initial_size}")
        
        # Process
        print("\n⚡ Processing...")
        process_start = time.time()
        
        import aiohttp
        async with aiohttp.ClientSession() as session:
            for i in range(10):
                async with session.post(
                    "http://localhost:8001/admin/queue/force-process/live",
                    params={'batch_size': 500}
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        items = data.get('items_retrieved', 0)
                        if items > 0:
                            print(f"  Batch {i+1}: Processed {items} items")
                await asyncio.sleep(0.5)
        
        process_time = time.time() - process_start
        
        final_size = await redis.zcard("queue:live_points")
        dlq_size = await redis.zcard("dlq:live_points")
        
        print(f"\n📊 Performance Results:")
        print(f"  Queue time: {queue_time:.2f}s")
        print(f"  Process time: {process_time:.2f}s")
        print(f"  Items processed: {initial_size - final_size}")
        print(f"  Processing rate: {(initial_size - final_size) / process_time:.0f} items/sec")
        print(f"  Final queue: {final_size}")
        print(f"  DLQ: {dlq_size}")
        
        # Cleanup
        with Session() as db:
            db.query(Flight).filter(Flight.id == flight_uuid).delete()
            db.query(Race).filter(Race.name == "Test Race for Queue").delete()
            db.commit()
        
        await redis.delete("queue:live_points")
        await redis.delete("dlq:live_points")
        
        print("\n✅ Load test completed!")
        
    finally:
        await redis.aclose()

async def main():
    print("=" * 60)
    print("COMPREHENSIVE QUEUE SYSTEM TEST")
    print("=" * 60)
    
    # Test 1: Basic queue processing
    await test_queue_processing()
    
    # Wait a bit
    await asyncio.sleep(2)
    
    # Test 2: Load and performance
    await test_load_and_performance()
    
    print("\n" + "=" * 60)
    print("ALL TESTS COMPLETED")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())