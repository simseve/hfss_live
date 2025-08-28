#!/usr/bin/env python3
"""
Test 500 point upload with detailed monitoring
"""

import requests
import time
from datetime import datetime, timezone, timedelta
import uuid

BASE_URL = "http://127.0.0.1:8000"
TEST_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJwaWxvdF9pZCI6IjY4YWFkYmRjNWRhNTI1MDYwZWRhYWVjMiIsInJhY2VfaWQiOiI2OGFhZGJiODVkYTUyNTA2MGVkYWFlYmYiLCJwaWxvdF9uYW1lIjoiU2ltb25lIFNldmVyaW5pIiwiZXhwIjoxNzk2MTY5NTk5LCJyYWNlIjp7Im5hbWUiOiJIRlNTIEFwcCBUZXN0aW5nIiwiZGF0ZSI6IjIwMjUtMDEtMDEiLCJ0aW1lem9uZSI6IkV1cm9wZS9Sb21lIiwibG9jYXRpb24iOiJMYXZlbm8iLCJlbmRfZGF0ZSI6IjIwMjYtMTItMDEifSwiZW5kcG9pbnRzIjp7ImxpdmUiOiIvbGl2ZSIsInVwbG9hZCI6Ii91cGxvYWQifX0.MU5OrqbbTRX36Qves9wDx62btbBWkumVX_WYfmXqsYo"


def main():
    print("\n" + "="*60)
    print("500 POINT UPLOAD TEST")
    print("="*60)
    
    flight_id = f"test-500-{uuid.uuid4().hex[:8]}"
    base_time = datetime.now(timezone.utc)
    
    # Generate 500 points
    print("📝 Generating 500 points...")
    points = []
    for i in range(500):
        point = {
            "datetime": (base_time + timedelta(seconds=i*10)).isoformat().replace('+00:00', 'Z'),
            "lat": 46.0 + (i * 0.00005),
            "lon": 7.0 + (i * 0.00005),
            "elevation": 1500 + (i % 200)
        }
        points.append(point)
    
    print(f"   Generated {len(points)} points")
    print(f"   Time span: {points[0]['datetime']} to {points[-1]['datetime']}")
    
    # Upload
    print(f"\n📤 Uploading 500 points...")
    print(f"   Flight ID: {flight_id}")
    
    payload = {
        "flight_id": flight_id,
        "device_id": "test-500",
        "track_points": points
    }
    
    start_time = time.time()
    response = requests.post(
        f"{BASE_URL}/tracking/upload",
        params={"token": TEST_TOKEN},
        json=payload,
        timeout=30
    )
    upload_time = time.time() - start_time
    
    if response.status_code == 202:
        result = response.json()
        print(f"   ✅ Upload accepted in {upload_time:.2f} seconds")
        print(f"   Flight UUID: {result.get('id')}")
        flight_uuid = result.get('id')
    else:
        print(f"   ❌ Upload failed: {response.status_code}")
        print(f"   Response: {response.text}")
        return
    
    # Monitor processing
    print(f"\n⏳ Monitoring processing...")
    from config import settings
    from sqlalchemy import create_engine, text
    
    engine = create_engine(settings.DATABASE_URL)
    
    max_checks = 20
    for check in range(max_checks):
        time.sleep(2)
        
        # Check database
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
                print(f"   Check {check+1}/{max_checks}: Trigger={trigger_points}, Actual={actual_points}")
                
                if trigger_points == 500 and actual_points == 500:
                    print(f"\n✅ SUCCESS! All 500 points processed!")
                    print(f"   Processing took ~{(check+1)*2} seconds")
                    
                    # Verify the triggers worked
                    result = conn.execute(text("""
                        SELECT 
                            first_fix->>'lat' as first_lat,
                            last_fix->>'lat' as last_lat
                        FROM flights
                        WHERE flight_id = :fid
                    """), {"fid": flight_id})
                    
                    fix = result.fetchone()
                    if fix:
                        print(f"   First fix lat: {fix[0]}")
                        print(f"   Last fix lat: {fix[1]}")
                    return
                
                if actual_points > 0 and actual_points < 500:
                    print(f"      (Processing... {actual_points}/500 points)")
            else:
                print(f"   Check {check+1}/{max_checks}: Flight not found yet")
        
        # Check queue status
        if check % 5 == 4:  # Every 5 checks
            response = requests.get(f"{BASE_URL}/queue/status")
            if response.status_code == 200:
                status = response.json()
                pending = status['queue_stats']['upload']['total_pending']
                if pending > 0:
                    print(f"      Queue: {pending} items pending")
    
    print(f"\n❌ Processing did not complete within {max_checks*2} seconds")
    print(f"   Final status: Trigger={trigger_points}, Actual={actual_points}")


if __name__ == "__main__":
    main()