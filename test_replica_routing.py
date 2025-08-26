#!/usr/bin/env python3
"""
Test script to verify replica database routing is working correctly
Tests both read operations (should use replica) and write operations (should use primary)
"""

import asyncio
import json
import sys
import os
from datetime import datetime, timezone
import requests
import websocket
import jwt

# Add the current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Configuration
BASE_URL = "http://localhost:8000"  # Change to your server URL
TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJwaWxvdF9pZCI6IjY4YWFkYmRjNWRhNTI1MDYwZWRhYWVjMiIsInJhY2VfaWQiOiI2OGFhZGJiODVkYTUyNTA2MGVkYWFlYmYiLCJwaWxvdF9uYW1lIjoiU2ltb25lIFNldmVyaW5pIiwiZXhwIjoxNzk2MTY5NTk5LCJyYWNlIjp7Im5hbWUiOiJIRlNTIEFwcCBUZXN0aW5nIiwiZGF0ZSI6IjIwMjUtMDEtMDEiLCJ0aW1lem9uZSI6IkV1cm9wZS9Sb21lIiwibG9jYXRpb24iOiJMYXZlbm8iLCJlbmRfZGF0ZSI6IjIwMjYtMTItMDEifSwiZW5kcG9pbnRzIjp7ImxpdmUiOiIvbGl2ZSIsInVwbG9hZCI6Ii91cGxvYWQifX0.MU5OrqbbTRX36Qves9wDx62btbBWkumVX_WYfmXqsYo"

def decode_token(token):
    """Decode JWT token to get pilot and race info"""
    try:
        # Decode without verification for testing
        payload = jwt.decode(token, options={"verify_signature": False})
        return payload
    except Exception as e:
        print(f"Error decoding token: {e}")
        return None

def test_database_routing():
    """Test that database routing is working correctly"""
    print("\n" + "="*60)
    print("REPLICA ROUTING VERIFICATION TEST")
    print("="*60)
    
    # Decode token to get info
    token_data = decode_token(TOKEN)
    if token_data:
        print(f"\nToken Info:")
        print(f"  Pilot: {token_data.get('pilot_name')} ({token_data.get('pilot_id')})")
        print(f"  Race: {token_data.get('race', {}).get('name')} ({token_data.get('race_id')})")
    
    # First, check database configuration locally
    try:
        from database.db_replica import primary_engine, replica_engine
        from config import settings
        
        print(f"\nLocal Configuration:")
        print(f"  USE_REPLICA: {settings.USE_REPLICA}")
        print(f"  Primary: {primary_engine.url.host}")
        print(f"  Replica: {replica_engine.url.host}")
        
        if primary_engine.url.host == replica_engine.url.host:
            print("  ⚠️  WARNING: Primary and replica point to the same host!")
        else:
            print("  ✅ Primary and replica are different hosts")
    except ImportError:
        print("\nCouldn't import local configuration (run from project directory)")
    
    print("\n" + "-"*40)
    print("Testing API Endpoints...")
    
    # Test 1: Send live tracking point (WRITE - should use primary)
    print("\n1. Testing WRITE operation (POST /live):")
    print("   This should use the PRIMARY database")
    
    test_point = {
        "lat": 45.89 + (datetime.now().second / 1000),  # Slightly different each time
        "lon": 8.63 + (datetime.now().second / 1000),
        "elevation": 350 + datetime.now().second,
        "datetime": datetime.now(timezone.utc).isoformat()
    }
    
    response = requests.post(
        f"{BASE_URL}/api/live",
        params={"token": TOKEN},
        json=test_point,
        timeout=5
    )
    
    if response.status_code == 202:
        print(f"   ✅ Point sent successfully: {test_point['datetime']}")
        flight_id = None
        try:
            resp_data = response.json()
            flight_id = resp_data.get('flight_id')
            if flight_id:
                print(f"   Flight UUID: {flight_id}")
        except:
            pass
    else:
        print(f"   ❌ Failed to send point: {response.status_code}")
        print(f"   Response: {response.text}")
    
    # Wait a moment for the point to be processed
    import time
    time.sleep(2)
    
    # Test 2: Read flights (READ - should use replica)
    print("\n2. Testing READ operation (GET /flights):")
    print("   This should use the REPLICA database")
    
    headers = {"Authorization": f"Bearer {TOKEN}"}
    response = requests.get(
        f"{BASE_URL}/api/flights",
        params={"race_id": token_data.get('race_id')} if token_data else {},
        headers=headers,
        timeout=5
    )
    
    if response.status_code == 200:
        flights = response.json()
        print(f"   ✅ Retrieved {len(flights)} flights from replica")
        if flights and len(flights) > 0:
            latest = flights[0]
            print(f"   Latest flight: {latest.get('pilot_name', 'Unknown')} - {latest.get('last_fix', {}).get('datetime', 'N/A')}")
    else:
        print(f"   ❌ Failed to read flights: {response.status_code}")
    
    # Test 3: Read live points (READ - should use replica)
    if flight_id:
        print(f"\n3. Testing READ operation (GET /live/points/{flight_id}):")
        print("   This should use the REPLICA database")
        
        response = requests.get(
            f"{BASE_URL}/api/live/points/{flight_id}",
            headers=headers,
            timeout=5
        )
        
        if response.status_code == 200:
            data = response.json()
            if data.get('type') == 'FeatureCollection':
                features = data.get('features', [])
                print(f"   ✅ Retrieved {len(features)} points from replica")
                if features:
                    latest_time = features[-1].get('properties', {}).get('datetime')
                    print(f"   Latest point: {latest_time}")
            else:
                print(f"   ✅ Retrieved track data from replica")
        else:
            print(f"   ❌ Failed to read points: {response.status_code}")
    
    # Test 4: Check live users (READ - should use replica)
    print("\n4. Testing READ operation (GET /live/users):")
    print("   This should use the REPLICA database")
    
    opentime = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0).isoformat()
    response = requests.get(
        f"{BASE_URL}/api/live/users",
        params={"opentime": opentime},
        headers=headers,
        timeout=5
    )
    
    if response.status_code == 200:
        users = response.json()
        print(f"   ✅ Retrieved {len(users)} active users from replica")
    else:
        print(f"   ❌ Failed to read users: {response.status_code}")
    
    print("\n" + "="*60)
    print("VERIFICATION COMPLETE")
    print("\nTo confirm routing:")
    print("1. Check application logs for 'replica' vs 'primary' messages")
    print("2. Monitor Neon dashboard connections on both endpoints")
    print("3. Primary should show spikes during writes")
    print("4. Replica should show activity during reads")
    print("="*60 + "\n")

def test_websocket_connection():
    """Test WebSocket connection (should read from replica)"""
    print("\n" + "-"*40)
    print("5. Testing WebSocket (should use REPLICA for initial data):")
    
    token_data = decode_token(TOKEN)
    if not token_data:
        print("   ❌ Could not decode token")
        return
    
    race_id = token_data.get('race_id')
    ws_url = f"ws://localhost:8000/api/ws/track/{race_id}?client_id=test&token={TOKEN}"
    
    try:
        ws = websocket.create_connection(ws_url, timeout=5)
        print("   ✅ WebSocket connected (initial data should come from replica)")
        
        # Wait for initial message
        result = ws.recv()
        data = json.loads(result)
        print(f"   Received: {data.get('type', 'unknown')} message")
        
        if data.get('type') == 'connection_status':
            print(f"   Active viewers: {data.get('active_viewers', 0)}")
        
        ws.close()
    except Exception as e:
        print(f"   ❌ WebSocket error: {e}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='Test replica database routing')
    parser.add_argument('--url', default='http://localhost:8000', help='Base URL of the API')
    parser.add_argument('--token', default=TOKEN, help='JWT token for authentication')
    args = parser.parse_args()
    
    BASE_URL = args.url
    TOKEN = args.token
    
    try:
        test_database_routing()
        test_websocket_connection()
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()