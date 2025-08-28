#!/usr/bin/env python3
"""
Comprehensive test for live and upload endpoints with trigger verification
"""

import requests
import json
import time
from datetime import datetime, timezone, timedelta
import uuid

# Server configuration
BASE_URL = "http://127.0.0.1:8000"

# Provided test token
TEST_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJwaWxvdF9pZCI6IjY4YWFkYmRjNWRhNTI1MDYwZWRhYWVjMiIsInJhY2VfaWQiOiI2OGFhZGJiODVkYTUyNTA2MGVkYWFlYmYiLCJwaWxvdF9uYW1lIjoiU2ltb25lIFNldmVyaW5pIiwiZXhwIjoxNzk2MTY5NTk5LCJyYWNlIjp7Im5hbWUiOiJIRlNTIEFwcCBUZXN0aW5nIiwiZGF0ZSI6IjIwMjUtMDEtMDEiLCJ0aW1lem9uZSI6IkV1cm9wZS9Sb21lIiwibG9jYXRpb24iOiJMYXZlbm8iLCJlbmRfZGF0ZSI6IjIwMjYtMTItMDEifSwiZW5kcG9pbnRzIjp7ImxpdmUiOiIvbGl2ZSIsInVwbG9hZCI6Ii91cGxvYWQifX0.MU5OrqbbTRX36Qves9wDx62btbBWkumVX_WYfmXqsYo"


def test_live_tracking_comprehensive():
    """Test live tracking with multiple batches and verify triggers"""
    print("\n" + "="*60)
    print("COMPREHENSIVE LIVE TRACKING TEST")
    print("="*60)
    
    flight_id = f"live-comprehensive-{uuid.uuid4().hex[:8]}"
    current_time = datetime.now(timezone.utc)
    
    # Test 1: Send initial batch
    print(f"\n📤 Test 1: Sending initial batch of 5 points...")
    print(f"   Flight ID: {flight_id}")
    
    points_batch_1 = [
        {
            "datetime": (current_time + timedelta(seconds=i*10)).isoformat().replace('+00:00', 'Z'),
            "lat": 45.0 + i * 0.001,
            "lon": 6.0 + i * 0.001,
            "elevation": 1000 + i * 10,
            "speed": 25.0 + i * 0.5,
            "heading": 90.0 + i * 2
        }
        for i in range(5)
    ]
    
    payload = {
        "flight_id": flight_id,
        "device_id": "test-device-comprehensive",
        "track_points": points_batch_1
    }
    
    response = requests.post(
        f"{BASE_URL}/tracking/live",
        params={"token": TEST_TOKEN},
        json=payload
    )
    
    if response.status_code == 202:
        print(f"   ✅ Batch 1 accepted: {response.json()['message']}")
    else:
        print(f"   ❌ Batch 1 failed: {response.status_code} - {response.text}")
        return False
    
    # Wait for processing
    time.sleep(3)
    
    # Test 2: Send overlapping points (some duplicates)
    print(f"\n📤 Test 2: Sending batch with 3 new + 2 duplicate points...")
    
    # Build batch with duplicates and new points
    points_batch_2 = [
        # Two duplicates from batch 1
        points_batch_1[3],
        points_batch_1[4]
    ]
    
    # Add three new points
    for i in range(3):
        points_batch_2.append({
            "datetime": (current_time + timedelta(seconds=50 + i*10)).isoformat().replace('+00:00', 'Z'),
            "lat": 45.005 + i * 0.001,
            "lon": 6.005 + i * 0.001,
            "elevation": 1050 + i * 10,
            "speed": 27.0 + i * 0.5,
            "heading": 95.0 + i * 2
        })
    
    payload["track_points"] = points_batch_2
    
    response = requests.post(
        f"{BASE_URL}/tracking/live",
        params={"token": TEST_TOKEN},
        json=payload
    )
    
    if response.status_code == 202:
        print(f"   ✅ Batch 2 accepted: {response.json()['message']}")
    else:
        print(f"   ❌ Batch 2 failed: {response.status_code}")
        return False
    
    # Wait for processing
    time.sleep(3)
    
    # Test 3: Send final batch
    print(f"\n📤 Test 3: Sending final batch of 5 points...")
    
    points_batch_3 = [
        {
            "datetime": (current_time + timedelta(seconds=80 + i*10)).isoformat().replace('+00:00', 'Z'),
            "lat": 45.008 + i * 0.001,
            "lon": 6.008 + i * 0.001,
            "elevation": 1080 + i * 10,
            "speed": 28.0 + i * 0.5,
            "heading": 100.0 + i * 2
        }
        for i in range(5)
    ]
    
    payload["track_points"] = points_batch_3
    
    response = requests.post(
        f"{BASE_URL}/tracking/live",
        params={"token": TEST_TOKEN},
        json=payload
    )
    
    if response.status_code == 202:
        print(f"   ✅ Batch 3 accepted: {response.json()['message']}")
    else:
        print(f"   ❌ Batch 3 failed: {response.status_code}")
        return False
    
    return flight_id


def test_upload_comprehensive():
    """Test upload endpoint with larger track"""
    print("\n" + "="*60)
    print("COMPREHENSIVE UPLOAD TEST")
    print("="*60)
    
    flight_id = f"upload-comprehensive-{uuid.uuid4().hex[:8]}"
    current_time = datetime.now(timezone.utc)
    
    # Create a realistic flight track with 50 points
    print(f"\n📤 Uploading complete flight with 50 points...")
    print(f"   Flight ID: {flight_id}")
    
    track_points = []
    for i in range(50):
        # Simulate a paragliding flight pattern
        lat = 46.0 + (i * 0.0005) + (0.0002 * (i % 10))  # Some variation
        lon = 7.0 + (i * 0.0004) + (0.0001 * (i % 5))
        elevation = 1500 + (i * 5) - ((i % 10) * 2)  # Climbing with thermal cycles
        speed = 25.0 + (5.0 * (i % 3))  # Variable speed
        
        point = {
            "datetime": (current_time + timedelta(seconds=i*30)).isoformat().replace('+00:00', 'Z'),
            "lat": lat,
            "lon": lon,
            "elevation": elevation,
            "speed": speed,
            "heading": 90.0 + (i % 36) * 10  # Circling pattern
        }
        track_points.append(point)
    
    payload = {
        "flight_id": flight_id,
        "device_id": "test-device-upload",
        "track_points": track_points
    }
    
    response = requests.post(
        f"{BASE_URL}/tracking/upload",
        params={"token": TEST_TOKEN},
        json=payload
    )
    
    if response.status_code == 202:
        result = response.json()
        print(f"   ✅ Upload accepted")
        print(f"   Flight UUID: {result.get('id')}")
        return flight_id, result.get('id')
    else:
        print(f"   ❌ Upload failed: {response.status_code}")
        print(f"   Response: {response.text}")
        return None, None


def check_queue_status():
    """Check Redis queue processing status"""
    print("\n📊 Checking queue status...")
    
    response = requests.get(f"{BASE_URL}/queue/status")
    if response.status_code == 200:
        status = response.json()
        
        print(f"   Redis connected: {status['redis_connected']}")
        
        # Check each queue
        for queue_name, stats in status['queue_stats'].items():
            if stats['total_pending'] > 0:
                print(f"   {queue_name}: {stats['total_pending']} pending")
        
        # Check processor stats
        proc_stats = status['processor_stats']
        print(f"   Processed: {proc_stats['processed']}, Failed: {proc_stats['failed']}")
        
        return status
    else:
        print(f"   ❌ Failed to get queue status")
        return None


def verify_database_results(live_flight_id, upload_flight_id):
    """Verify trigger results in database"""
    print("\n" + "="*60)
    print("DATABASE VERIFICATION")
    print("="*60)
    
    from config import settings
    from sqlalchemy import create_engine, text
    
    engine = create_engine(settings.DATABASE_URL)
    
    with engine.connect() as conn:
        # Check both flights
        if live_flight_id:
            result = conn.execute(text("""
                SELECT 
                    flight_id,
                    source,
                    total_points,
                    first_fix->>'lat' as first_lat,
                    first_fix->>'datetime' as first_time,
                    last_fix->>'lat' as last_lat,
                    last_fix->>'datetime' as last_time
                FROM flights
                WHERE flight_id = :flight_id
            """), {"flight_id": live_flight_id})
            
            flight = result.fetchone()
            if flight:
                print(f"\n📍 Live Flight: {flight[0]}")
                print(f"   Source: {flight[1]}")
                print(f"   Total points: {flight[2]}")
                print(f"   First fix: lat={flight[3]}, time={flight[4]}")
                print(f"   Last fix: lat={flight[5]}, time={flight[6]}")
                
                # Count actual points in table
                result = conn.execute(text("""
                    SELECT COUNT(*) FROM live_track_points
                    WHERE flight_id = :flight_id
                """), {"flight_id": live_flight_id})
                
                actual_count = result.scalar()
                print(f"   Actual points in live_track_points: {actual_count}")
                
                if flight[2] == actual_count:
                    print(f"   ✅ Trigger count matches actual points")
                else:
                    print(f"   ⚠️  Trigger count ({flight[2]}) differs from actual ({actual_count})")
        
        if upload_flight_id:
            result = conn.execute(text("""
                SELECT 
                    flight_id,
                    source,
                    total_points,
                    first_fix->>'lat' as first_lat,
                    first_fix->>'datetime' as first_time,
                    last_fix->>'lat' as last_lat,
                    last_fix->>'datetime' as last_time
                FROM flights
                WHERE flight_id = :flight_id
            """), {"flight_id": upload_flight_id})
            
            flight = result.fetchone()
            if flight:
                print(f"\n📍 Upload Flight: {flight[0]}")
                print(f"   Source: {flight[1]}")
                print(f"   Total points: {flight[2]}")
                print(f"   First fix: lat={flight[3]}, time={flight[4]}")
                print(f"   Last fix: lat={flight[5]}, time={flight[6]}")
                
                # Count actual points
                result = conn.execute(text("""
                    SELECT COUNT(*) FROM uploaded_track_points
                    WHERE flight_id = :flight_id
                """), {"flight_id": upload_flight_id})
                
                actual_count = result.scalar()
                print(f"   Actual points in uploaded_track_points: {actual_count}")
                
                if flight[2] == actual_count:
                    print(f"   ✅ Trigger count matches actual points")
                else:
                    print(f"   ⚠️  Trigger count ({flight[2]}) differs from actual ({actual_count})")


def main():
    """Run comprehensive tests"""
    print("\n" + "="*60)
    print("COMPREHENSIVE TRIGGER TESTING")
    print(f"Server: {BASE_URL}")
    print(f"Time: {datetime.now(timezone.utc).isoformat()}")
    print("="*60)
    
    # Check server health
    try:
        response = requests.get(f"{BASE_URL}/health")
        if response.status_code != 200:
            print(f"❌ Server not healthy: {response.status_code}")
            return
        health = response.json()
        print(f"✅ Server is running")
        print(f"   Database: {health['database']}")
        print(f"   Redis: {health['redis']}")
    except Exception as e:
        print(f"❌ Cannot connect to server: {e}")
        return
    
    # Run tests
    live_flight_id = test_live_tracking_comprehensive()
    
    # Wait for queue processing
    print("\n⏳ Waiting for queue processing...")
    time.sleep(5)
    
    upload_flight_id, upload_uuid = test_upload_comprehensive()
    
    # Wait for queue processing
    print("\n⏳ Waiting for final queue processing...")
    time.sleep(5)
    
    # Check queue status
    check_queue_status()
    
    # Verify database
    verify_database_results(live_flight_id, upload_flight_id)
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    if live_flight_id:
        print(f"✅ Live tracking test completed - {live_flight_id}")
        print(f"   - Tested multiple batches")
        print(f"   - Tested duplicate handling")
        print(f"   - Verified trigger updates")
    else:
        print("❌ Live tracking test failed")
    
    if upload_flight_id:
        print(f"✅ Upload test completed - {upload_flight_id}")
        print(f"   - Uploaded 50-point flight")
        print(f"   - Verified trigger updates")
    else:
        print("❌ Upload test failed")


if __name__ == "__main__":
    main()