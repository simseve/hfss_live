from fastapi import WebSocket
from starlette.websockets import WebSocketState
from typing import Dict, Set, List, Optional, Tuple
import asyncio
import logging
from datetime import datetime, timezone
import hashlib

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


# Create a global tile connection manager for the application
tile_manager = TileConnectionManager()