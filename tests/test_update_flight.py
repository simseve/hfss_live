#!/usr/bin/env python3
"""
Test script for the flight update endpoint
"""
import requests
import json
import uuid
from datetime import datetime, timezone, timedelta
import random
import time

# Configuration
BASE_URL = "http://localhost:8000/scoring"
BATCH_URL = f"{BASE_URL}/batch"


def generate_track_points(count=10):
    base_lat = 45.5231
    base_lon = -122.6765
    base_alt = 1200.5

    tracks = []
    current_time = datetime.now(timezone.utc)

    for i in range(count):
        # Create slightly different coordinates
        lat = base_lat + (random.random() - 0.5) * 0.001
        lon = base_lon + (random.random() - 0.5) * 0.001
        alt = base_alt + random.randint(-10, 10)

        # Add seconds to the timestamp
        timestamp = current_time.isoformat()
        current_time = current_time + timedelta(seconds=1)

        track = {
            "lat": lat,
            "lon": lon,
            "gps_alt": alt,
            "speed": random.uniform(5, 15),
            "time": timestamp,
            # Add a placeholder flight_uuid that will be overridden
            "flight_uuid": str(uuid.uuid4())
        }
        tracks.append(track)

    return tracks


def test_update_flight():
    """Test the update flight endpoint by first creating a flight and then updating it"""
    print("Testing flight update workflow...")

    # STEP 1: Create initial flight with batch upload
    initial_batch_size = 10
    print(f"1. Creating initial flight with {initial_batch_size} points...")

    initial_tracks = generate_track_points(initial_batch_size)
    initial_payload = {"tracks": initial_tracks}

    create_response = requests.post(BATCH_URL, json=initial_payload)

    print(f"Status code: {create_response.status_code}")
    print(f"Response: {create_response.text}")

    if create_response.status_code != 201:
        print("Failed to create initial flight. Aborting test.")
        return

    # Extract the flight_uuid from the response
    response_data = create_response.json()
    flight_uuid = response_data.get("flight_uuid")

    print(f"Created flight with UUID: {flight_uuid}")
    print("-" * 40)

    # STEP 2: Update the flight with new track points
    update_batch_size = 15
    print(f"2. Updating flight with {update_batch_size} new points...")

    # Generate different track points for the update
    update_tracks = generate_track_points(update_batch_size)
    update_payload = {"tracks": update_tracks}

    # Use the PUT endpoint with the flight_uuid
    update_url = f"{BASE_URL}/flight/{flight_uuid}"

    start_time = time.time()
    update_response = requests.put(update_url, json=update_payload)
    elapsed_time = time.time() - start_time

    print(f"Status code: {update_response.status_code}")
    print(f"Response: {update_response.text}")
    print(f"Elapsed time: {elapsed_time:.2f} seconds")
    print(f"Points per second: {update_batch_size / elapsed_time:.2f}")

    # STEP 3: Verify the update by getting the flight points
    print("-" * 40)
    print("3. Verifying update by fetching flight points...")

    verify_url = f"{BASE_URL}/flight/{flight_uuid}/points"
    verify_response = requests.get(verify_url)

    print(f"Status code: {verify_response.status_code}")

    if verify_response.status_code == 200:
        response_data = verify_response.json()
        points_count = response_data.get("points_count", 0)
        print(
            f"Flight now has {points_count} points (should be {update_batch_size})")

        if points_count == update_batch_size:
            print("✅ Test passed: Flight was successfully updated!")
        else:
            print("❌ Test failed: Number of points doesn't match expected count")
    else:
        print(
            f"❌ Test failed: Could not verify flight points: {verify_response.text}")


if __name__ == "__main__":
    test_update_flight()
