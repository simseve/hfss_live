#!/usr/bin/env python3
"""Trigger flight separation by updating the last_fix to be older"""

from database.db_conf import get_db
from database.models import Flight
from datetime import datetime, timezone, timedelta
import time

def trigger_separation(device_id="9590046863", hours_ago=4):
    """Make the last fix older to trigger separation on next point"""
    
    print(f"🎯 Triggering Flight Separation for device {device_id}")
    print("=" * 60)
    
    db = next(get_db())
    try:
        # Get current flight
        flight = db.query(Flight).filter(
            Flight.device_id == device_id,
            Flight.source == "tk905b_live"
        ).order_by(Flight.created_at.desc()).first()
        
        if not flight:
            print(f"❌ No flight found for device {device_id}")
            return
        
        print(f"\n📊 Current flight: {flight.flight_id}")
        print(f"   Current last_fix: {flight.last_fix.get('datetime') if flight.last_fix else 'None'}")
        
        # Update last_fix to be hours_ago in the past
        old_time = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
        
        if flight.last_fix:
            flight.last_fix['datetime'] = old_time.strftime('%Y-%m-%dT%H:%M:%SZ')
        else:
            flight.last_fix = {
                'lat': 45.973288,
                'lon': 8.875027,
                'elevation': 350,
                'datetime': old_time.strftime('%Y-%m-%dT%H:%M:%SZ')
            }
        
        db.commit()
        
        print(f"\n✅ Updated last_fix to: {flight.last_fix['datetime']}")
        print(f"   This is {hours_ago} hours ago")
        
        # Calculate what will happen
        time_gap = datetime.now(timezone.utc) - old_time
        hours = time_gap.total_seconds() / 3600
        
        if hours >= 3:
            print(f"\n🆕 Next point will CREATE NEW FLIGHT (gap: {hours:.1f} hours)")
            print(f"   Expected suffix: {datetime.now(timezone.utc).strftime('%H%M')}")
        else:
            print(f"\n✅ Next point will CONTINUE same flight (gap: {hours:.1f} hours)")
        
        print("\n📝 Next steps:")
        print("1. Wait for the TK905B device to send a new location")
        print("2. Or manually send a test point to trigger the separation")
        print("3. Monitor will show the new flight when created")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        db.rollback()
    finally:
        db.close()

def reset_flight(device_id="9590046863"):
    """Reset the flight to current time"""
    
    db = next(get_db())
    try:
        flight = db.query(Flight).filter(
            Flight.device_id == device_id,
            Flight.source == "tk905b_live"
        ).order_by(Flight.created_at.desc()).first()
        
        if flight and flight.last_fix:
            flight.last_fix['datetime'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
            db.commit()
            print(f"✅ Reset last_fix to current time: {flight.last_fix['datetime']}")
        
    except Exception as e:
        print(f"Error: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "reset":
        print("🔄 Resetting flight to current time")
        reset_flight()
    else:
        hours = 4  # Default to 4 hours ago
        if len(sys.argv) > 1:
            try:
                hours = float(sys.argv[1])
            except:
                pass
        
        trigger_separation(hours_ago=hours)