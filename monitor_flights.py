#!/usr/bin/env python3
"""Monitor flights to see flight separation in action"""

from database.db_replica import get_replica_db
from database.models import Flight, LiveTrackPoint
from datetime import datetime, timezone, timedelta
import time
import sys

def monitor_flights(device_id=None):
    """Monitor flights and show separation status"""
    
    print("🔍 Monitoring Flights")
    print("=" * 80)
    
    while True:
        try:
            with next(get_replica_db()) as db:
                # Get recent flights
                query = db.query(Flight).filter(
                    Flight.source.in_(['tk905b_live', 'flymaster_live'])
                )
                
                if device_id:
                    query = query.filter(Flight.device_id == device_id)
                
                flights = query.order_by(Flight.created_at.desc()).limit(10).all()
                
                # Clear screen (works on Unix/Mac)
                print("\033[2J\033[H")
                
                print(f"📊 Flight Monitor - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                print("=" * 80)
                
                if not flights:
                    print("No flights found")
                else:
                    for flight in flights:
                        print(f"\n✈️ Flight: {flight.flight_id}")
                        print(f"   Device: {flight.device_id} ({flight.source})")
                        print(f"   Pilot: {flight.pilot_name}")
                        print(f"   Created: {flight.created_at}")
                        
                        # Check for suffix (indicates separation reason)
                        flight_id_parts = flight.flight_id.split('-')
                        if len(flight_id_parts) > 4:
                            suffix = flight_id_parts[-1]
                            if suffix.startswith('L'):
                                print(f"   📍 Separation: Landing detected")
                            elif len(suffix) == 8 and suffix.isdigit():
                                print(f"   📅 Separation: New day")
                            elif len(suffix) == 4 and suffix.isdigit():
                                print(f"   ⏰ Separation: Inactivity gap")
                            else:
                                print(f"   🔄 Separation: Unknown ({suffix})")
                        
                        if flight.first_fix:
                            print(f"   First fix: {flight.first_fix.get('datetime', 'N/A')}")
                        if flight.last_fix:
                            print(f"   Last fix: {flight.last_fix.get('datetime', 'N/A')}")
                            
                            # Calculate time since last fix
                            try:
                                last_fix_time = datetime.fromisoformat(
                                    flight.last_fix['datetime'].replace('Z', '+00:00')
                                )
                                time_since = datetime.now(timezone.utc) - last_fix_time
                                hours = time_since.total_seconds() / 3600
                                
                                if hours < 1:
                                    print(f"   ⏱️ Time since last: {int(time_since.total_seconds() / 60)} minutes")
                                else:
                                    print(f"   ⏱️ Time since last: {hours:.1f} hours")
                                
                                # Predict next separation
                                if hours >= 2.5:
                                    print(f"   ⚠️ Next point will create NEW FLIGHT (3+ hour gap)")
                                elif hours >= 2:
                                    print(f"   ⚡ Approaching 3-hour threshold")
                                    
                            except:
                                pass
                        
                        # Count points
                        point_count = db.query(LiveTrackPoint).filter(
                            LiveTrackPoint.flight_uuid == flight.id
                        ).count()
                        print(f"   📍 Points: {point_count}")
                
                print("\n" + "=" * 80)
                print("Press Ctrl+C to exit | Refreshing every 5 seconds...")
                
            time.sleep(5)
            
        except KeyboardInterrupt:
            print("\n👋 Exiting monitor")
            break
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    device_id = sys.argv[1] if len(sys.argv) > 1 else None
    
    if device_id:
        print(f"Monitoring device: {device_id}")
    else:
        print("Monitoring all TK905B and Flymaster devices")
    
    monitor_flights(device_id)