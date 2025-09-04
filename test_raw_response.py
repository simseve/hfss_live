#!/usr/bin/env python
"""Get raw response from the endpoint"""

import requests
import json

token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJoaWtlYW5kZmx5LmFwcCIsImF1ZCI6ImFwaS5oaWtlYW5kZmx5LmFwcCIsImV4cCI6MTc5NjExNzQzMiwic3ViIjoiY29udGVzdDo2OGFhZGJiODVkYTUyNTA2MGVkYWFlYmYiLCJhY3QiOnsic3ViIjoiNjhhODNmZWJlZjg2NGIzYjI1OWI3MTY0In19.0c-AYNH_J353nuSrUixL-JrWqAp4MgNyNY5bEqxmRBU"

url = 'http://dev-api.hikeandfly.app/tracking/live/users'
params = {'opentime': '2025-01-01T00:00:00Z'}
headers = {'Authorization': f'Bearer {token}'}

response = requests.get(url, params=params, headers=headers, timeout=10)
print(f'Status: {response.status_code}')

if response.status_code == 200:
    data = response.json()
    
    # Pretty print the structure
    print('\nResponse structure:')
    print(json.dumps(data, indent=2, default=str)[:2000])  # First 2000 chars
    
    # Check for our flight
    response_str = json.dumps(data, default=str)
    if '9590046863-1431' in response_str:
        print('\n✅ Flight ID 9590046863-1431 found in response!')
        
        # Find where it is
        if 'upload' in response_str:
            print('  And "upload" keyword found!')
    else:
        print('\n❌ Flight ID 9590046863-1431 NOT found in response')
        
    # Count sources
    live_count = response_str.count('"source": "live"') + response_str.count('"source": "flymaster_live"') + response_str.count('"source": "tk905b_live"')
    upload_count = response_str.count('"source": "upload"') + response_str.count('"source": "flymaster_upload"') + response_str.count('"source": "tk905b_upload"')
    
    print(f'\nSource counts in response:')
    print(f'  Live sources: {live_count}')
    print(f'  Upload sources: {upload_count}')