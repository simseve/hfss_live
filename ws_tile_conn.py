from fastapi import WebSocket
from starlette.websockets import WebSocketState
from typing import Dict, Set, List, Optional, Tuple, Any
import asyncio
import logging
from datetime import datetime, timezone, timedelta
import hashlib
import json
import gzip
import base64

logger = logging.getLogger(__name__)


class TileConnectionManager:
    def __init__(self):
        # Active connections by race_id
        self.active_connections: Dict[str, Set[WebSocket]] = {}
        
        # Track which tiles each client is viewing
        # Structure: {client_id: {race_id: set((z, x, y))}}
        self.client_viewports: Dict[str, Dict[str, Set[Tuple[int, int, int]]]] = {}
        
        # Track which clients are viewing each tile
        # Structure: {race_id: {(z, x, y): set(client_id)}}
        self.tile_subscribers: Dict[str, Dict[Tuple[int, int, int], Set[str]]] = {}
        
        # Cache of generated tiles with timestamps
        # Structure: {race_id: {(z, x, y): {"data": bytes, "timestamp": datetime, "hash": str}}}
        self.tile_cache: Dict[str, Dict[Tuple[int, int, int], Dict]] = {}
        
        # Track last update time for each tile
        # Structure: {race_id: {(z, x, y): datetime}}
        self.tile_last_update: Dict[str, Dict[Tuple[int, int, int], datetime]] = {}
        
        # Client WebSocket mapping for efficient lookups
        # Structure: {client_id: WebSocket}
        self.client_sockets: Dict[str, WebSocket] = {}
        
        # Track pilots with sent data to prevent duplicates
        # Structure: {race_id: {pilot_uuid: last_sent_time}}
        self.pilots_with_sent_data: Dict[str, Dict[str, datetime]] = {}
        
        # Track last GeoJSON update time per race
        # Structure: {race_id: datetime}
        self.last_geojson_update: Dict[str, datetime] = {}
        
        # Background task for broadcasting updates
        self.broadcast_tasks: Dict[str, asyncio.Task] = {}

    async def connect(self, websocket: WebSocket, race_id: str, client_id: str):
        """Connect a client to a specific race's tile updates"""
        # WebSocket already accepted in the route handler
        
        # Initialize race_id list if needed
        if race_id not in self.active_connections:
            self.active_connections[race_id] = set()
            self.tile_subscribers[race_id] = {}
            self.tile_cache[race_id] = {}
            self.tile_last_update[race_id] = {}
        
        # Add this connection to the race
        self.active_connections[race_id].add(websocket)
        self.client_sockets[client_id] = websocket
        
        # Initialize client viewport tracking
        if client_id not in self.client_viewports:
            self.client_viewports[client_id] = {}
        self.client_viewports[client_id][race_id] = set()
        
        # Send confirmation to the client
        await websocket.send_json({
            "type": "connection_status",
            "status": "connected",
            "race_id": race_id,
            "protocol": "tile-based",
            "active_viewers": len(self.active_connections[race_id])
        })
        
        logger.info(f"Client {client_id} connected to race {race_id} (tile-based)")
        
        # Start broadcast task for this race if not already running
        if race_id not in self.broadcast_tasks or self.broadcast_tasks[race_id].done():
            self.broadcast_tasks[race_id] = asyncio.create_task(
                self._broadcast_geojson_updates(race_id)
            )

    async def disconnect(self, websocket: WebSocket, client_id: str):
        """Disconnect a client from all subscribed races and tiles"""
        # Remove from all race connections
        for race_id in list(self.active_connections.keys()):
            if websocket in self.active_connections[race_id]:
                self.active_connections[race_id].remove(websocket)
                
                # Clean up empty race connections
                if len(self.active_connections[race_id]) == 0:
                    del self.active_connections[race_id]
                    # Clean up tile data for this race if no clients
                    if race_id in self.tile_cache:
                        del self.tile_cache[race_id]
                    if race_id in self.tile_last_update:
                        del self.tile_last_update[race_id]
        
        # Remove from tile subscriptions
        if client_id in self.client_viewports:
            for race_id, tiles in self.client_viewports[client_id].items():
                if race_id in self.tile_subscribers:
                    for tile in tiles:
                        if tile in self.tile_subscribers[race_id]:
                            self.tile_subscribers[race_id][tile].discard(client_id)
                            # Clean up empty tile subscriptions
                            if not self.tile_subscribers[race_id][tile]:
                                del self.tile_subscribers[race_id][tile]
            del self.client_viewports[client_id]
        
        # Remove from client sockets
        if client_id in self.client_sockets:
            del self.client_sockets[client_id]
        
        logger.info(f"Client {client_id} disconnected from tile-based system")
        
        # Stop broadcast task if no more clients
        for race_id in list(self.broadcast_tasks.keys()):
            if race_id not in self.active_connections or not self.active_connections[race_id]:
                if race_id in self.broadcast_tasks:
                    self.broadcast_tasks[race_id].cancel()
                    del self.broadcast_tasks[race_id]
                if race_id in self.last_geojson_update:
                    del self.last_geojson_update[race_id]

    async def update_client_viewport(self, client_id: str, race_id: str, 
                                    viewport_tiles: List[Tuple[int, int, int]]):
        """Update which tiles a client is viewing"""
        if client_id not in self.client_viewports:
            self.client_viewports[client_id] = {}
        
        old_tiles = self.client_viewports[client_id].get(race_id, set())
        new_tiles = set(viewport_tiles)
        
        # Find tiles to unsubscribe from
        tiles_to_remove = old_tiles - new_tiles
        for tile in tiles_to_remove:
            if race_id in self.tile_subscribers and tile in self.tile_subscribers[race_id]:
                self.tile_subscribers[race_id][tile].discard(client_id)
                if not self.tile_subscribers[race_id][tile]:
                    del self.tile_subscribers[race_id][tile]
        
        # Find tiles to subscribe to
        tiles_to_add = new_tiles - old_tiles
        for tile in tiles_to_add:
            if race_id not in self.tile_subscribers:
                self.tile_subscribers[race_id] = {}
            if tile not in self.tile_subscribers[race_id]:
                self.tile_subscribers[race_id][tile] = set()
            self.tile_subscribers[race_id][tile].add(client_id)
        
        # Update client's viewport
        self.client_viewports[client_id][race_id] = new_tiles
        
        logger.debug(f"Client {client_id} viewport updated: {len(new_tiles)} tiles, "
                    f"+{len(tiles_to_add)} -{len(tiles_to_remove)}")
        
        return {"added": list(tiles_to_add), "removed": list(tiles_to_remove)}

    async def _broadcast_geojson_updates(self, race_id: str):
        """Background task to broadcast GeoJSON updates every second with configurable delay"""
        from config import settings
        delay_seconds = settings.TRACKING_DELAY_SECONDS

        logger.info(f"Starting GeoJSON broadcast for race {race_id} with {delay_seconds}-second delay")

        # Initialize last update time to configured delay ago
        self.last_geojson_update[race_id] = datetime.now(timezone.utc) - timedelta(seconds=delay_seconds)
        
        while race_id in self.active_connections and self.active_connections[race_id]:
            try:
                from database.db_replica import get_read_db_with_fallback
                from database.models import Flight
                
                # Get database session
                db = next(get_read_db_with_fallback())
                
                try:
                    # Get active flights with configurable delay
                    delayed_time = datetime.now(timezone.utc) - timedelta(seconds=delay_seconds)
                    # Only get flights that have been active in the last 24 hours
                    cutoff_time = datetime.now(timezone.utc) - timedelta(hours=24)
                    
                    # Query flights directly - only recent ones
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
                            # Always keep the more recent flight based on created_at
                            if flight.created_at > pilot_flights[flight.pilot_id].created_at:
                                pilot_flights[flight.pilot_id] = flight
                    
                    # Use only the most recent flight for each pilot
                    flights = list(pilot_flights.values())
                    
                    updates = []
                    for flight in flights:
                        # For active flights, get the most recent point that's old enough to send
                        from database.models import LiveTrackPoint

                        # Get the most recent point that's older than the delay
                        delayed_point = db.query(LiveTrackPoint).filter(
                            LiveTrackPoint.flight_uuid == flight.id,
                            LiveTrackPoint.datetime <= delayed_time
                        ).order_by(LiveTrackPoint.datetime.desc()).first()

                        if delayed_point:
                            # Use the delayed point as our "current" position
                            delayed_fix = {
                                'lat': delayed_point.lat,
                                'lon': delayed_point.lon,
                                'elevation': delayed_point.elevation,
                                'datetime': delayed_point.datetime.isoformat()
                            }

                            # Calculate flight dynamics using utility
                            from utils.flight_dynamics import calculate_flight_dynamics

                            # Get recent points around the delayed point for calculations
                            recent_points = db.query(LiveTrackPoint).filter(
                                LiveTrackPoint.flight_uuid == flight.id,
                                LiveTrackPoint.datetime <= delayed_point.datetime
                            ).order_by(LiveTrackPoint.datetime.desc()).limit(5).all()

                            # Calculate dynamics with smoothed vario
                            dynamics = calculate_flight_dynamics(
                                recent_points=recent_points,
                                flight_state=flight.flight_state,
                                vario_smoothing=3  # Use 3 points for vario averaging
                            )

                            # Calculate flight time from first_fix to delayed point
                            flight_time = 0
                            if flight.first_fix:
                                first_time_str = flight.first_fix.get('datetime')
                                if first_time_str:
                                    from dateutil import parser
                                    first_time = parser.parse(first_time_str)
                                    flight_time = (delayed_point.datetime - first_time).total_seconds()

                            updates.append({
                                'pilot_id': flight.pilot_id,
                                'pilot_name': flight.pilot_name or 'Unknown',
                                'flight_id': str(flight.id),
                                'lat': float(delayed_fix['lat']),
                                'lon': float(delayed_fix['lon']),
                                'elevation': float(delayed_fix['elevation']),
                                'timestamp': delayed_fix['datetime'],
                                'speed': dynamics['speed'],
                                'heading': dynamics['heading'],
                                'vario': dynamics['vario'],
                                'flight_time': flight_time,  # in seconds
                                'source': flight.source,
                                'total_points': flight.total_points,
                                'flight_state': flight.flight_state.get('state', 'unknown') if flight.flight_state else 'unknown',
                                'flight_state_info': flight.flight_state if flight.flight_state else {},
                                'first_fix': flight.first_fix if flight.first_fix else None,
                                'last_fix': flight.last_fix if flight.last_fix else None,
                                'delay_applied': delay_seconds  # So frontend knows the delay
                            })
                    
                    else:
                        logger.debug(f"No updates to send for race {race_id} - all fixes too recent (< {delay_seconds}s old)")

                    if updates:
                        logger.info(f"Sending {len(updates)} delta updates for race {race_id}")
                        # Create delta update format expected by frontend
                        delta_data = {
                            'type': 'delta',
                            'timestamp': datetime.now(timezone.utc).isoformat(),
                            'updates': updates
                        }

                        # Compress the delta data
                        json_str = json.dumps(delta_data)
                        compressed = gzip.compress(json_str.encode('utf-8'), compresslevel=6)
                        
                        # Broadcast to all connected clients for this race
                        message = {
                            "type": "delta_update",
                            "race_id": race_id,
                            "data": base64.b64encode(compressed).decode('utf-8'),
                            "timestamp": delta_data['timestamp'],
                            "compression": "gzip",
                            "update_count": len(updates)
                        }
                        
                        await self.broadcast_to_race(race_id, message)
                        logger.debug(f"Broadcasted {len(updates)} pilot updates for race {race_id}")
                    
                    # Update last broadcast time (maintain configured delay)
                    self.last_geojson_update[race_id] = datetime.now(timezone.utc) - timedelta(seconds=delay_seconds)
                    
                finally:
                    db.close()
                
                # Wait 10 seconds before next update (reduce database load)
                await asyncio.sleep(10)
                
            except asyncio.CancelledError:
                logger.info(f"GeoJSON broadcast cancelled for race {race_id}")
                break
            except Exception as e:
                logger.error(f"Error in GeoJSON broadcast for race {race_id}: {e}")
                await asyncio.sleep(5)  # Wait longer on error
        
        logger.info(f"Stopped GeoJSON broadcast for race {race_id}")
    
    async def broadcast_to_race(self, race_id: str, message: Dict[str, Any]):
        """Broadcast a message to all clients connected to a race"""
        if race_id not in self.active_connections:
            logger.warning(f"No active connections for race {race_id}")
            return

        num_clients = len(self.active_connections[race_id])
        if num_clients == 0:
            logger.warning(f"Empty connection set for race {race_id}")
            return

        logger.debug(f"Broadcasting {message['type']} to {num_clients} clients for race {race_id}")

        disconnected = []
        sent_count = 0

        for websocket in self.active_connections[race_id]:
            try:
                if websocket.client_state == WebSocketState.CONNECTED:
                    await websocket.send_json(message)
                    sent_count += 1
                else:
                    disconnected.append(websocket)
            except Exception as e:
                logger.error(f"Error broadcasting to client: {e}")
                disconnected.append(websocket)
        
        # Clean up disconnected clients
        for ws in disconnected:
            self.active_connections[race_id].discard(ws)

        if sent_count > 0:
            logger.debug(f"Successfully sent {message['type']} to {sent_count}/{num_clients} clients")
        else:
            logger.warning(f"Failed to send {message['type']} to any clients for race {race_id}")
    
    async def send_tile_to_client(self, client_id: str, race_id: str, 
                                  tile_coords: Tuple[int, int, int], 
                                  tile_data: bytes, is_delta: bool = False):
        """Send a specific tile to a client"""
        if client_id not in self.client_sockets:
            return False
        
        websocket = self.client_sockets[client_id]
        z, x, y = tile_coords
        
        try:
            if websocket.client_state == WebSocketState.CONNECTED:
                # For binary MVT data, we'll send as base64 in JSON
                import base64
                await websocket.send_json({
                    "type": "tile_delta" if is_delta else "tile_data",
                    "race_id": race_id,
                    "tile": {"z": z, "x": x, "y": y},
                    "format": "mvt",
                    "data": base64.b64encode(tile_data).decode('utf-8'),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "is_delta": is_delta
                })
                return True
        except Exception as e:
            logger.error(f"Failed to send tile to client {client_id}: {str(e)}")
            return False
        
        return False

    async def broadcast_tile_update(self, race_id: str, tile_coords: Tuple[int, int, int], 
                                   tile_data: bytes, is_delta: bool = False):
        """Broadcast a tile update to all clients viewing that tile"""
        if race_id not in self.tile_subscribers:
            return 0
        
        if tile_coords not in self.tile_subscribers[race_id]:
            return 0
        
        clients = self.tile_subscribers[race_id][tile_coords].copy()
        sent_count = 0
        
        for client_id in clients:
            success = await self.send_tile_to_client(
                client_id, race_id, tile_coords, tile_data, is_delta
            )
            if success:
                sent_count += 1
        
        # Update cache and timestamp
        if race_id not in self.tile_cache:
            self.tile_cache[race_id] = {}
        
        # Store tile in cache with hash for change detection
        tile_hash = hashlib.md5(tile_data).hexdigest()
        self.tile_cache[race_id][tile_coords] = {
            "data": tile_data,
            "timestamp": datetime.now(timezone.utc),
            "hash": tile_hash
        }
        
        if race_id not in self.tile_last_update:
            self.tile_last_update[race_id] = {}
        self.tile_last_update[race_id][tile_coords] = datetime.now(timezone.utc)
        
        logger.debug(f"Broadcast tile {tile_coords} to {sent_count}/{len(clients)} clients")
        return sent_count

    async def request_tiles_for_client(self, client_id: str, race_id: str, 
                                      requested_tiles: List[Tuple[int, int, int]]):
        """Handle explicit tile requests from a client"""
        sent_tiles = []
        
        for tile_coords in requested_tiles:
            # Check if we have this tile in cache
            if (race_id in self.tile_cache and 
                tile_coords in self.tile_cache[race_id]):
                # Send cached tile
                cached_tile = self.tile_cache[race_id][tile_coords]
                success = await self.send_tile_to_client(
                    client_id, race_id, tile_coords, 
                    cached_tile["data"], is_delta=False
                )
                if success:
                    sent_tiles.append(tile_coords)
            else:
                # Tile not in cache, will need to generate
                # This will be handled by the tile generation service
                pass
        
        return sent_tiles

    def get_tiles_with_viewers(self, race_id: str) -> Set[Tuple[int, int, int]]:
        """Get all tiles that have at least one viewer"""
        if race_id not in self.tile_subscribers:
            return set()
        return set(self.tile_subscribers[race_id].keys())

    def get_active_zoom_levels(self, race_id: str) -> Set[int]:
        """Get all zoom levels being viewed for a race"""
        tiles = self.get_tiles_with_viewers(race_id)
        return {z for z, _, _ in tiles}

    def should_update_tile(self, race_id: str, tile_coords: Tuple[int, int, int], 
                          new_data: bytes) -> bool:
        """Check if tile data has changed and should be broadcast"""
        if race_id not in self.tile_cache or tile_coords not in self.tile_cache[race_id]:
            return True
        
        # Compare hash to detect changes
        new_hash = hashlib.md5(new_data).hexdigest()
        old_hash = self.tile_cache[race_id][tile_coords].get("hash", "")
        
        return new_hash != old_hash

    def get_cache_stats(self, race_id: str) -> Dict:
        """Get cache statistics for monitoring"""
        if race_id not in self.tile_cache:
            return {"cached_tiles": 0, "total_size": 0}
        
        total_size = sum(
            len(tile["data"]) 
            for tile in self.tile_cache[race_id].values()
        )
        
        return {
            "cached_tiles": len(self.tile_cache[race_id]),
            "total_size": total_size,
            "active_viewers": len(self.active_connections.get(race_id, [])),
            "tiles_with_viewers": len(self.get_tiles_with_viewers(race_id))
        }
    
    def get_active_viewers(self, race_id: str) -> int:
        """Get the number of active viewers for a race"""
        return len(self.active_connections.get(race_id, []))
    
    def add_pilot_with_sent_data(self, race_id: str, pilot_uuid: str, last_sent_time: datetime):
        """Track pilots that have had data sent to prevent duplicates"""
        if race_id not in self.pilots_with_sent_data:
            self.pilots_with_sent_data[race_id] = {}
        self.pilots_with_sent_data[race_id][pilot_uuid] = last_sent_time


# Create a global tile connection manager for the application
tile_manager = TileConnectionManager()