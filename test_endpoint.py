#!/usr/bin/env python
"""Test the live/users endpoint to see if upload flights are returned"""

import requests
from datetime import datetime, timezone, timedelta
import jwt
from config import settings
import json

# Create a test JWT token for the race
payload = {
    'sub': 'contest:68b69cd1dfefb67daa124af8',
    'aud': 'api.hikeandfly.app',
    'iss': 'hikeandfly.app',
    'iat': datetime.now(timezone.utc).timestamp(),
    'exp': (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()
}
token = jwt.encode(payload, settings.SECRET_KEY, algorithm='HS256')

print(f'Testing /live/users endpoint')
print(f'Race ID: 68b69cd1dfefb67daa124af8')
print(f'Token: {token[:50]}...\n')

# Test 1: Without source filter (should return all)
url = 'http://localhost:8000/tracking/live/users'
params = {'opentime': '2025-01-01T00:00:00Z'}
headers = {'Authorization': f'Bearer {token}'}

print(f'Test 1: Without source filter')
print(f'URL: {url}')
print(f'Params: {params}')

try:
    response = requests.get(url, params=params, headers=headers)
    print(f'Status: {response.status_code}')
    
    if response.status_code == 200:
        data = response.json()
        pilots = data.get('pilots', {})
        print(f'Number of pilots: {len(pilots)}')
        
        # Look for upload flights
        upload_count = 0
        live_count = 0
        for pilot_id, pilot_data in pilots.items():
            for flight_id, flight_data in pilot_data.get('flights', {}).items():
                source = flight_data.get('source', '')
                if 'upload' in source:
                    upload_count += 1
                    print(f'  Found upload flight: {flight_id[:50]}... (source: {source})')
                elif 'live' in source:
                    live_count += 1
                    
        print(f'Summary: {live_count} live flights, {upload_count} upload flights')
    else:
        print(f'Error response: {response.text[:200]}')
        
except requests.exceptions.ConnectionError:
    print('Could not connect to server. Is it running on localhost:8000?')
    
print('\n---\n')

# Test 2: Check database directly for comparison
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database.models import Flight

engine = create_engine(settings.DATABASE_URL)
Session = sessionmaker(bind=engine)
session = Session()

try:
    opentime_dt = datetime.fromisoformat('2025-01-01T00:00:00+00:00')
    closetime_dt = datetime.now(timezone.utc) + timedelta(hours=24)
    
    # Query matching what the endpoint should do
    flights = session.query(Flight).filter(
        Flight.race_id == '68b69cd1dfefb67daa124af8',
        Flight.created_at >= opentime_dt,
        Flight.created_at <= closetime_dt
    ).all()
    
    print(f'Database query (matching endpoint logic):')
    print(f'  Total flights in time window: {len(flights)}')
    
    sources = {}
    for f in flights:
        source = f.source
        sources[source] = sources.get(source, 0) + 1
        
    print(f'  By source:')
    for source, count in sources.items():
        print(f'    - {source}: {count}')
        
    # Specifically check for our persisted flight
    persisted = session.query(Flight).filter(
        Flight.flight_id == 'tk905b-68b69cd1dfefb67daa124af8-68aadbb85da525060edaaebf-9590046863-1431-upload'
    ).first()
    
    if persisted:
        print(f'\nOur persisted flight:')
        print(f'  Would be included: {persisted.created_at >= opentime_dt and persisted.created_at <= closetime_dt}')
    
finally:
    session.close()