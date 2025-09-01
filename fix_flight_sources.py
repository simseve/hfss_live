#!/usr/bin/env python3
"""Fix existing flight sources to include _live suffix"""

from database.db_conf import get_db
from database.models import Flight

def fix_flight_sources():
    db = next(get_db())
    try:
        # Find all flights with source 'tk905b' and update to 'tk905b_live'
        flights = db.query(Flight).filter(
            Flight.source == 'tk905b'
        ).all()
        
        print(f"Found {len(flights)} flights with source 'tk905b'")
        
        for flight in flights:
            print(f"Updating flight {flight.id} - {flight.pilot_name}")
            flight.source = 'tk905b_live'
        
        db.commit()
        print(f"✅ Updated {len(flights)} flights to source 'tk905b_live'")
        
        # Verify the update
        tk905b_live_count = db.query(Flight).filter(
            Flight.source == 'tk905b_live'
        ).count()
        
        print(f"Total flights with 'tk905b_live' source: {tk905b_live_count}")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    fix_flight_sources()