#!/usr/bin/env python3
"""Manually update first_fix and last_fix for flights that are missing them"""

from database.db_conf import get_db
from database.models import Flight, LiveTrackPoint
from sqlalchemy import func

def update_flight_fixes():
    db = next(get_db())
    try:
        # Find flights with missing first_fix or last_fix
        flights = db.query(Flight).filter(
            (Flight.first_fix == None) | (Flight.last_fix == None)
        ).all()
        
        print(f"Found {len(flights)} flights with missing fixes")
        
        for flight in flights:
            print(f"\nProcessing flight {flight.id} - {flight.pilot_name}")
            
            # Get first and last points for this flight
            first_point = db.query(LiveTrackPoint).filter(
                LiveTrackPoint.flight_uuid == flight.id
            ).order_by(LiveTrackPoint.datetime).first()
            
            last_point = db.query(LiveTrackPoint).filter(
                LiveTrackPoint.flight_uuid == flight.id
            ).order_by(LiveTrackPoint.datetime.desc()).first()
            
            # Count total points
            total_points = db.query(LiveTrackPoint).filter(
                LiveTrackPoint.flight_uuid == flight.id
            ).count()
            
            if first_point:
                flight.first_fix = {
                    'lat': float(first_point.lat),
                    'lon': float(first_point.lon),
                    'elevation': float(first_point.elevation) if first_point.elevation else 0,
                    'datetime': first_point.datetime.strftime('%Y-%m-%dT%H:%M:%SZ')
                }
                print(f"  Set first_fix: {flight.first_fix['datetime']}")
            
            if last_point:
                flight.last_fix = {
                    'lat': float(last_point.lat),
                    'lon': float(last_point.lon),
                    'elevation': float(last_point.elevation) if last_point.elevation else 0,
                    'datetime': last_point.datetime.strftime('%Y-%m-%dT%H:%M:%SZ')
                }
                print(f"  Set last_fix: {flight.last_fix['datetime']}")
            
            if total_points > 0:
                flight.total_points = total_points
                print(f"  Set total_points: {total_points}")
        
        db.commit()
        print(f"\n✅ Updated {len(flights)} flights")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    update_flight_fixes()