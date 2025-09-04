#!/usr/bin/env python
"""Debug date comparison issue"""

from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database.models import Flight
from config import settings

engine = create_engine(settings.DATABASE_URL)
Session = sessionmaker(bind=engine)
session = Session()

try:
    # Get the persisted flight
    flight = session.query(Flight).filter(
        Flight.flight_id == 'tk905b-68b69cd1dfefb67daa124af8-68aadbb85da525060edaaebf-9590046863-1431-upload'
    ).first()
    
    if flight:
        print(f'Flight found: {flight.flight_id}')
        print(f'Race ID: {flight.race_id}')
        print(f'Created at: {flight.created_at}')
        print(f'Created at type: {type(flight.created_at)}')
        print(f'Created at tzinfo: {flight.created_at.tzinfo}')
        
        # Create the filter dates
        opentime_dt = datetime.fromisoformat('2025-01-01T00:00:00+00:00')
        closetime_dt = datetime.now(timezone.utc) + timedelta(hours=24)
        
        print(f'\nFilter dates:')
        print(f'Opentime: {opentime_dt}')
        print(f'Opentime type: {type(opentime_dt)}')
        print(f'Opentime tzinfo: {opentime_dt.tzinfo}')
        
        print(f'Closetime: {closetime_dt}')
        print(f'Closetime type: {type(closetime_dt)}')
        print(f'Closetime tzinfo: {closetime_dt.tzinfo}')
        
        print(f'\nComparisons:')
        print(f'created_at >= opentime: {flight.created_at >= opentime_dt}')
        print(f'created_at <= closetime: {flight.created_at <= closetime_dt}')
        
        # Test the exact query
        print(f'\nTesting exact query:')
        result = session.query(Flight).filter(
            Flight.race_id == '68b69cd1dfefb67daa124af8',
            Flight.created_at >= opentime_dt,
            Flight.created_at <= closetime_dt
        ).count()
        
        print(f'Flights matching all conditions: {result}')
        
        # Test each condition separately
        print(f'\nTesting conditions separately:')
        
        race_match = session.query(Flight).filter(
            Flight.race_id == '68b69cd1dfefb67daa124af8'
        ).count()
        print(f'  Flights with race_id match: {race_match}')
        
        time_match = session.query(Flight).filter(
            Flight.created_at >= opentime_dt,
            Flight.created_at <= closetime_dt
        ).count()
        print(f'  Flights with time match: {time_match}')
        
        # Check if ANY flights exist for this race
        all_race_flights = session.query(Flight).filter(
            Flight.race_id == '68b69cd1dfefb67daa124af8'
        ).all()
        
        print(f'\nAll flights for race {flight.race_id[:20]}...:')
        for f in all_race_flights[:5]:  # Show first 5
            print(f'  - {f.flight_id[:50]}...')
            print(f'    created: {f.created_at}')
            print(f'    source: {f.source}')
            
    else:
        print('Flight not found!')
        
finally:
    session.close()