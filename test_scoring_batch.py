#!/usr/bin/env python3
"""
Test script for the batch scoring track endpoint
"""
import requests
import json
import uuid
from datetime import datetime, timezone
import random
import time

# Configuration
API_URL = "http://localhost:8000/scoring/batch"


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
        from datetime import timedelta
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


def test_batch_upload(batch_size=100):
    """Test batch upload with the specified batch size"""
    print(f"Testing batch upload with {batch_size} points...")

    # Generate track points
    tracks = generate_track_points(batch_size)

    # Prepare the payload
    payload = {
        "tracks": tracks
    }

    # Measure time
    start_time = time.time()

    # Send request
    response = requests.post(API_URL, json=payload)

    # Calculate elapsed time
    elapsed_time = time.time() - start_time

    # Print results
    print(f"Status code: {response.status_code}")
    print(f"Response: {response.text}")
    print(f"Elapsed time: {elapsed_time:.2f} seconds")
    print(f"Points per second: {batch_size / elapsed_time:.2f}")

    return response


if __name__ == "__main__":
    # Test with different batch sizes
    test_batch_upload(10)
    # print("-" * 40)
    # test_batch_upload(100)
    # print("-" * 40)
    # test_batch_upload(1000)
