#!/usr/bin/env python3
"""Force flight separation by updating last_fix and sending a new point"""

from database.db_conf import get_db
from database.models import Flight, LiveTrackPoint
from datetime import datetime, timezone, timedelta
from redis_queue_system.redis_queue import redis_queue, QUEUE_NAMES
import asyncio

async def force_separation():
    """Force a flight separation by updating last_fix and queueing a new point"""
    
    device_id = "9590046863"
    
    print(f"🚀 Forcing Flight Separation for device {device_id}")
    print("=" * 60)
    
    db = next(get_db())
    try:
        # Step 1: Update the current flight's last_fix to be 4 hours ago
        flight = db.query(Flight).filter(
            Flight.device_id == device_id,
            Flight.source == "tk905b_live"
        ).order_by(Flight.created_at.desc()).first()
        
        if not flight:
            print(f"❌ No flight found")
            return
        
        print(f"\n📊 Current flight: {flight.flight_id}")
        old_last_fix = flight.last_fix.get('datetime') if flight.last_fix else None
        print(f"   Current last_fix: {old_last_fix}")
        
        # Set last_fix to 4 hours ago
        four_hours_ago = datetime.now(timezone.utc) - timedelta(hours=4)
        flight.last_fix = {
            'lat': 45.973288,
            'lon': 8.875027,
            'elevation': 350,
            'datetime': four_hours_ago.strftime('%Y-%m-%dT%H:%M:%SZ')
        }
        
        db.commit()
        print(f"\n✅ Updated last_fix to: {flight.last_fix['datetime']}")
        print(f"   This is 4 hours ago - next point will trigger new flight")
        
    except Exception as e:
        print(f"❌ Error updating flight: {e}")
        db.rollback()
        return
    finally:
        db.close()
    
    # Step 2: Queue a new point with current timestamp
    print(f"\n📤 Queueing new point with current timestamp...")
    
    current_time = datetime.now(timezone.utc)
    new_point = {
        'datetime': current_time.isoformat(),
        'lat': 45.973300,  # Slightly different position
        'lon': 8.875100,
        'elevation': 355,
        'device_id': device_id,
        'device_type': 'tk905b',
        'barometric_altitude': None,
        # Registration info for flight creation
        'race_id': '68aadbb85da525060edaaebf',
        'race_uuid': '6798055812e629a8838a7059',
        'pilot_id': '68aadbdc5da525060edaaec2',
        'pilot_name': 'Simone Severini',
        'base_flight_id': f"tk905b-68aadbdc5da525060edaaec2-68aadbb85da525060edaaebf-{device_id}"
    }
    
    # Queue the point
    queued = await redis_queue.queue_points(
        QUEUE_NAMES['live'],
        [new_point]
    )
    
    if queued:
        print(f"✅ Point queued successfully!")
        print(f"   Timestamp: {current_time.strftime('%Y-%m-%d %H:%M:%S')} UTC")
        print(f"   Gap from last fix: 4.0 hours")
        print(f"\n🎯 This should trigger creation of a new flight!")
        print(f"   Expected new flight ID suffix: {current_time.strftime('%H%M')}")
        print(f"\n📊 Check the monitor to see the new flight appear!")
    else:
        print(f"❌ Failed to queue point")

if __name__ == "__main__":
    asyncio.run(force_separation())