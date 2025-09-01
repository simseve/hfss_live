#!/usr/bin/env python3
"""Test WebSocket connection"""

import asyncio
import websockets
import json

async def test_websocket():
    race_id = "68aadbb85da525060edaaebf"
    token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJoaWtlYW5kZmx5LmFwcCIsImF1ZCI6ImFwaS5oaWtlYW5kZmx5LmFwcCIsImV4cCI6MTc5NjExNzQzMiwic3ViIjoiY29udGVzdDo2OGFhZGJiODVkYTUyNTA2MGVkYWFlYmYiLCJhY3QiOnsic3ViIjoiNjhhODNmZWJlZjg2NGIzYjI1OWI3MTY0In19.0c-AYNH_J353nuSrUixL-JrWqAp4MgNyNY5bEqxmRBU"
    client_id = "test_python_client"
    
    # Note: Using localhost instead of api.hikeandfly.app for local testing
    uri = f"ws://localhost:8000/tracking/ws/track/{race_id}?token={token}&client_id={client_id}"
    
    print(f"Connecting to WebSocket...")
    print(f"Race ID: {race_id}")
    print(f"Client ID: {client_id}")
    
    try:
        async with websockets.connect(uri) as websocket:
            print("✅ Connected to WebSocket")
            
            # Wait for initial data
            print("\nWaiting for initial data...")
            message = await asyncio.wait_for(websocket.recv(), timeout=5)
            data = json.loads(message)
            
            print(f"\n📦 Received message type: {data.get('type', 'unknown')}")
            
            if data.get('type') == 'initial_data':
                flights = data.get('flights', [])
                print(f"✈️ Number of flights: {len(flights)}")
                
                for flight in flights:
                    print(f"\nFlight: {flight.get('pilot_name', 'Unknown')}")
                    print(f"  UUID: {flight.get('uuid', 'N/A')}")
                    print(f"  Source: {flight.get('source', 'N/A')}")
                    print(f"  Track points: {flight.get('downsampledPoints', 0)}/{flight.get('totalPoints', 0)}")
                    if flight.get('lastFix'):
                        print(f"  Last fix: {flight['lastFix'].get('datetime', 'N/A')}")
            
            # Send a ping to test bidirectional communication
            print("\n📤 Sending ping...")
            await websocket.send(json.dumps({"type": "ping"}))
            
            # Wait for pong
            response = await asyncio.wait_for(websocket.recv(), timeout=5)
            pong = json.loads(response)
            if pong.get('type') == 'pong':
                print("✅ Received pong")
            
            print("\n✅ WebSocket test successful!")
            
    except asyncio.TimeoutError:
        print("❌ Timeout waiting for response")
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_websocket())