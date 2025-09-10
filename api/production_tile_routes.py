"""
Production-ready tile WebSocket endpoint
Optimized for hundreds of concurrent users with smooth 1-second interpolation
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from sqlalchemy.orm import Session
from database.db_replica import get_read_db_with_fallback
from database.models import Race
import logging
import jwt
from jwt.exceptions import PyJWTError
from config import settings
from datetime import datetime, timezone
import asyncio
import json
import gzip
import base64
from typing import Set
from ws_tile_conn import tile_manager
from services.production_tile_service import production_tile_service

logger = logging.getLogger(__name__)
router = APIRouter()

# Track connected clients for monitoring
connected_clients: Set[str] = set()


@router.websocket("/ws/live/{race_id}")
async def production_websocket_endpoint(
    websocket: WebSocket,
    race_id: str,
    client_id: str = Query(...),
    token: str = Query(...)
):
    """
    Production WebSocket endpoint for live tracking
    Optimized for hundreds of concurrent users
    """
    db = None
    
    try:
        # Verify token (copied from api/routes.py)
        try:
            token_data = jwt.decode(
                token,
                settings.SECRET_KEY,
                algorithms=["HS256"],
                audience="api.hikeandfly.app",
                issuer="hikeandfly.app",
                verify=True
            )

            if not token_data.get("sub", "").startswith("contest:"):
                await websocket.close(code=1008, reason="Invalid token")
                return

            token_race_id = token_data["sub"].split(":")[1]

            # Verify race_id matches token
            if race_id != token_race_id:
                await websocket.close(code=1008, reason="Token not valid for this race")
                return

        except (PyJWTError, jwt.ExpiredSignatureError) as e:
            logger.error(f"Token validation failed: {e}")
            await websocket.close(code=1008, reason="Invalid token")
            return

        # Accept connection
        await websocket.accept()
        connected_clients.add(client_id)
        
        try:
            # Add to tile manager for tracking
            await tile_manager.connect(websocket, race_id, client_id)
        except Exception as e:
            logger.error(f"Failed to add to tile manager: {e}")
            await websocket.close(code=1011, reason="Internal error")
            return
        
        # Get database session
        db = next(get_read_db_with_fallback())
        
        # Get race information
        race = db.query(Race).filter(Race.race_id == race_id).first()
        if not race:
            await websocket.send_json({
                "type": "error",
                "message": "Race not found"
            })
            await websocket.close(code=1008, reason="Race not found")
            return

        # Send initial metadata with interpolation settings
        await websocket.send_json({
            "type": "race_config",
            "race_id": race_id,
            "race_name": race.name,
            "timezone": race.timezone,
            "delay_seconds": 60,  # 60-second broadcast delay
            "update_interval": 10,  # New data every 10 seconds
            "interpolation_rate": 1,  # Update display every 1 second
            "protocol_version": "2.0",
            "features": {
                "delta_updates": True,
                "compressed_tiles": True,
                "clustering": True,
                "smooth_interpolation": True
            }
        })
        
        # Send current viewer count
        viewer_count = len(tile_manager.active_connections.get(race_id, []))
        await websocket.send_json({
            "type": "viewer_count",
            "count": viewer_count,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        
        # Main message handling loop
        last_heartbeat = datetime.now(timezone.utc)
        
        while True:
            try:
                # Wait for client messages with timeout for heartbeat
                try:
                    data = await asyncio.wait_for(websocket.receive_text(), timeout=30)
                    message = json.loads(data)
                except asyncio.TimeoutError:
                    # Send heartbeat
                    now = datetime.now(timezone.utc)
                    if (now - last_heartbeat).total_seconds() > 30:
                        await websocket.send_json({
                            "type": "heartbeat",
                            "timestamp": now.isoformat()
                        })
                        last_heartbeat = now
                    continue
                
                # Handle different message types
                message_type = message.get("type")
                
                if message_type == "ping":
                    # Simple ping/pong for latency measurement
                    await websocket.send_json({
                        "type": "pong",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "client_timestamp": message.get("timestamp")
                    })
                
                elif message_type == "viewport_update":
                    # Client updating their viewport
                    viewport = message.get("viewport", {})
                    
                    if "tiles" in viewport:
                        tiles = [tuple(t) for t in viewport["tiles"]]
                        
                        # Update viewport tracking
                        changes = await tile_manager.update_client_viewport(
                            client_id, race_id, tiles
                        )
                        
                        # Send tiles for newly visible areas
                        if changes["added"]:
                            tiles_sent = 0
                            for z, x, y in changes["added"]:
                                # Get tile from production service (already compressed)
                                tile_data = await production_tile_service.get_or_generate_tile(
                                    race_id, z, x, y, db
                                )
                                
                                if tile_data:
                                    # Send compressed tile
                                    await websocket.send_json({
                                        "type": "tile_data",
                                        "tile": {"z": z, "x": x, "y": y},
                                        "format": "mvt",
                                        "compression": "gzip",
                                        "data": base64.b64encode(tile_data).decode('utf-8'),
                                        "timestamp": datetime.now(timezone.utc).isoformat()
                                    })
                                    tiles_sent += 1
                            
                            logger.debug(f"Sent {tiles_sent} tiles to {client_id}")
                
                elif message_type == "request_initial_data":
                    # Client requesting initial data for smooth interpolation
                    zoom = message.get("zoom", 12)
                    bbox = message.get("bbox", [-180, -90, 180, 90])
                    
                    # Calculate tiles for bbox
                    tiles = production_tile_service.calculate_tiles_for_viewport(bbox, zoom)
                    
                    # Limit initial tiles
                    max_initial = 9  # 3x3 grid
                    tiles = tiles[:max_initial]
                    
                    # Send initial tiles
                    for z, x, y in tiles:
                        tile_data = await production_tile_service.get_or_generate_tile(
                            race_id, z, x, y, db
                        )
                        
                        if tile_data:
                            await websocket.send_json({
                                "type": "tile_data",
                                "tile": {"z": z, "x": x, "y": y},
                                "format": "mvt",
                                "compression": "gzip",
                                "data": base64.b64encode(tile_data).decode('utf-8'),
                                "timestamp": datetime.now(timezone.utc).isoformat()
                            })
                    
                    await websocket.send_json({
                        "type": "initial_data_complete",
                        "tiles_sent": len(tiles)
                    })
                
                elif message_type == "get_stats":
                    # Send performance statistics
                    stats = {
                        "viewers": len(tile_manager.active_connections.get(race_id, [])),
                        "tiles_cached": len(production_tile_service.tile_cache.get(race_id, {})),
                        "client_id": client_id,
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    }
                    
                    await websocket.send_json({
                        "type": "stats",
                        "data": stats
                    })
                
            except json.JSONDecodeError:
                await websocket.send_json({
                    "type": "error",
                    "message": "Invalid message format"
                })
            except WebSocketDisconnect:
                break
            except Exception as e:
                logger.error(f"Error handling message: {str(e)}")
                
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"WebSocket error for {client_id}: {str(e)}")
        try:
            await websocket.close(code=1011, reason="Server error")
        except:
            pass
    finally:
        # Cleanup
        connected_clients.discard(client_id)
        await tile_manager.disconnect(websocket, client_id)
        
        if db:
            try:
                db.close()
            except:
                pass
        
        logger.info(f"Client {client_id} disconnected. Active clients: {len(connected_clients)}")


@router.get("/stats")
async def get_live_stats():
    """Get current system statistics"""
    stats = {
        "total_connected_clients": len(connected_clients),
        "races_with_viewers": len(tile_manager.active_connections),
        "races": {}
    }
    
    for race_id, connections in tile_manager.active_connections.items():
        stats["races"][race_id] = {
            "viewers": len(connections),
            "tiles_with_viewers": len(tile_manager.get_tiles_with_viewers(race_id)),
            "cached_tiles": len(production_tile_service.tile_cache.get(race_id, {}))
        }
    
    return stats