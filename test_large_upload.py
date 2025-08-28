#!/usr/bin/env python3
"""
Test large upload with 200 points
"""

import requests
import time
from datetime import datetime, timezone, timedelta
import uuid
import math

BASE_URL = "http://127.0.0.1:8000"
TEST_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJwaWxvdF9pZCI6IjY4YWFkYmRjNWRhNTI1MDYwZWRhYWVjMiIsInJhY2VfaWQiOiI2OGFhZGJiODVkYTUyNTA2MGVkYWFlYmYiLCJwaWxvdF9uYW1lIjoiU2ltb25lIFNldmVyaW5pIiwiZXhwIjoxNzk2MTY5NTk5LCJyYWNlIjp7Im5hbWUiOiJIRlNTIEFwcCBUZXN0aW5nIiwiZGF0ZSI6IjIwMjUtMDEtMDEiLCJ0aW1lem9uZSI6IkV1cm9wZS9Sb21lIiwibG9jYXRpb24iOiJMYXZlbm8iLCJlbmRfZGF0ZSI6IjIwMjYtMTItMDEifSwiZW5kcG9pbnRzIjp7ImxpdmUiOiIvbGl2ZSIsInVwbG9hZCI6Ii91cGxvYWQifX0.MU5OrqbbTRX36Qves9wDx62btbBWkumVX_WYfmXqsYo"


def generate_realistic_flight_path(num_points=200):
    """Generate a realistic paragliding flight path with thermals"""
    points = []
    base_time = datetime.now(timezone.utc)
    
    # Starting position (takeoff)
    base_lat = 46.0
    base_lon = 7.0
    base_elevation = 1500  # Starting altitude
    
    # Flight parameters
    thermal_count = 0
    in_thermal = False
    thermal_duration = 0
    
    for i in range(num_points):
        # Time progresses 15 seconds per point (50 minutes total for 200 points)
        timestamp = (base_time + timedelta(seconds=i*15)).isoformat().replace('+00:00', 'Z')
        
        # Simulate thermal cycles every ~30 points
        if i % 30 == 0:
            in_thermal = not in_thermal
            thermal_duration = 0
            if in_thermal:
                thermal_count += 1
        
        thermal_duration += 1
        
        # Calculate position
        # Fly in a general direction with some circling in thermals
        if in_thermal:
            # Circle in thermal
            angle = (thermal_duration * 30) * math.pi / 180  # 30 degrees per point
            radius = 0.001  # Small radius for circling
            lat = base_lat + (i * 0.0001) + radius * math.sin(angle)
            lon = base_lon + (i * 0.0001) + radius * math.cos(angle)
            # Gain altitude in thermal
            elevation = base_elevation + (i * 2) + (thermal_duration * 5)
            speed = 25.0  # Slower speed in thermal
        else:
            # Glide between thermals
            lat = base_lat + (i * 0.0002)  # Move forward
            lon = base_lon + (i * 0.0002)
            # Lose altitude while gliding
            elevation = base_elevation + (i * 2) - (thermal_duration * 3)
            speed = 35.0  # Faster glide speed
        
        # Calculate heading
        heading = (90 + (i * 2)) % 360
        
        point = {
            "datetime": timestamp,
            "lat": round(lat, 6),
            "lon": round(lon, 6),
            "elevation": round(max(elevation, 200)),  # Don't go below ground
            "speed": speed + (i % 5) - 2,  # Some speed variation
            "heading": heading
        }
        points.append(point)
    
    return points


def wait_for_processing(timeout=30):
    """Wait for queue to be empty and processing to complete"""
    print(f"⏳ Waiting for processing (up to {timeout} seconds)...")
    start = time.time()
    last_processed = 0
    
    while time.time() - start < timeout:
        response = requests.get(f"{BASE_URL}/queue/status")
        if response.status_code == 200:
            status = response.json()
            
            # Check if upload queue is empty
            upload_pending = status['queue_stats']['upload']['total_pending']
            
            # Get processing stats
            processed = status['processor_stats']['processed']
            
            # If queue is empty and processing has stopped increasing
            if upload_pending == 0:
                if processed == last_processed:
                    # No new processing in last check, likely done
                    print(f"   ✅ Processing complete: {processed} total processed")
                    return True, processed
                last_processed = processed
        
        time.sleep(1)
    
    return False, last_processed


def verify_upload(flight_id, expected_points=200):
    """Verify the upload was processed correctly"""
    from config import settings
    from sqlalchemy import create_engine, text
    
    engine = create_engine(settings.DATABASE_URL)
    
    with engine.connect() as conn:
        # Check flight record
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
        """), {"flight_id": flight_id})
        
        flight = result.fetchone()
        if not flight:
            return False, "Flight not found"
        
        # Check actual points in table
        result = conn.execute(text("""
            SELECT COUNT(*) as count,
                   MIN(lat) as min_lat,
                   MAX(lat) as max_lat,
                   MIN(datetime) as first_time,
                   MAX(datetime) as last_time
            FROM uploaded_track_points
            WHERE flight_id = :flight_id
        """), {"flight_id": flight_id})
        
        actual = result.fetchone()
        
        # Verify results
        trigger_points = flight[2]
        actual_points = actual[0]
        
        print(f"\n📊 Verification Results:")
        print(f"   Flight: {flight[0]}")
        print(f"   Source: {flight[1]}")
        print(f"   Trigger total_points: {trigger_points}")
        print(f"   Actual points in DB: {actual_points}")
        print(f"   First fix: lat={flight[3]}, time={flight[4]}")
        print(f"   Last fix: lat={flight[5]}, time={flight[6]}")
        
        if trigger_points == expected_points and actual_points == expected_points:
            print(f"   ✅ All {expected_points} points successfully processed!")
            print(f"   ✅ Triggers correctly updated flight record!")
            return True, "Success"
        else:
            if trigger_points != actual_points:
                print(f"   ⚠️  Trigger count ({trigger_points}) doesn't match actual ({actual_points})")
            if actual_points != expected_points:
                print(f"   ❌ Expected {expected_points} points but got {actual_points}")
            return False, f"Point count mismatch"


def main():
    print("\n" + "="*60)
    print("LARGE UPLOAD TEST - 200 POINTS")
    print(f"Server: {BASE_URL}")
    print(f"Time: {datetime.now(timezone.utc).isoformat()}")
    print("="*60)
    
    # Generate flight ID
    flight_id = f"large-upload-{uuid.uuid4().hex[:8]}"
    
    # Generate 200 points
    print(f"\n🎯 Generating realistic flight path with 200 points...")
    track_points = generate_realistic_flight_path(200)
    
    print(f"   Generated {len(track_points)} points")
    print(f"   Time span: {track_points[0]['datetime']} to {track_points[-1]['datetime']}")
    print(f"   Lat range: {min(p['lat'] for p in track_points):.4f} to {max(p['lat'] for p in track_points):.4f}")
    print(f"   Elevation range: {min(p['elevation'] for p in track_points)} to {max(p['elevation'] for p in track_points)} meters")
    
    # Prepare payload
    payload = {
        "flight_id": flight_id,
        "device_id": "test-large-upload",
        "track_points": track_points
    }
    
    # Upload the track
    print(f"\n📤 Uploading {len(track_points)} points...")
    print(f"   Flight ID: {flight_id}")
    
    start_time = time.time()
    response = requests.post(
        f"{BASE_URL}/tracking/upload",
        params={"token": TEST_TOKEN},
        json=payload
    )
    upload_time = time.time() - start_time
    
    if response.status_code == 202:
        result = response.json()
        print(f"   ✅ Upload accepted in {upload_time:.2f} seconds")
        print(f"   Flight UUID: {result.get('id')}")
    else:
        print(f"   ❌ Upload failed: {response.status_code}")
        print(f"   Response: {response.text}")
        return
    
    # Wait for processing
    success, processed_count = wait_for_processing(timeout=30)
    
    if not success:
        print(f"   ⚠️  Processing timeout - may still be processing")
        print(f"   Processed so far: {processed_count}")
    
    # Verify the upload
    print(f"\n🔍 Verifying upload...")
    verified, message = verify_upload(flight_id, expected_points=200)
    
    # Final summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    if verified:
        print(f"✅ Successfully uploaded and processed 200 points!")
        print(f"✅ Database triggers working correctly!")
        print(f"✅ Flight ID: {flight_id}")
    else:
        print(f"❌ Test failed: {message}")
        print(f"   Flight ID: {flight_id}")
        
        # Additional debugging
        print(f"\n🔧 Debugging info:")
        response = requests.get(f"{BASE_URL}/queue/status")
        if response.status_code == 200:
            status = response.json()
            print(f"   Queue pending: {status['queue_stats']['upload']['total_pending']}")
            print(f"   Total processed: {status['processor_stats']['processed']}")
            print(f"   Total failed: {status['processor_stats']['failed']}")


if __name__ == "__main__":
    main()