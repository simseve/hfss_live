#!/usr/bin/env python3
"""
Complete WebSocket test script that:
1. Adds live tracking points
2. Connects to WebSocket
3. Sends viewport_update
4. Waits for delta updates
"""
import asyncio
import aiohttp
import websockets
import json
import base64
import gzip
from datetime import datetime, timezone
import time
import random

# Configuration
API_BASE = "https://api.hikeandfly.app"
RACE_ID = "68aadbb85da525060edaaebf"
WS_URL = f"wss://api.hikeandfly.app/live/ws/live/{RACE_ID}?token=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJoaWtlYW5kZmx5LmFwcCIsImF1ZCI6ImFwaS5oaWtlYW5kZmx5LmFwcCIsImV4cCI6MTc5NjExNzQzMiwic3ViIjoiY29udGVzdDo2OGFhZGJiODVkYTUyNTA2MGVkYWFlYmYiLCJhY3QiOnsic3ViIjoiNjhhODNmZWJlZjg2NGIzYjI1OWI3MTY0In19.0c-AYNH_J353nuSrUixL-JrWqAp4MgNyNY5bEqxmRBU&client_id=test_script"

async def add_live_points():
    """Add live tracking points via REST API"""
    # Zurich coordinates
    base_lat = 47.3769
    base_lng = 8.5417
    
    points = []
    current_time = int(time.time())
    
    # Generate 10 points with slight movement
    for i in range(10):
        points.append({
            "lat": base_lat + random.uniform(-0.001, 0.001),
            "lng": base_lng + random.uniform(-0.001, 0.001),
            "altitude": 450 + random.uniform(-10, 10),
            "timestamp": current_time - (10 - i) * 10,  # Points from last 100 seconds
            "speed": 35 + random.uniform(-5, 5),
            "vario": random.uniform(-1, 2),
            "heading": random.randint(0, 359)
        })
    
    payload = {
        "race_id": RACE_ID,
        "pilot_id": "test_pilot_001",
        "pilot_name": "Test Pilot Zurich",
        "points": points,
        "device_id": "test_simulator",
        "tracker_type": "simulator"
    }
    
    headers = {
        "Content-Type": "application/json",
        "X-Tracking-Token": "simulator-token-12345"
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{API_BASE}/api/v2/live/add_live_track_points",
            json=payload,
            headers=headers
        ) as response:
            if response.status in [200, 202]:
                print(f"✓ Added {len(points)} live points at {datetime.now().strftime('%H:%M:%S')}")
                return True
            else:
                text = await response.text()
                print(f"✗ Failed to add points: {response.status} - {text[:200]}")
                return False

async def websocket_client():
    """Connect to WebSocket and listen for updates"""
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Connecting to WebSocket...")
    
    delta_count = 0
    tile_count = 0
    last_update = datetime.now()
    
    async with websockets.connect(WS_URL) as websocket:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ✓ Connected to WebSocket")
        
        # Wait for initial messages
        for _ in range(3):
            try:
                message = await asyncio.wait_for(websocket.recv(), timeout=1)
                data = json.loads(message)
                msg_type = data.get('type', 'unknown')
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Received: {msg_type}")
                
                if msg_type == 'race_config':
                    print(f"  → Update interval: {data.get('update_interval')}s")
                    print(f"  → Features: {list(data.get('features', {}).keys())}")
            except asyncio.TimeoutError:
                break
        
        # Send viewport update for Zurich tiles
        viewport_msg = {
            "type": "viewport_update",
            "viewport": {
                "tiles": [
                    [10, 536, 362],  # Zurich center
                    [10, 537, 362],
                    [10, 536, 363],
                    [10, 537, 363]
                ]
            }
        }
        
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Sending viewport_update for Zurich tiles...")
        await websocket.send(json.dumps(viewport_msg))
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ✓ Viewport update sent")
        
        # Also request initial data
        initial_msg = {
            "type": "request_initial_data",
            "zoom": 10,
            "bbox": [8.4, 47.3, 8.7, 47.5]  # Zurich area
        }
        
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Sending request_initial_data...")
        await websocket.send(json.dumps(initial_msg))
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ✓ Initial data requested")
        
        print(f"\n{'='*60}")
        print("Waiting for 10-second delta updates...")
        print(f"{'='*60}\n")
        
        # Listen for updates
        ping_time = datetime.now()
        
        while True:
            try:
                # Send ping every 30 seconds
                if (datetime.now() - ping_time).total_seconds() > 30:
                    await websocket.send(json.dumps({
                        "type": "ping",
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    }))
                    ping_time = datetime.now()
                
                # Wait for message with timeout
                message = await asyncio.wait_for(websocket.recv(), timeout=1)
                data = json.loads(message)
                msg_type = data.get('type', 'unknown')
                
                current_time = datetime.now()
                time_since_last = (current_time - last_update).total_seconds()
                
                if msg_type == 'delta_update':
                    delta_count += 1
                    print(f"[{current_time.strftime('%H:%M:%S')}] 🔄 DELTA UPDATE #{delta_count}")
                    print(f"  → Time since last update: {time_since_last:.1f}s")
                    print(f"  → Update count: {data.get('update_count', 0)}")
                    print(f"  → Compression: {data.get('compression', 'none')}")
                    
                    # Try to decode the delta data
                    if 'data' in data:
                        try:
                            compressed = base64.b64decode(data['data'])
                            if data.get('compression') == 'gzip':
                                decompressed = gzip.decompress(compressed)
                                delta_json = json.loads(decompressed)
                                print(f"  → Delta contains: {len(delta_json.get('updates', []))} updates")
                        except:
                            pass
                    
                    last_update = current_time
                    print()
                    
                elif msg_type == 'tile_data':
                    tile_count += 1
                    tile = data.get('tile', {})
                    print(f"[{current_time.strftime('%H:%M:%S')}] 📍 Tile data #{tile_count}: z={tile.get('z')}, x={tile.get('x')}, y={tile.get('y')}")
                    
                elif msg_type == 'heartbeat':
                    print(f"[{current_time.strftime('%H:%M:%S')}] 💓 Heartbeat")
                    
                elif msg_type not in ['pong', 'connection_status', 'race_config', 'viewer_count', 'initial_data_complete']:
                    print(f"[{current_time.strftime('%H:%M:%S')}] {msg_type}: {str(data)[:100]}")
                
            except asyncio.TimeoutError:
                # No message received, continue
                pass
            except websockets.ConnectionClosed:
                print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Connection closed")
                break
            except Exception as e:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Error: {e}")

async def continuous_point_sender():
    """Continuously send new points every 10 seconds"""
    while True:
        await add_live_points()
        await asyncio.sleep(10)

async def main():
    print("="*60)
    print("WebSocket Delta Update Test")
    print("="*60)
    
    # First, add some initial points
    print("\n1. Adding initial live tracking points...")
    await add_live_points()
    
    # Wait a moment for points to be processed
    await asyncio.sleep(2)
    
    # Start continuous point sender in background
    print("\n2. Starting continuous point sender (every 10s)...")
    point_sender = asyncio.create_task(continuous_point_sender())
    
    # Connect to WebSocket and listen
    print("\n3. Connecting to WebSocket and subscribing to Zurich tiles...")
    try:
        await websocket_client()
    except KeyboardInterrupt:
        print("\n\nStopped by user")
    finally:
        point_sender.cancel()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nTest terminated by user")