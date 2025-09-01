#!/usr/bin/env python3
"""Test what the WebSocket endpoint would return"""

from datetime import datetime, timezone, timedelta, time
from zoneinfo import ZoneInfo
from sqlalchemy import func
from database.db_replica import get_replica_db
from database.models import Flight, LiveTrackPoint, Race
import json

race_id = "68aadbb85da525060edaaebf"

with next(get_replica_db()) as db:
    # Get race and timezone
    race = db.query(Race).filter(Race.race_id == race_id).first()
    
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
    
    print(f"Current UTC: {current_time}")
    print(f"Day start UTC: {utc_day_start}")
    print(f"Day end UTC: {utc_day_end}")
    print()
    
    # Use exact same query as WebSocket
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
    
    print(f"Flights matching WebSocket criteria: {len(flights)}")
    
    for flight in flights:
        print(f"\nFlight {flight.id}:")
        print(f"  Pilot: {flight.pilot_name}")
        print(f"  Source: {flight.source}")
        print(f"  Created: {flight.created_at}")
        print(f"  Last fix: {flight.last_fix}")
        
        # Count track points
        points = db.query(LiveTrackPoint).filter(
            LiveTrackPoint.flight_uuid == flight.id
        ).count()
        print(f"  Track points: {points}")