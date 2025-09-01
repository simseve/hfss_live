#!/usr/bin/env python3
"""
Debug what's in the queue before processing
"""
import asyncio
from tcp_server.jt808_processor import jt808_processor
from datetime import datetime, timezone
import json

async def test_queue():
    # Simulate the exact data that would be queued
    parsed_data = {
        'protocol': 'JT808',
        'msg_id': 0x0200,  # Location report
        'device_id': '9590046863',
        'latitude': 46.5197,
        'longitude': 6.6323,
        'altitude': 375,
        'gps_time': '2025-09-01T14:15:00',  # No timezone
        'speed': 15.0,
        'heading': 45
    }
    
    registration = {
        'device_id': '9590046863',
        'race_id': '68aadbb85da525060edaaebf',
        'pilot_id': '68aadbdc5da525060edaaec2',
        'pilot_name': 'Simone Severini',
        'race_uuid': '406e3e24-14b7-4c95-9aab-0e17f8bee947',
        'device_type': 'tk905b'
    }
    
    # Call the queue method to see what it produces
    result = await jt808_processor._queue_data(parsed_data, registration)
    print(f"Queue result: {result}")
    
    # Check what would be in the track_point
    flight_id = '2732099b-20dc-4102-aa5e-9e9b281de0a0'
    
    # Recreate the exact logic from jt808_processor
    gps_time_str = parsed_data.get('gps_time')
    if gps_time_str:
        try:
            dt = datetime.fromisoformat(gps_time_str).replace(tzinfo=timezone.utc)
            timestamp = dt.isoformat()
        except:
            timestamp = datetime.now(timezone.utc).isoformat()
    else:
        timestamp = datetime.now(timezone.utc).isoformat()
    
    track_point = {
        'datetime': timestamp,
        'flight_uuid': flight_id,
        'flight_id': flight_id,
        'lat': parsed_data['latitude'],
        'lon': parsed_data['longitude'],
        'elevation': parsed_data.get('altitude', 0),
        'device_id': registration['device_id'],
        'barometric_altitude': None
    }
    
    print("\nTrack point that would be queued:")
    print(json.dumps(track_point, indent=2))
    
    # Show what's wrapped for queue
    queue_item = {
        'points': [track_point],
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'count': 1,
        'queue_type': 'live_points'
    }
    
    print("\nFull queue item:")
    print(json.dumps(queue_item, indent=2))

if __name__ == '__main__':
    asyncio.run(test_queue())