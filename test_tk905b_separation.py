#!/usr/bin/env python3
"""Test TK905B flight separation by simulating time gaps"""

from database.db_conf import get_db
from database.models import Flight, LiveTrackPoint
from datetime import datetime, timezone, timedelta
import time

def simulate_tk905b_gap():
    """Simulate different time gaps to test flight separation"""
    
    device_id = "9590046863"
    
    print("🧪 Testing TK905B Flight Separation")
    print("=" * 60)
    
    db = next(get_db())
    try:
        # Get current flight
        current_flight = db.query(Flight).filter(
            Flight.device_id == device_id,
            Flight.source == "tk905b_live"
        ).order_by(Flight.created_at.desc()).first()
        
        if current_flight:
            print(f"\n📊 Current flight: {current_flight.flight_id}")
            print(f"   Last fix: {current_flight.last_fix.get('datetime') if current_flight.last_fix else 'None'}")
            
            if current_flight.last_fix:
                last_fix_time = datetime.fromisoformat(
                    current_flight.last_fix['datetime'].replace('Z', '+00:00')
                )
                time_since = datetime.now(timezone.utc) - last_fix_time
                hours = time_since.total_seconds() / 3600
                
                print(f"   Time since last: {hours:.1f} hours")
                
                if hours < 3:
                    print(f"\n✅ Next point should CONTINUE same flight (< 3 hours)")
                else:
                    print(f"\n🆕 Next point should CREATE NEW flight (>= 3 hours)")
                
                # Show what would happen at different times
                print(f"\n📅 Flight Separation Predictions:")
                
                # In 30 minutes
                future_30min = datetime.now(timezone.utc) + timedelta(minutes=30)
                gap_30min = (future_30min - last_fix_time).total_seconds() / 3600
                if gap_30min < 3:
                    print(f"   In 30 min ({gap_30min:.1f}h gap): Continue same flight")
                else:
                    print(f"   In 30 min ({gap_30min:.1f}h gap): CREATE NEW FLIGHT")
                
                # In 1 hour
                future_1hr = datetime.now(timezone.utc) + timedelta(hours=1)
                gap_1hr = (future_1hr - last_fix_time).total_seconds() / 3600
                if gap_1hr < 3:
                    print(f"   In 1 hour ({gap_1hr:.1f}h gap): Continue same flight")
                else:
                    print(f"   In 1 hour ({gap_1hr:.1f}h gap): CREATE NEW FLIGHT")
                
                # Tomorrow (new day)
                tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
                print(f"   Tomorrow: CREATE NEW FLIGHT (new day)")
                
        else:
            print(f"❌ No flight found for device {device_id}")
        
        # Count total flights for this device
        total_flights = db.query(Flight).filter(
            Flight.device_id == device_id,
            Flight.source == "tk905b_live"
        ).count()
        
        print(f"\n📈 Total flights for device: {total_flights}")
        
        # Show all flights with their suffixes
        all_flights = db.query(Flight).filter(
            Flight.device_id == device_id,
            Flight.source == "tk905b_live"
        ).order_by(Flight.created_at.desc()).all()
        
        if len(all_flights) > 1:
            print(f"\n📋 Flight History:")
            for i, flight in enumerate(all_flights[:5], 1):
                flight_id_parts = flight.flight_id.split('-')
                suffix = flight_id_parts[-1] if len(flight_id_parts) > 4 else "original"
                
                print(f"   {i}. {flight.flight_id}")
                print(f"      Created: {flight.created_at}")
                print(f"      Suffix: {suffix}")
                
                if suffix != "original":
                    if suffix.startswith('L'):
                        print(f"      Reason: Landing detected")
                    elif len(suffix) == 8 and suffix.isdigit():
                        print(f"      Reason: New day")
                    elif len(suffix) == 4 and suffix.isdigit():
                        print(f"      Reason: Inactivity gap")
        
    except Exception as e:
        print(f"Error: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    simulate_tk905b_gap()