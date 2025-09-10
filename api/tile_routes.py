from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, Depends
from sqlalchemy.orm import Session
from database.db_replica import get_read_db_with_fallback, get_replica_db
from database.models import Race, Flight
import logging
import jwt
from jwt.exceptions import PyJWTError
from config import settings
from datetime import datetime, timezone
import asyncio
import json
from typing import List, Tuple, Optional
from ws_tile_conn import tile_manager
from services.tile_generation_service import tile_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws/tiles/{race_id}")
async def websocket_tile_tracking_endpoint(
    websocket: WebSocket,
    race_id: str,
    client_id: str = Query(...),
    token: str = Query(...)
):
    """WebSocket endpoint for tile-based real-time tracking updates"""
    db = None
    try:
        # Verify token (same as existing WebSocket)
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
            await websocket.close(code=1008, reason="Invalid token")
            return

        # Connect this client to the tile-based system
        await tile_manager.connect(websocket, race_id, client_id)
        
        # Initialize tile service if needed
        if not tile_service.redis_client:
            await tile_service.initialize()

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

        # Send initial race metadata
        await websocket.send_json({
            "type": "race_metadata",
            "race_id": race_id,
            "race_name": race.name,
            "timezone": race.timezone,
            "bounds": {
                # You can calculate actual bounds from data or use defaults
                "min_lat": -90,
                "max_lat": 90,
                "min_lon": -180,
                "max_lon": 180
            }
        })

        # Keep connection alive and handle client messages
        while True:
            try:
                # Wait for messages with timeout
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30)

                try:
                    message = json.loads(data)
                    message_type = message.get("type")

                    if message_type == "ping":
                        await websocket.send_json({
                            "type": "pong",
                            "timestamp": datetime.now(timezone.utc).isoformat()
                        })

                    elif message_type == "viewport_update":
                        # Client is updating their viewport
                        viewport = message.get("viewport", {})
                        
                        if "tiles" in viewport:
                            # Update which tiles the client is viewing
                            tiles = [tuple(t) for t in viewport["tiles"]]  # Convert to tuples
                            changes = await tile_manager.update_client_viewport(
                                client_id, race_id, tiles
                            )
                            
                            # Send newly requested tiles from cache or generate them
                            if changes["added"]:
                                # Generate/fetch tiles for newly visible areas
                                generated = await tile_service.generate_tile_batch(
                                    race_id, changes["added"], db
                                )
                                
                                for tile_coords, tile_data in generated.items():
                                    await tile_manager.send_tile_to_client(
                                        client_id, race_id, tile_coords, tile_data
                                    )
                            
                            # Send viewport update confirmation
                            await websocket.send_json({
                                "type": "viewport_updated",
                                "added_tiles": len(changes["added"]),
                                "removed_tiles": len(changes["removed"]),
                                "total_tiles": len(tiles)
                            })

                    elif message_type == "request_tiles":
                        # Explicit request for specific tiles
                        requested_tiles = message.get("tiles", [])
                        tiles = [tuple(t) for t in requested_tiles]
                        
                        # Generate/fetch requested tiles
                        generated = await tile_service.generate_tile_batch(
                            race_id, tiles, db
                        )
                        
                        for tile_coords, tile_data in generated.items():
                            await tile_manager.send_tile_to_client(
                                client_id, race_id, tile_coords, tile_data
                            )

                    elif message_type == "get_initial_tiles":
                        # Client requesting initial set of tiles for their viewport
                        zoom = message.get("zoom", 10)
                        bbox = message.get("bbox")
                        
                        if bbox:
                            # Calculate tiles for the bounding box
                            tiles = tile_service.calculate_tiles_for_viewport(bbox, zoom)
                            
                            # Limit initial tiles to prevent overload
                            max_initial_tiles = 25
                            if len(tiles) > max_initial_tiles:
                                # Take center tiles only
                                tiles = tiles[:max_initial_tiles]
                            
                            # Generate/fetch tiles
                            generated = await tile_service.generate_tile_batch(
                                race_id, tiles, db
                            )
                            
                            for tile_coords, tile_data in generated.items():
                                await tile_manager.send_tile_to_client(
                                    client_id, race_id, tile_coords, tile_data
                                )
                            
                            await websocket.send_json({
                                "type": "initial_tiles_sent",
                                "count": len(generated),
                                "zoom": zoom
                            })

                    elif message_type == "get_cache_stats":
                        # Debug endpoint to get cache statistics
                        stats = tile_manager.get_cache_stats(race_id)
                        await websocket.send_json({
                            "type": "cache_stats",
                            "stats": stats
                        })

                except json.JSONDecodeError:
                    await websocket.send_json({
                        "type": "error",
                        "message": "Invalid message format"
                    })

            except asyncio.TimeoutError:
                # Send heartbeat to check connection
                try:
                    await websocket.send_json({
                        "type": "heartbeat",
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    })
                except Exception:
                    logger.warning(f"Connection to client {client_id} timed out")
                    break

    except WebSocketDisconnect:
        await tile_manager.disconnect(websocket, client_id)
        logger.info(f"Client {client_id} disconnected from tile-based WebSocket")
    except Exception as e:
        logger.error(f"Tile WebSocket error: {str(e)}")
        try:
            await websocket.close(code=1011, reason="Server error")
        except:
            pass
        await tile_manager.disconnect(websocket, client_id)
    finally:
        # Close database session
        if db:
            try:
                db.close()
            except:
                pass


@router.get("/tiles/info/{race_id}")
async def get_tile_info(
    race_id: str,
    zoom: int = Query(10, ge=0, le=20),
    db: Session = Depends(get_replica_db)
):
    """Get information about tiles with data for a race at specific zoom level"""
    try:
        # Find tiles that contain data
        tiles_with_data = await tile_service.get_tiles_with_data(
            race_id, [zoom], db
        )
        
        return {
            "race_id": race_id,
            "zoom": zoom,
            "tiles_with_data": list(tiles_with_data.get(zoom, [])),
            "tile_count": len(tiles_with_data.get(zoom, []))
        }
    except Exception as e:
        logger.error(f"Error getting tile info: {str(e)}")
        return {
            "error": str(e),
            "tiles_with_data": [],
            "tile_count": 0
        }

@router.get("/tiles/debug/{race_id}")
async def debug_race_data(
    race_id: str,
    db: Session = Depends(get_replica_db)
):
    """Debug endpoint to check what data exists for a race"""
    try:
        from sqlalchemy import text
        
        # Check if race exists
        result = db.execute(text("""
            SELECT race_id, name, timezone 
            FROM races 
            WHERE race_id = :race_id
        """), {"race_id": race_id})
        race = result.fetchone()
        
        # Check flights
        result = db.execute(text("""
            SELECT COUNT(*) as count, 
                   MIN(created_at) as first,
                   MAX(created_at) as last,
                   array_agg(DISTINCT source) as sources
            FROM flights 
            WHERE race_id = :race_id
        """), {"race_id": race_id})
        flights = result.fetchone()
        
        # Check live points with bounds
        result = db.execute(text("""
            SELECT COUNT(*) as count,
                   MIN(ltp.datetime) as first,
                   MAX(ltp.datetime) as last,
                   MIN(ltp.lat) as min_lat,
                   MAX(ltp.lat) as max_lat,
                   MIN(ltp.lon) as min_lon,
                   MAX(ltp.lon) as max_lon,
                   COUNT(DISTINCT ltp.flight_uuid) as flight_count
            FROM live_track_points ltp
            JOIN flights f ON f.id = ltp.flight_uuid
            WHERE f.race_id = :race_id
        """), {"race_id": race_id})
        points = result.fetchone()
        
        # Check points in Brazil area specifically
        result = db.execute(text("""
            SELECT COUNT(*) as brazil_count
            FROM live_track_points ltp
            JOIN flights f ON f.id = ltp.flight_uuid
            WHERE f.race_id = :race_id
            AND ltp.lat BETWEEN -25 AND -15
            AND ltp.lon BETWEEN -45 AND -35
        """), {"race_id": race_id})
        brazil = result.fetchone()
        
        return {
            "race": {
                "exists": race is not None,
                "name": race.name if race else None,
                "timezone": race.timezone if race else None
            },
            "flights": {
                "count": flights.count if flights else 0,
                "first": str(flights.first) if flights and flights.first else None,
                "last": str(flights.last) if flights and flights.last else None,
                "sources": flights.sources if flights else []
            },
            "points": {
                "total": points.count if points else 0,
                "flights": points.flight_count if points else 0,
                "time_range": {
                    "first": str(points.first) if points and points.first else None,
                    "last": str(points.last) if points and points.last else None
                },
                "bounds": {
                    "min_lat": float(points.min_lat) if points and points.min_lat else None,
                    "max_lat": float(points.max_lat) if points and points.max_lat else None,
                    "min_lon": float(points.min_lon) if points and points.min_lon else None,
                    "max_lon": float(points.max_lon) if points and points.max_lon else None
                },
                "brazil_area_count": brazil.brazil_count if brazil else 0
            }
        }
    except Exception as e:
        return {"error": str(e)}

@router.get("/tiles/simple/{race_id}/{z}/{x}/{y}")
async def test_simple_tile(
    race_id: str,
    z: int,
    x: int, 
    y: int,
    db: Session = Depends(get_replica_db)
):
    """Test endpoint for simple tile generation"""
    try:
        from services.simple_tile_service import generate_simple_tile
        
        tile_data = await generate_simple_tile(
            race_id, z, x, y, db, delay_seconds=60
        )
        
        return {
            "success": True,
            "tile": f"{z}/{x}/{y}",
            "race_id": race_id,
            "size": len(tile_data),
            "is_empty": len(tile_data) == 0,
            "first_bytes": tile_data[:20].hex() if len(tile_data) > 0 else None,
            "is_mvt": len(tile_data) > 0 and tile_data[0] == 0x1a
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "tile": f"{z}/{x}/{y}",
            "race_id": race_id
        }

@router.get("/tiles/test/{race_id}/{z}/{x}/{y}")
async def test_tile_generation(
    race_id: str,
    z: int,
    x: int, 
    y: int,
    db: Session = Depends(get_replica_db)
):
    """Test endpoint to directly generate a tile and see what happens"""
    try:
        # Initialize tile service if needed
        if not tile_service.redis_client:
            await tile_service.initialize()
            
        # Try to generate the tile
        tile_data = await tile_service.generate_live_tile(
            race_id, z, x, y, db, delay_seconds=60
        )
        
        return {
            "success": True,
            "tile": f"{z}/{x}/{y}",
            "race_id": race_id,
            "size": len(tile_data),
            "is_empty": len(tile_data) == 0,
            "first_bytes": tile_data[:20].hex() if len(tile_data) > 0 else None
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "tile": f"{z}/{x}/{y}",
            "race_id": race_id
        }