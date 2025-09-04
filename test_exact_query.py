#!/usr/bin/env python
"""Test the exact query from the endpoint"""

from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database.models import Flight
from config import settings

engine = create_engine(settings.DATABASE_URL)
Session = sessionmaker(bind=engine)
session = Session()

try:
    # Exact parameters from the endpoint
    race_id = '68aadbb85da525060edaaebf'
    opentime_dt = datetime.fromisoformat('2025-01-01T00:00:00+00:00')
    closetime_dt = datetime.now(timezone.utc) + timedelta(hours=24)
    
    print(f'Query parameters:')
    print(f'  race_id: {race_id}')
    print(f'  opentime: {opentime_dt}')
    print(f'  closetime: {closetime_dt}')
    
    # Exact query from endpoint
    flights = session.query(Flight).filter(
        Flight.race_id == race_id,
        Flight.created_at >= opentime_dt,
        Flight.created_at <= closetime_dt
    ).all()
    
    print(f'\nTotal flights found: {len(flights)}')
    
    # Check our specific flight
    our_flight = None
    for flight in flights:
        if '9590046863-1431' in flight.flight_id:
            our_flight = flight
            break
    
    if our_flight:
        print(f'\n✅ Our persisted flight IS in the query results!')
        print(f'  flight_id: {our_flight.flight_id}')
        print(f'  source: {our_flight.source}')
        print(f'  first_fix: {our_flight.first_fix is not None}')
        print(f'  last_fix: {our_flight.last_fix is not None}')
        print(f'  Would be skipped: {not our_flight.first_fix or not our_flight.last_fix}')
    else:
        print(f'\n❌ Our persisted flight is NOT in the query results')
        
        # Check why not
        our_flight = session.query(Flight).filter(
            Flight.flight_id == 'tk905b-68b69cd1dfefb67daa124af8-68aadbb85da525060edaaebf-9590046863-1431-upload'
        ).first()
        
        if our_flight:
            print(f'\n  Flight exists but filtered out:')
            print(f'    race_id match: {our_flight.race_id == race_id}')
            print(f'    created_at >= opentime: {our_flight.created_at >= opentime_dt}')
            print(f'    created_at <= closetime: {our_flight.created_at <= closetime_dt}')
            print(f'    All conditions: {our_flight.race_id == race_id and our_flight.created_at >= opentime_dt and our_flight.created_at <= closetime_dt}')
    
    # Group by source
    by_source = {}
    for flight in flights:
        source = flight.source
        by_source[source] = by_source.get(source, 0) + 1
    
    print(f'\nFlights by source:')
    for source, count in by_source.items():
        print(f'  {source}: {count}')
        
finally:
    session.close()