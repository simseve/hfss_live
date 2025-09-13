"""
Production-ready tile endpoints for live tracking
Optimized for handling hundreds of concurrent users
"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, Response
from typing import Optional, Dict, List, Tuple
import logging
import json
from datetime import datetime, timezone, timedelta
from database.db_replica import get_read_db_with_fallback
from database.models import Race, Flight
from ws_tile_conn import tile_manager
import asyncio

logger = logging.getLogger(__name__)

router = APIRouter()

@router.websocket("/ws/live/{race_id}")
async def websocket_live_endpoint(
    websocket: WebSocket,
    race_id: str,
    client_id: str = Query(...)
):
    """WebSocket endpoint for production tile-based live tracking"""
    await websocket.accept()
    
    try:
        # Connect to tile manager
        await tile_manager.connect(websocket, race_id, client_id)
        
        # Handle messages
        while True:
            try:
                # Wait for messages with timeout
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30)
                message = json.loads(data)
                
                # Handle different message types
                if message.get('type') == 'viewport_update':
                    # Update client viewport
                    viewport = message.get('viewport', {})
                    tiles = viewport.get('tiles', [])
                    if tiles:
                        # Convert list of [z, x, y] to tuples
                        tile_tuples = [tuple(t) for t in tiles]
                        await tile_manager.update_client_viewport(
                            client_id, race_id, tile_tuples
                        )
                        
                elif message.get('type') == 'request_tiles':
                    # Request specific tiles
                    requested = message.get('tiles', [])
                    if requested:
                        tile_tuples = [tuple(t) for t in requested]
                        await tile_manager.request_tiles_for_client(
                            client_id, race_id, tile_tuples
                        )
                        
                elif message.get('type') == 'request_initial_data':
                    # Send initial data including flights and tasks
                    await send_initial_data(websocket, race_id, client_id, message)
                    
                elif message.get('type') == 'ping':
                    # Respond to ping
                    await websocket.send_json({
                        "type": "pong",
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    })
                    
            except asyncio.TimeoutError:
                # Send heartbeat on timeout
                await websocket.send_json({
                    "type": "heartbeat",
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })
                
    except WebSocketDisconnect:
        logger.info(f"Client {client_id} disconnected normally")
    except Exception as e:
        logger.error(f"WebSocket error for client {client_id}: {e}")
    finally:
        await tile_manager.disconnect(websocket, client_id)


async def send_initial_data(websocket: WebSocket, race_id: str, client_id: str, message: Dict):
    """Send initial data to client including flights and tasks"""
    try:
        db = next(get_read_db_with_fallback())
        
        response = {
            "type": "initial_data",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        # Include pilots/flights if requested
        if message.get('include_pilots'):
            # Only get flights that have been active in the last 24 hours
            cutoff_time = datetime.now(timezone.utc) - timedelta(hours=24)
            all_flights = db.query(Flight).filter(
                Flight.race_id == race_id,
                Flight.source.like('%live%'),
                Flight.last_fix.isnot(None),
                Flight.created_at >= cutoff_time  # Only flights created in last 24 hours
            ).all()
            
            # Group by pilot_id and keep only the most recent flight for each pilot
            pilot_flights = {}
            for flight in all_flights:
                if flight.pilot_id not in pilot_flights:
                    pilot_flights[flight.pilot_id] = flight
                else:
                    # Keep the more recent flight based on created_at
                    if flight.created_at > pilot_flights[flight.pilot_id].created_at:
                        pilot_flights[flight.pilot_id] = flight
            
            # Use only the most recent flight for each pilot
            flights = list(pilot_flights.values())
            
            flight_data = []
            for flight in flights:
                if flight.last_fix:
                    flight_info = {
                        "pilot_id": flight.pilot_id,
                        "pilot_name": flight.pilot_name or "Unknown",
                        "uuid": str(flight.id),  # Convert UUID to string
                        "source": flight.source,
                        "isActive": True,
                        "lastFix": flight.last_fix,
                        "flight_state": "flying",
                        "flight_state_info": {}
                    }
                    flight_data.append(flight_info)
            
            response["flights"] = flight_data
            logger.info(f"Sent {len(flight_data)} flights to {client_id}")
        
        # Fetch tasks from local endpoint (which has caching and fallback to HFSS)
        if message.get('include_tasks'):
            try:
                import aiohttp
                
                # Use local endpoint which handles HFSS communication and caching
                local_url = f"http://localhost:8000/tracking/tasks/race/{race_id}"
                logger.debug(f"Fetching tasks from local endpoint: {local_url}")
                timeout = aiohttp.ClientTimeout(total=5)  # 5 second timeout
                
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(local_url) as resp:
                        if resp.status == 200:
                            task_response = await resp.json()
                            # Extract tasks from the response structure
                            if task_response.get("success") and "tasks" in task_response:
                                tasks_data = task_response["tasks"]
                                if isinstance(tasks_data, dict) and "features" in tasks_data:
                                    # Convert GeoJSON features to the expected format
                                    response["tasks"] = []
                                    for feature in tasks_data["features"]:
                                        # Combine geometry coordinates with waypoint metadata
                                        waypoints = []
                                        if "waypoints" in feature and "geometry" in feature:
                                            coords = feature["geometry"].get("coordinates", [])
                                            waypoint_meta = feature["waypoints"]
                                            
                                            # Match coordinates with waypoint metadata
                                            for i, wp_meta in enumerate(waypoint_meta):
                                                if i < len(coords):
                                                    coord = coords[i]
                                                    waypoints.append({
                                                        "lat": coord[1],
                                                        "lon": coord[0],
                                                        "name": wp_meta.get("name", ""),
                                                        "radius": wp_meta.get("radius", 50),
                                                        "type": wp_meta.get("type", 1),
                                                        "seq": wp_meta.get("seq", i + 1)
                                                    })
                                        
                                        if waypoints:
                                            task = {
                                                "task_name": feature.get("properties", {}).get("task_name", ""),
                                                "waypoints": waypoints,
                                                "goal_task_type": feature.get("properties", {}).get("goal_task_type", "0")
                                            }
                                            response["tasks"].append(task)
                                    logger.info(f"Fetched {len(response['tasks'])} tasks for race {race_id}")
                                else:
                                    response["tasks"] = []
                            else:
                                response["tasks"] = []
                                logger.debug(f"No tasks in response for race {race_id}")
                        else:
                            response["tasks"] = []
                            logger.debug(f"Tasks not found for race {race_id}, status: {resp.status}")
            except asyncio.TimeoutError:
                logger.warning(f"Local tasks endpoint timeout after 5 seconds, returning empty array")
                response["tasks"] = []
            except Exception as e:
                logger.debug(f"Could not fetch tasks: {e}")
                response["tasks"] = []
        
        await websocket.send_json(response)
        logger.info(f"Sent initial data with {len(response.get('flights', []))} flights to {client_id}")
        
    except Exception as e:
        logger.error(f"Error sending initial data: {e}")
        await websocket.send_json({
            "type": "error",
            "message": f"Failed to fetch initial data: {str(e)}"
        })
    finally:
        if 'db' in locals():
            db.close()