#!/usr/bin/env python
"""Debug why upload flight isn't showing in API"""

from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database.models import Flight
from config import settings

engine = create_engine(settings.DATABASE_URL)
Session = sessionmaker(bind=engine)
session = Session()

try:
    # Parameters from the API call
    race_id = '68aadbb85da525060edaaebf'
    opentime_dt = datetime.fromisoformat('2025-01-01T00:00:00+00:00')
    closetime_dt = datetime.now(timezone.utc) + timedelta(hours=24)
    
    # Get the upload flight specifically
    upload_flight = session.query(Flight).filter(
        Flight.flight_id == 'tk905b-68b69cd1dfefb67daa124af8-68aadbb85da525060edaaebf-9590046863-1431-upload'
    ).first()
    
    if upload_flight:
        print('Upload Flight Analysis:')
        print(f'  flight_id: {upload_flight.flight_id}')
        print(f'  UUID: {upload_flight.id}')
        print(f'  source: {upload_flight.source}')
        print(f'  race_id: {upload_flight.race_id}')
        print(f'  created_at: {upload_flight.created_at}')
        print(f'  total_points: {upload_flight.total_points}')
        print(f'  first_fix: {upload_flight.first_fix}')
        print(f'  last_fix: {upload_flight.last_fix}')
        
        print(f'\nQuery condition checks:')
        print(f'  ✓ race_id matches: {upload_flight.race_id == race_id} ({upload_flight.race_id} == {race_id})')
        print(f'  ✓ created_at >= opentime: {upload_flight.created_at >= opentime_dt}')
        print(f'  ✓ created_at <= closetime: {upload_flight.created_at <= closetime_dt}')
        print(f'  ✓ has first_fix: {upload_flight.first_fix is not None}')
        print(f'  ✓ has last_fix: {upload_flight.last_fix is not None}')
        
        all_conditions = (
            upload_flight.race_id == race_id and
            upload_flight.created_at >= opentime_dt and
            upload_flight.created_at <= closetime_dt and
            upload_flight.first_fix is not None and
            upload_flight.last_fix is not None
        )
        
        if all_conditions:
            print(f'\n✅ ALL CONDITIONS MET - Should be in API response')
        else:
            print(f'\n❌ Some conditions not met')
            
        # Test the exact query
        print(f'\nTesting exact API query:')
        query_result = session.query(Flight).filter(
            Flight.race_id == race_id,
            Flight.created_at >= opentime_dt,
            Flight.created_at <= closetime_dt
        )
        
        # Check if upload flight is in results
        all_flights = query_result.all()
        upload_in_results = any(f.id == upload_flight.id for f in all_flights)
        
        print(f'  Query returns {len(all_flights)} total flights')
        print(f'  Upload flight in results: {upload_in_results}')
        
        if upload_in_results:
            # Count by source
            source_counts = {}
            for f in all_flights:
                source_counts[f.source] = source_counts.get(f.source, 0) + 1
                if f.id == upload_flight.id:
                    print(f'  Found upload flight at position in query results')
                    
            print(f'\nFlights by source in query:')
            for source, count in sorted(source_counts.items()):
                print(f'    {source}: {count}')
    else:
        print('Upload flight not found!')
        
finally:
    session.close()