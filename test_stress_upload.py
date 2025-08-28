#!/usr/bin/env python3
"""
Stress test with 500 and 1000 point uploads
"""

import requests
import time
from datetime import datetime, timezone, timedelta
import uuid

BASE_URL = "http://127.0.0.1:8000"
TEST_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJwaWxvdF9pZCI6IjY4YWFkYmRjNWRhNTI1MDYwZWRhYWVjMiIsInJhY2VfaWQiOiI2OGFhZGJiODVkYTUyNTA2MGVkYWFlYmYiLCJwaWxvdF9uYW1lIjoiU2ltb25lIFNldmVyaW5pIiwiZXhwIjoxNzk2MTY5NTk5LCJyYWNlIjp7Im5hbWUiOiJIRlNTIEFwcCBUZXN0aW5nIiwiZGF0ZSI6IjIwMjUtMDEtMDEiLCJ0aW1lem9uZSI6IkV1cm9wZS9Sb21lIiwibG9jYXRpb24iOiJMYXZlbm8iLCJlbmRfZGF0ZSI6IjIwMjYtMTItMDEifSwiZW5kcG9pbnRzIjp7ImxpdmUiOiIvbGl2ZSIsInVwbG9hZCI6Ii91cGxvYWQifX0.MU5OrqbbTRX36Qves9wDx62btbBWkumVX_WYfmXqsYo"


def generate_points(num_points):
    """Generate simple track points"""
    points = []
    base_time = datetime.now(timezone.utc)
    
    for i in range(num_points):
        # 10 seconds between points
        timestamp = (base_time + timedelta(seconds=i*10)).isoformat().replace('+00:00', 'Z')
        
        point = {
            "datetime": timestamp,
            "lat": 46.0 + (i * 0.00001),
            "lon": 7.0 + (i * 0.00001),
            "elevation": 1500 + (i % 100),  # Vary elevation
        }
        points.append(point)
    
    return points


def test_upload(num_points):
    """Test uploading a specific number of points"""
    print(f"\n{'='*60}")
    print(f"Testing upload with {num_points} points")
    print(f"{'='*60}")
    
    flight_id = f"stress-test-{num_points}-{uuid.uuid4().hex[:8]}"
    
    # Generate points
    print(f"📝 Generating {num_points} points...")
    track_points = generate_points(num_points)
    
    # Upload
    print(f"📤 Uploading {num_points} points...")
    print(f"   Flight ID: {flight_id}")
    
    payload = {
        "flight_id": flight_id,
        "device_id": f"stress-test-{num_points}",
        "track_points": track_points
    }
    
    start_time = time.time()
    response = requests.post(
        f"{BASE_URL}/tracking/upload",
        params={"token": TEST_TOKEN},
        json=payload,
        timeout=30  # 30 second timeout
    )
    upload_time = time.time() - start_time
    
    if response.status_code == 202:
        print(f"   ✅ Upload accepted in {upload_time:.2f} seconds")
        print(f"   Flight UUID: {response.json().get('id')}")
    else:
        print(f"   ❌ Upload failed: {response.status_code}")
        return False
    
    # Wait for processing
    print(f"   ⏳ Waiting for processing...")
    time.sleep(min(10, num_points/100))  # Scale wait time with points
    
    # Verify
    from config import settings
    from sqlalchemy import create_engine, text
    
    engine = create_engine(settings.DATABASE_URL)
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT 
                total_points,
                (SELECT COUNT(*) FROM uploaded_track_points WHERE flight_id = :fid) as actual_points
            FROM flights
            WHERE flight_id = :fid
        """), {"fid": flight_id})
        
        row = result.fetchone()
        if row:
            trigger_points, actual_points = row
            print(f"\n   📊 Results:")
            print(f"      Trigger count: {trigger_points}")
            print(f"      Actual count: {actual_points}")
            
            if trigger_points == num_points and actual_points == num_points:
                print(f"   ✅ All {num_points} points processed successfully!")
                return True
            else:
                print(f"   ❌ Point count mismatch (expected {num_points})")
                return False
        else:
            print(f"   ❌ Flight not found")
            return False


def main():
    print("\n" + "="*60)
    print("STRESS TEST - LARGE UPLOADS")
    print(f"Server: {BASE_URL}")
    print("="*60)
    
    # Test with increasing sizes
    test_sizes = [500, 1000]
    results = {}
    
    for size in test_sizes:
        try:
            success = test_upload(size)
            results[size] = success
            
            # Give server a break between tests
            if size < test_sizes[-1]:
                print(f"\n⏸️  Pausing 5 seconds before next test...")
                time.sleep(5)
        except Exception as e:
            print(f"   ❌ Test failed with error: {e}")
            results[size] = False
    
    # Summary
    print("\n" + "="*60)
    print("STRESS TEST SUMMARY")
    print("="*60)
    
    for size, success in results.items():
        if success:
            print(f"✅ {size} points: SUCCESS")
        else:
            print(f"❌ {size} points: FAILED")
    
    # Check final queue status
    response = requests.get(f"{BASE_URL}/queue/status")
    if response.status_code == 200:
        status = response.json()
        print(f"\n📊 Final queue stats:")
        print(f"   Total processed: {status['processor_stats']['processed']}")
        print(f"   Total failed: {status['processor_stats']['failed']}")


if __name__ == "__main__":
    main()