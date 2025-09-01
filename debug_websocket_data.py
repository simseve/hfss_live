#!/usr/bin/env python3
"""Debug script to check what data the WebSocket endpoint should be sending"""

import os
import sys
from datetime import datetime, timezone, timedelta, time
from zoneinfo import ZoneInfo
from sqlalchemy import func
from database.db_replica import get_replica_db
from database.models import Flight, LiveTrackPoint, Race

def check_race_data(race_id: str):
    """Check what data exists for a specific race"""
    
    with next(get_replica_db()) as db:
        # Get race information
        race = db.query(Race).filter(Race.race_id == race_id).first()
        if not race:
            print(f"❌ Race {race_id} not found in database")
            return
        
        print(f"✅ Race found: {race.name}")
        print(f"   Timezone: {race.timezone or 'UTC'}")
        
        # Get current time and race timezone
        current_time = datetime.now(timezone.utc)
        race_timezone = ZoneInfo(race.timezone) if race.timezone else timezone.utc
        race_local_time = current_time.astimezone(race_timezone)
        
        # Calculate day boundaries
        race_day_start = datetime.combine(
            race_local_time.date(), time.min, tzinfo=race_timezone)
        race_day_end = datetime.combine(
            race_local_time.date(), time.max, tzinfo=race_timezone)
        
        utc_day_start = race_day_start.astimezone(timezone.utc)
        utc_day_end = race_day_end.astimezone(timezone.utc)
        
        print(f"\n📅 Time boundaries:")
        print(f"   Current UTC: {current_time}")
        print(f"   Race local: {race_local_time}")
        print(f"   Day start (UTC): {utc_day_start}")
        print(f"   Day end (UTC): {utc_day_end}")
        
        # Get all flights for this race
        all_flights = db.query(Flight).filter(
            Flight.race_id == race_id
        ).order_by(Flight.created_at.desc()).all()
        
        print(f"\n📊 Total flights for race: {len(all_flights)}")
        
        # Get flights using the same logic as WebSocket endpoint
        lookback_buffer = timedelta(hours=4)
        flights = (
            db.query(Flight)
            .filter(
                Flight.race_id == race_id,
                # Either the flight was created today
                ((Flight.created_at >= utc_day_start - lookback_buffer) &
                 (Flight.created_at <= utc_day_end)) |
                # OR the flight has a last_fix during today
                (func.json_extract_path_text(Flight.last_fix, 'datetime') >=
                    utc_day_start.strftime('%Y-%m-%dT%H:%M:%SZ')) &
                (func.json_extract_path_text(Flight.last_fix, 'datetime') <=
                    utc_day_end.strftime('%Y-%m-%dT%H:%M:%SZ')),
                Flight.source.contains('live')
            )
            .order_by(Flight.created_at.desc())
            .all()
        )
        
        print(f"\n✈️ Live flights today: {len(flights)}")
        
        # Show details for each flight
        for i, flight in enumerate(flights[:10], 1):  # Limit to first 10
            print(f"\n   Flight {i}:")
            print(f"   - ID: {flight.id}")
            print(f"   - Pilot: {flight.pilot_name} (ID: {flight.pilot_id})")
            print(f"   - Created: {flight.created_at}")
            print(f"   - Source: {flight.source}")
            
            if flight.last_fix:
                print(f"   - Last fix: {flight.last_fix.get('datetime', 'N/A')}")
                
            # Count track points
            track_points_count = db.query(LiveTrackPoint).filter(
                LiveTrackPoint.flight_uuid == flight.id
            ).count()
            
            print(f"   - Track points: {track_points_count}")
            
            # Show first and last point
            if track_points_count > 0:
                first_point = db.query(LiveTrackPoint).filter(
                    LiveTrackPoint.flight_uuid == flight.id
                ).order_by(LiveTrackPoint.datetime).first()
                
                last_point = db.query(LiveTrackPoint).filter(
                    LiveTrackPoint.flight_uuid == flight.id
                ).order_by(LiveTrackPoint.datetime.desc()).first()
                
                if first_point:
                    print(f"   - First point: {first_point.datetime}")
                if last_point:
                    print(f"   - Last point: {last_point.datetime}")
        
        # Check for any recent live track points
        recent_points = db.query(LiveTrackPoint).join(
            Flight, LiveTrackPoint.flight_uuid == Flight.id
        ).filter(
            Flight.race_id == race_id,
            LiveTrackPoint.datetime >= current_time - timedelta(hours=24)
        ).count()
        
        print(f"\n📍 Live track points in last 24h: {recent_points}")
        
        # Check for uploaded tracks
        upload_flights = db.query(Flight).filter(
            Flight.race_id == race_id,
            Flight.source.contains('upload')
        ).count()
        
        print(f"\n📤 Uploaded flights: {upload_flights}")

if __name__ == "__main__":
    race_id = "68aadbb85da525060edaaebf"  # The race ID from your WebSocket URL
    
    if len(sys.argv) > 1:
        race_id = sys.argv[1]
    
    print(f"🔍 Checking data for race: {race_id}")
    print("=" * 60)
    
    try:
        check_race_data(race_id)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()