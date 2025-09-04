#!/usr/bin/env python
"""Test if upload flight shows in API"""

import requests
import json

token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJoaWtlYW5kZmx5LmFwcCIsImF1ZCI6ImFwaS5oaWtlYW5kZmx5LmFwcCIsImV4cCI6MTc5NjExNzQzMiwic3ViIjoiY29udGVzdDo2OGFhZGJiODVkYTUyNTA2MGVkYWFlYmYiLCJhY3QiOnsic3ViIjoiNjhhODNmZWJlZjg2NGIzYjI1OWI3MTY0In19.0c-AYNH_J353nuSrUixL-JrWqAp4MgNyNY5bEqxmRBU"

url = 'https://dev-api.hikeandfly.app/tracking/live/users'
params = {'opentime': '2025-01-01T00:00:00Z'}
headers = {'Authorization': f'Bearer {token}'}

print(f'Testing: {url}')
print(f'With params: {params}\n')

response = requests.get(url, params=params, headers=headers, timeout=10)
print(f'Status Code: {response.status_code}')

if response.status_code == 200:
    data = response.json()
    response_str = json.dumps(data, default=str)
    
    # Look for upload flights
    if 'tk905b_upload' in response_str:
        print('✅ Found tk905b_upload flight!')
        # Extract details
        pilots = data.get('pilots', {})
        for pilot_id, pilot_data in pilots.items():
            flights = pilot_data.get('flights', [])
            for flight in flights:
                if flight.get('source') == 'tk905b_upload':
                    print(f'  UUID: {flight.get("uuid")}')
                    print(f'  Points: {flight.get("total_points", "N/A")}')
                    print(f'  First Fix: {flight.get("firstFixTime")}')
    else:
        print('❌ No tk905b_upload flight found')
    
    # Count sources
    sources = {}
    pilots = data.get('pilots', {})
    for pilot_id, pilot_data in pilots.items():
        for flight in pilot_data.get('flights', []):
            source = flight.get('source', 'unknown')
            sources[source] = sources.get(source, 0) + 1
    
    print(f'\nFlights by source:')
    for source, count in sorted(sources.items()):
        print(f'  {source}: {count}')
        
    upload_count = sum(1 for s in sources if 'upload' in s)
    print(f'\nTotal upload flights: {upload_count}')