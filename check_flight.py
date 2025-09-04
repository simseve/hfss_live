#!/usr/bin/env python
"""Check if persisted flight shows in live/users endpoint"""

from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database.models import Flight
from config import settings

# Create database connection
engine = create_engine(settings.DATABASE_URL)
Session = sessionmaker(bind=engine)
session = Session()

try:
    # Check the specific upload flight
    upload_flight = session.query(Flight).filter(
        Flight.flight_id.like('%9590046863-1431-upload%')
    ).first()
    
    if upload_flight:
        print(f'Found persisted flight:')
        print(f'  flight_id: {upload_flight.flight_id}')
        print(f'  source: {upload_flight.source}')
        print(f'  created_at: {upload_flight.created_at}')
        print(f'  pilot: {upload_flight.pilot_name}')
        print(f'  total_points: {upload_flight.total_points}')
        
        # Check against opentime filter
        opentime_dt = datetime.fromisoformat('2025-01-01T00:00:00+00:00')
        
        print(f'\nFilter check:')
        print(f'  opentime filter: {opentime_dt}')
        print(f'  flight created:  {upload_flight.created_at}')
        
        if upload_flight.created_at >= opentime_dt:
            print(f'\n✅ Flight WOULD show in UI (created after opentime)')
        else:
            print(f'\n❌ Flight would NOT show in UI (created before opentime)')
            time_diff = opentime_dt - upload_flight.created_at
            print(f'   Flight is {time_diff.days} days older than opentime filter')
            
        # Also check the original live flight
        live_flight = session.query(Flight).filter(
            Flight.flight_id.like('%9590046863-1431'),
            Flight.source.like('%live%')
        ).first()
        
        if live_flight:
            print(f'\nOriginal live flight:')
            print(f'  created_at: {live_flight.created_at}')
            print(f'  This is what upload flight inherited')
    else:
        print('Upload flight not found')
        
        # Check if any version exists
        any_flight = session.query(Flight).filter(
            Flight.flight_id.like('%9590046863-1431%')
        ).all()
        
        print(f'\nFound {len(any_flight)} flights with this ID:')
        for f in any_flight:
            print(f'  - {f.flight_id} (source: {f.source})')
        
finally:
    session.close()