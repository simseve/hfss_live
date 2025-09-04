#!/usr/bin/env python
"""Test the live/users endpoint with the correct token"""

import requests
import jwt
import json
from datetime import datetime, timezone

# The correct token from user
token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJoaWtlYW5kZmx5LmFwcCIsImF1ZCI6ImFwaS5oaWtlYW5kZmx5LmFwcCIsImV4cCI6MTc5NjExNzQzMiwic3ViIjoiY29udGVzdDo2OGFhZGJiODVkYTUyNTA2MGVkYWFlYmYiLCJhY3QiOnsic3ViIjoiNjhhODNmZWJlZjg2NGIzYjI1OWI3MTY0In19.0c-AYNH_J353nuSrUixL-JrWqAp4MgNyNY5bEqxmRBU"

# Decode to see contents (without verification for inspection)
payload = jwt.decode(token, options={"verify_signature": False})
print(f'Token contents:')
print(json.dumps(payload, indent=2))
print(f'\nRace ID from token: {payload["sub"].split(":")[1]}')

# Test against local server
print('\nTesting against local server...')
url = 'http://localhost:8000/tracking/live/users'
params = {'opentime': '2025-01-01T00:00:00Z'}
headers = {'Authorization': f'Bearer {token}'}

try:
    response = requests.get(url, params=params, headers=headers, timeout=5)
    print(f'Status: {response.status_code}')
    
    if response.status_code == 200:
        data = response.json()
        pilots = data.get('pilots', {})
        print(f'Number of pilots: {len(pilots)}')
        
        # Look specifically for our persisted flight
        found_persisted = False
        for pilot_id, pilot_data in pilots.items():
            if 'Tk905B' in pilot_data.get('pilot_name', ''):
                print(f'\nFound Tk905B pilot: {pilot_data.get("pilot_name")}')
                for flight_id, flight_data in pilot_data.get('flights', {}).items():
                    if '9590046863-1431' in flight_id:
                        found_persisted = True
                        print(f'  ✅ Found our persisted flight!')
                        print(f'    Flight ID: {flight_id}')
                        print(f'    Source: {flight_data.get("source")}')
                        print(f'    Points: {flight_data.get("total_points")}')
                        
        if not found_persisted:
            print('\n❌ Persisted flight NOT found in response')
            
            # Show what we did find
            print('\nFlights in response:')
            count = 0
            for pilot_id, pilot_data in pilots.items():
                for flight_id, flight_data in pilot_data.get('flights', {}).items():
                    count += 1
                    if count <= 5:  # Show first 5
                        print(f'  - {flight_id[:50]}...')
                        print(f'    Source: {flight_data.get("source")}')
    else:
        print(f'Error: {response.text[:500]}')
        
except requests.exceptions.ConnectionError:
    print('Could not connect to local server')
    
except requests.exceptions.Timeout:
    print('Request timed out')

# Test against dev server
print('\n---\nTesting against dev server...')
url = 'http://dev-api.hikeandfly.app/tracking/live/users'

try:
    response = requests.get(url, params=params, headers=headers, timeout=10)
    print(f'Status: {response.status_code}')
    
    if response.status_code == 200:
        data = response.json()
        pilots = data.get('pilots', {})
        print(f'Number of pilots: {len(pilots)}')
        
        # Look for upload flights
        found_persisted = False
        upload_count = 0
        live_count = 0
        
        # Check if pilots is a dict or list
        if isinstance(pilots, dict):
            pilots_iter = pilots.items()
        else:
            print(f'  Pilots is a list with {len(pilots)} items')
            pilots_iter = enumerate(pilots)
            
        for pilot_key, pilot_data in pilots_iter:
            if isinstance(pilot_data, dict):
                pilot_name = pilot_data.get('pilot_name', '')
                flights = pilot_data.get('flights', {})
            else:
                print(f'  Unexpected pilot data type: {type(pilot_data)}')
                continue
            
            for flight_id, flight_data in flights.items():
                source = flight_data.get('source', '')
                
                if 'upload' in source:
                    upload_count += 1
                    if '9590046863-1431' in flight_id:
                        found_persisted = True
                        print(f'\n✅ Found persisted flight!')
                        print(f'  Pilot: {pilot_name}')
                        print(f'  Flight: {flight_id}')
                        print(f'  Source: {source}')
                        print(f'  Points: {flight_data.get("total_points")}')
                elif 'live' in source:
                    live_count += 1
                    
        print(f'\nSummary:')
        print(f'  Live flights: {live_count}')
        print(f'  Upload flights: {upload_count}')
        
        if not found_persisted and upload_count == 0:
            print('\n❌ No upload flights found - they may be filtered out')
            print('   The endpoint might only be returning live flights')
            
except Exception as e:
    print(f'Error: {e}')