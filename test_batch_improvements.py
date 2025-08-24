#!/usr/bin/env python3
"""
Test script for the improved /batch endpoint
Tests the following improvements:
1. Accept existing flight_uuid for migration
2. Return detailed response with points added/skipped
3. Batch size validation
4. Chunked processing for large batches
"""

import requests
import uuid
import json
from datetime import datetime, timedelta
import random

# API endpoint
BASE_URL = "http://localhost:8000"
BATCH_ENDPOINT = f"{BASE_URL}/scoring/batch"

def generate_track_points(num_points, base_lat=45.5, base_lon=-122.6):
    """Generate sample track points"""
    points = []
    start_time = datetime.utcnow()
    
    for i in range(num_points):
        points.append({
            "lat": base_lat + random.uniform(-0.01, 0.01),
            "lon": base_lon + random.uniform(-0.01, 0.01),
            "gps_alt": 1000 + random.uniform(-50, 50),
            "date_time": (start_time + timedelta(seconds=i*10)).isoformat() + "Z",
            "speed": random.uniform(10, 30),
            "elevation": 1000 + random.uniform(-50, 50)
        })
    
    return points

def test_new_flight_uuid():
    """Test 1: Create batch without providing flight_uuid (generates new UUID)"""
    print("\n=== Test 1: New Flight UUID Generation ===")
    
    track_points = generate_track_points(10)
    payload = {"tracks": track_points}
    
    response = requests.post(BATCH_ENDPOINT, json=payload)
    print(f"Status Code: {response.status_code}")
    
    if response.status_code == 201:
        data = response.json()
        print(f"Flight UUID: {data['flight_uuid']}")
        print(f"Points Added: {data['points_added']}")
        print(f"Points Skipped: {data.get('points_skipped', 0)}")
        print(f"Queued: {data.get('queued', False)}")
        return data['flight_uuid']
    else:
        print(f"Error: {response.text}")
        return None

def test_existing_flight_uuid(flight_uuid=None):
    """Test 2: Create batch with existing flight_uuid (for migration)"""
    print("\n=== Test 2: Existing Flight UUID (Migration) ===")
    
    if not flight_uuid:
        flight_uuid = str(uuid.uuid4())
    
    track_points = generate_track_points(10, base_lat=45.6, base_lon=-122.7)
    payload = {
        "tracks": track_points,
        "flight_uuid": flight_uuid
    }
    
    response = requests.post(BATCH_ENDPOINT, json=payload)
    print(f"Status Code: {response.status_code}")
    print(f"Using Flight UUID: {flight_uuid}")
    
    if response.status_code == 201:
        data = response.json()
        print(f"Points Added: {data['points_added']}")
        print(f"Points Skipped: {data.get('points_skipped', 0)}")
        print(f"Queued: {data.get('queued', False)}")
    else:
        print(f"Error: {response.text}")

def test_duplicate_handling(flight_uuid):
    """Test 3: Test duplicate point handling"""
    print("\n=== Test 3: Duplicate Point Handling ===")
    
    # Create some points
    track_points = generate_track_points(5)
    
    # Add some duplicates
    track_points.extend(track_points[:3])  # Duplicate first 3 points
    
    payload = {
        "tracks": track_points,
        "flight_uuid": flight_uuid
    }
    
    response = requests.post(BATCH_ENDPOINT, json=payload)
    print(f"Status Code: {response.status_code}")
    print(f"Total Points Sent: {len(track_points)}")
    
    if response.status_code == 201:
        data = response.json()
        print(f"Points Added: {data['points_added']}")
        print(f"Points Skipped: {data.get('points_skipped', 0)}")
        print(f"Queued: {data.get('queued', False)}")
    else:
        print(f"Error: {response.text}")

def test_batch_size_validation():
    """Test 4: Test batch size validation"""
    print("\n=== Test 4: Batch Size Validation ===")
    
    # Try to exceed max batch size (10000)
    track_points = generate_track_points(10001)
    payload = {"tracks": track_points}
    
    response = requests.post(BATCH_ENDPOINT, json=payload)
    print(f"Status Code: {response.status_code}")
    print(f"Attempting to send {len(track_points)} points")
    
    if response.status_code == 400:
        print("Correctly rejected oversized batch")
        print(f"Error: {response.json().get('detail', response.text)}")
    else:
        print(f"Unexpected response: {response.text}")

def test_large_batch_chunking():
    """Test 5: Test large batch processing with chunking"""
    print("\n=== Test 5: Large Batch Chunking ===")
    
    # Create a large batch that should be processed in chunks
    track_points = generate_track_points(2500)
    payload = {"tracks": track_points}
    
    response = requests.post(BATCH_ENDPOINT, json=payload)
    print(f"Status Code: {response.status_code}")
    print(f"Sent {len(track_points)} points")
    
    if response.status_code == 201:
        data = response.json()
        print(f"Flight UUID: {data['flight_uuid']}")
        print(f"Points Added: {data['points_added']}")
        print(f"Points Skipped: {data.get('points_skipped', 0)}")
        print(f"Queued: {data.get('queued', False)}")
        
        # Check if it was processed in chunks (not queued for large batch)
        if not data.get('queued', False):
            print("Large batch was processed directly with chunking")
        else:
            print("Batch was queued for background processing")
    else:
        print(f"Error: {response.text}")

def test_small_batch_queueing():
    """Test 6: Test small batch queueing"""
    print("\n=== Test 6: Small Batch Queueing ===")
    
    # Create a small batch that should be queued
    track_points = generate_track_points(100)
    payload = {"tracks": track_points}
    
    response = requests.post(BATCH_ENDPOINT, json=payload)
    print(f"Status Code: {response.status_code}")
    print(f"Sent {len(track_points)} points")
    
    if response.status_code == 201:
        data = response.json()
        print(f"Flight UUID: {data['flight_uuid']}")
        print(f"Points Added: {data['points_added']}")
        print(f"Points Skipped: {data.get('points_skipped', 0)}")
        print(f"Queued: {data.get('queued', False)}")
        
        if data.get('queued', False):
            print("Small batch was correctly queued for background processing")
    else:
        print(f"Error: {response.text}")

def main():
    """Run all tests"""
    print("=" * 60)
    print("Testing Improved /batch Endpoint")
    print("=" * 60)
    
    # Test 1: Generate new flight UUID
    flight_uuid = test_new_flight_uuid()
    
    # Test 2: Use existing flight UUID
    if flight_uuid:
        test_existing_flight_uuid(flight_uuid)
    
    # Test 3: Duplicate handling
    if flight_uuid:
        test_duplicate_handling(flight_uuid)
    
    # Test 4: Batch size validation
    test_batch_size_validation()
    
    # Test 5: Large batch with chunking
    test_large_batch_chunking()
    
    # Test 6: Small batch queueing
    test_small_batch_queueing()
    
    print("\n" + "=" * 60)
    print("All tests completed!")
    print("=" * 60)

if __name__ == "__main__":
    main()