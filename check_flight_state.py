#!/usr/bin/env python
"""Check current state of persisted flight"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database.models import Flight, UploadedTrackPoint
from config import settings

engine = create_engine(settings.DATABASE_URL)
Session = sessionmaker(bind=engine)
session = Session()

try:
    # Check the upload flight
    flight = session.query(Flight).filter(
        Flight.flight_id == 'tk905b-68b69cd1dfefb67daa124af8-68aadbb85da525060edaaebf-9590046863-1431-upload'
    ).first()
    
    if flight:
        print(f'Upload flight status:')
        print(f'  flight_id: {flight.flight_id}')
        print(f'  source: {flight.source}')
        print(f'  total_points: {flight.total_points}')
        print(f'  first_fix: {flight.first_fix}')
        print(f'  last_fix: {flight.last_fix}')
        
        if not flight.first_fix or not flight.last_fix:
            print('\n❌ Flight has NULL fixes - this is why it\'s not showing in /live/users!')
            
            # Check if points exist
            point_count = session.query(UploadedTrackPoint).filter(
                UploadedTrackPoint.flight_uuid == flight.id
            ).count()
            
            print(f'\n  Points in database: {point_count}')
            
            if point_count > 0:
                # Get first and last point
                first_point = session.query(UploadedTrackPoint).filter(
                    UploadedTrackPoint.flight_uuid == flight.id
                ).order_by(UploadedTrackPoint.datetime.asc()).first()
                
                last_point = session.query(UploadedTrackPoint).filter(
                    UploadedTrackPoint.flight_uuid == flight.id
                ).order_by(UploadedTrackPoint.datetime.desc()).first()
                
                if first_point and last_point:
                    print(f'  First point datetime: {first_point.datetime}')
                    print(f'  Last point datetime: {last_point.datetime}')
                    print(f'\n  The trigger should have updated first_fix and last_fix!')
                    print(f'  This might be a trigger issue.')
        else:
            print('\n✅ Flight has fixes - should be visible in /live/users')
            
    else:
        print('Upload flight not found')
        
finally:
    session.close()