#!/usr/bin/env python3
"""
Test live endpoint batch processing and trigger updates
"""

import requests
import time
from datetime import datetime, timezone, timedelta
import uuid

BASE_URL = "http://127.0.0.1:8000"
TEST_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJwaWxvdF9pZCI6IjY4YWFkYmRjNWRhNTI1MDYwZWRhYWVjMiIsInJhY2VfaWQiOiI2OGFhZGJiODVkYTUyNTA2MGVkYWFlYmYiLCJwaWxvdF9uYW1lIjoiU2ltb25lIFNldmVyaW5pIiwiZXhwIjoxNzk2MTY5NTk5LCJyYWNlIjp7Im5hbWUiOiJIRlNTIEFwcCBUZXN0aW5nIiwiZGF0ZSI6IjIwMjUtMDEtMDEiLCJ0aW1lem9uZSI6IkV1cm9wZS9Sb21lIiwibG9jYXRpb24iOiJMYXZlbm8iLCJlbmRfZGF0ZSI6IjIwMjYtMTItMDEifSwiZW5kcG9pbnRzIjp7ImxpdmUiOiIvbGl2ZSIsInVwbG9hZCI6Ii91cGxvYWQifX0.MU5OrqbbTRX36Qves9wDx62btbBWkumVX_WYfmXqsYo"


def wait_for_processing(timeout=10):
    """Wait for queue to be empty"""
    start = time.time()
    while time.time() - start < timeout:
        response = requests.get(f"{BASE_URL}/queue/status")
        if response.status_code == 200:
            status = response.json()
            live_pending = status['queue_stats']['live']['total_pending']
            if live_pending == 0:
                return True
        time.sleep(0.5)
    return False


def check_points_in_db(flight_id):
    """Check how many points are in database"""
    from config import settings
    from sqlalchemy import create_engine, text
    engine = create_engine(settings.DATABASE_URL)
    
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT COUNT(*) as count,
                   MIN(lat) as min_lat,
                   MAX(lat) as max_lat
            FROM live_track_points
            WHERE flight_id = :flight_id
        """), {"flight_id": flight_id})
        
        row = result.fetchone()
        return row[0], row[1], row[2]


def main():
    print("\n" + "="*60)
    print("LIVE BATCH PROCESSING TEST")
    print("="*60)
    
    flight_id = f"batch-test-{uuid.uuid4().hex[:8]}"
    base_time = datetime.now(timezone.utc)
    
    # Batch 1: 3 points
    print(f"\n📤 Batch 1: Sending 3 points...")
    points_1 = [
        {
            "datetime": (base_time + timedelta(seconds=i*10)).isoformat().replace('+00:00', 'Z'),
            "lat": 45.0 + i * 0.001,
            "lon": 6.0 + i * 0.001,
            "elevation": 1000 + i * 10
        }
        for i in range(3)
    ]
    
    response = requests.post(
        f"{BASE_URL}/tracking/live",
        params={"token": TEST_TOKEN},
        json={
            "flight_id": flight_id,
            "device_id": "test-batch",
            "track_points": points_1
        }
    )
    
    if response.status_code == 202:
        print(f"   ✅ Batch 1 accepted")
    else:
        print(f"   ❌ Failed: {response.text}")
        return
    
    # Wait for processing
    print("   ⏳ Waiting for processing...")
    if wait_for_processing():
        count, min_lat, max_lat = check_points_in_db(flight_id)
        if count > 0:
            print(f"   📊 Points in DB: {count} (lat range: {min_lat:.3f} to {max_lat:.3f})")
        else:
            print(f"   📊 Points in DB: {count} (no points inserted yet)")
    else:
        print("   ⚠️  Queue still has pending items")
    
    # Batch 2: 2 more points
    print(f"\n📤 Batch 2: Sending 2 more points...")
    points_2 = [
        {
            "datetime": (base_time + timedelta(seconds=30 + i*10)).isoformat().replace('+00:00', 'Z'),
            "lat": 45.003 + i * 0.001,
            "lon": 6.003 + i * 0.001,
            "elevation": 1030 + i * 10
        }
        for i in range(2)
    ]
    
    response = requests.post(
        f"{BASE_URL}/tracking/live",
        params={"token": TEST_TOKEN},
        json={
            "flight_id": flight_id,
            "device_id": "test-batch",
            "track_points": points_2
        }
    )
    
    if response.status_code == 202:
        print(f"   ✅ Batch 2 accepted")
    else:
        print(f"   ❌ Failed: {response.text}")
        return
    
    # Wait for processing
    print("   ⏳ Waiting for processing...")
    if wait_for_processing():
        count, min_lat, max_lat = check_points_in_db(flight_id)
        if count > 0:
            print(f"   📊 Points in DB: {count} (lat range: {min_lat:.3f} to {max_lat:.3f})")
        else:
            print(f"   📊 Points in DB: {count} (no points inserted yet)")
    else:
        print("   ⚠️  Queue still has pending items")
    
    # Check flight record
    print(f"\n📊 Checking flight record...")
    from config import settings
    from sqlalchemy import create_engine, text
    engine = create_engine(settings.DATABASE_URL)
    
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT 
                total_points,
                first_fix->>'lat' as first_lat,
                first_fix->>'datetime' as first_time,
                last_fix->>'lat' as last_lat,
                last_fix->>'datetime' as last_time
            FROM flights
            WHERE flight_id = :flight_id
        """), {"flight_id": flight_id})
        
        flight = result.fetchone()
        if flight:
            print(f"   Total points (from trigger): {flight[0]}")
            print(f"   First fix: lat={flight[1]}, time={flight[2]}")
            print(f"   Last fix: lat={flight[3]}, time={flight[4]}")
            
            if flight[0] == 5:
                print(f"   ✅ Trigger correctly counted 5 points (3 + 2)")
            else:
                print(f"   ⚠️  Expected 5 points, got {flight[0]}")
    
    # Test duplicates
    print(f"\n📤 Testing duplicate handling...")
    print(f"   Resending the same 2 points from batch 2...")
    
    response = requests.post(
        f"{BASE_URL}/tracking/live",
        params={"token": TEST_TOKEN},
        json={
            "flight_id": flight_id,
            "device_id": "test-batch",
            "track_points": points_2  # Same points as batch 2
        }
    )
    
    if response.status_code == 202:
        print(f"   ✅ Duplicate batch accepted (will be filtered by DB)")
    
    # Wait and check
    print("   ⏳ Waiting for processing...")
    time.sleep(3)
    count, _, _ = check_points_in_db(flight_id)
    print(f"   📊 Points in DB after duplicates: {count}")
    if count == 5:
        print(f"   ✅ Duplicates were correctly ignored (still 5 points)")
    else:
        print(f"   ⚠️  Point count changed to {count}")


if __name__ == "__main__":
    main()