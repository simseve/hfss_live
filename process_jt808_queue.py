#!/usr/bin/env python3
"""
Process JT808 GPS points from Redis queue to database
"""
import redis
import json
from datetime import datetime, timezone
from database.db_conf import get_db
from database.models import LiveTrackPoint

def process_queue():
    r = redis.from_url('redis://127.0.0.1:6379/0')
    db = next(get_db())
    
    queue_name = 'queue:live_points'
    processed_count = 0
    
    while True:
        # Get item with lowest score (oldest)
        items = r.zpopmin(queue_name, 1)
        if not items:
            break
            
        item_json, score = items[0]
        data = json.loads(item_json)
        
        points = data.get('points', [])
        for point_data in points:
            try:
                # Use current time with microseconds to avoid duplicates
                point_time = datetime.now(timezone.utc)
                
                # Check if point already exists (same location and flight)
                existing = db.query(LiveTrackPoint).filter(
                    LiveTrackPoint.flight_id == point_data['flight_id'],
                    LiveTrackPoint.lat == point_data['latitude'],
                    LiveTrackPoint.lon == point_data['longitude']
                ).first()
                
                if existing:
                    print(f"Skipping duplicate point: {point_data['latitude']:.6f}, {point_data['longitude']:.6f}")
                    continue
                
                # Create LiveTrackPoint
                point = LiveTrackPoint(
                    datetime=point_time,
                    flight_uuid=point_data['flight_id'],  # UUID string
                    flight_id=point_data['flight_id'],
                    lat=point_data['latitude'],
                    lon=point_data['longitude'],
                    elevation=point_data.get('altitude', 0),
                    device_id=point_data.get('device_id')
                )
                db.add(point)
                db.commit()  # Commit each point individually to avoid batch constraint issues
                processed_count += 1
                print(f"Added point: {point_data['latitude']:.6f}, {point_data['longitude']:.6f} at {point_time}")
            except Exception as e:
                print(f"Error processing point: {e}")
                db.rollback()
                continue
    
    if processed_count > 0:
        print(f"\n✅ Processed {processed_count} points into database")
    else:
        print("No points to process")
    
    db.close()
    
    # Check total points
    db = next(get_db())
    total = db.query(LiveTrackPoint).filter(
        LiveTrackPoint.device_id == '9590046863'
    ).count()
    print(f"Total points for device 9590046863: {total}")

if __name__ == '__main__':
    process_queue()