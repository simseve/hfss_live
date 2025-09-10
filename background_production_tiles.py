"""
Production background service for tile generation
Pre-generates tiles for active viewing areas and broadcasts updates efficiently
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Set, Tuple
from database.db_replica import ReplicaSession
from ws_tile_conn import tile_manager
from services.production_tile_service import production_tile_service
import gzip
import base64
import json

logger = logging.getLogger(__name__)


class TileBroadcastManager:
    """Manages efficient broadcasting of tile updates to hundreds of users"""
    
    def __init__(self):
        # Track which tiles are being viewed by zoom level
        self.active_tiles_by_zoom: Dict[str, Dict[int, Set[Tuple[int, int]]]] = {}
        
        # Track last update time for delta calculations
        self.last_update_time: Dict[str, datetime] = {}
        
        # Pre-generation configuration
        self.pregenerate_zoom_levels = [8, 10, 12, 14]  # Common viewing levels
        self.max_tiles_per_zoom = 100  # Limit to prevent overload
        
    async def update_active_tiles(self):
        """Update list of tiles being actively viewed"""
        for race_id in tile_manager.active_connections.keys():
            if race_id not in self.active_tiles_by_zoom:
                self.active_tiles_by_zoom[race_id] = {}
            
            # Get all tiles being viewed
            viewed_tiles = tile_manager.get_tiles_with_viewers(race_id)
            
            # Group by zoom level
            tiles_by_zoom = {}
            for z, x, y in viewed_tiles:
                if z not in tiles_by_zoom:
                    tiles_by_zoom[z] = set()
                tiles_by_zoom[z].add((x, y))
            
            self.active_tiles_by_zoom[race_id] = tiles_by_zoom

    async def broadcast_tile_updates(self):
        """
        Main update loop - runs every 10 seconds
        Generates and broadcasts tile updates to all connected clients
        """
        while True:
            try:
                await asyncio.sleep(10)  # Update every 10 seconds
                
                # Update active tiles list
                await self.update_active_tiles()
                
                # Process each active race
                for race_id in self.active_tiles_by_zoom.keys():
                    await self.process_race_updates(race_id)
                    
            except Exception as e:
                logger.error(f"Error in tile broadcast loop: {str(e)}")
                await asyncio.sleep(1)  # Brief pause on error

    async def process_race_updates(self, race_id: str):
        """Process updates for a single race"""
        try:
            viewer_count = len(tile_manager.active_connections.get(race_id, []))
            if viewer_count == 0:
                return
                
            logger.debug(f"Processing updates for race {race_id} ({viewer_count} viewers)")
            
            with ReplicaSession() as db:
                # Get last update time
                last_update = self.last_update_time.get(
                    race_id, 
                    datetime.now(timezone.utc) - timedelta(seconds=10)
                )
                
                # Option 1: Send delta updates for efficiency
                if race_id in self.last_update_time:
                    await self.send_delta_updates(race_id, last_update, db)
                
                # Option 2: Send full tiles for new connections or every minute
                time_since_full = (datetime.now(timezone.utc) - last_update).total_seconds()
                if time_since_full > 60 or race_id not in self.last_update_time:
                    await self.send_full_tiles(race_id, db)
                
                # Update last update time
                self.last_update_time[race_id] = datetime.now(timezone.utc)
                
        except Exception as e:
            logger.error(f"Error processing race {race_id}: {str(e)}")

    async def send_delta_updates(self, race_id: str, since: datetime, db):
        """Send only position updates since last check"""
        try:
            # Get movement deltas
            delta_data = await production_tile_service.get_movement_delta(
                race_id, [], since, db
            )
            
            if delta_data["updates"]:
                # Compress delta data
                delta_json = json.dumps(delta_data).encode('utf-8')
                compressed = gzip.compress(delta_json, compresslevel=6)
                
                # Broadcast to all viewers
                message = {
                    "type": "delta_update",
                    "race_id": race_id,
                    "data": base64.b64encode(compressed).decode('utf-8'),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "compression": "gzip",
                    "update_count": len(delta_data["updates"])
                }
                
                # Send to all connected clients
                for websocket in tile_manager.active_connections.get(race_id, []):
                    try:
                        await websocket.send_json(message)
                    except Exception as e:
                        logger.error(f"Failed to send delta to client: {e}")
                
                logger.info(f"Sent delta with {len(delta_data['updates'])} updates to race {race_id}")
                
        except Exception as e:
            logger.error(f"Error sending delta updates: {str(e)}")

    async def send_full_tiles(self, race_id: str, db):
        """Send full tile updates for all viewed tiles"""
        try:
            tiles_by_zoom = self.active_tiles_by_zoom.get(race_id, {})
            tiles_sent = 0
            
            for zoom, xy_tiles in tiles_by_zoom.items():
                for x, y in list(xy_tiles)[:self.max_tiles_per_zoom]:
                    # Get or generate tile
                    tile_data = await production_tile_service.get_or_generate_tile(
                        race_id, zoom, x, y, db
                    )
                    
                    if tile_data and len(tile_data) > 0:
                        # Tile is already compressed from production service
                        sent_count = await tile_manager.broadcast_tile_update(
                            race_id, (zoom, x, y), tile_data, is_delta=False
                        )
                        if sent_count > 0:
                            tiles_sent += 1
            
            if tiles_sent > 0:
                logger.info(f"Sent {tiles_sent} full tiles for race {race_id}")
                
        except Exception as e:
            logger.error(f"Error sending full tiles: {str(e)}")

    async def pregenerate_popular_tiles(self):
        """
        Pre-generate tiles for common zoom levels
        Runs every minute to keep cache warm
        """
        while True:
            try:
                await asyncio.sleep(60)  # Run every minute
                
                with ReplicaSession() as db:
                    for race_id in self.active_tiles_by_zoom.keys():
                        # Pre-generate tiles for common zoom levels
                        for zoom in self.pregenerate_zoom_levels:
                            # Calculate which tiles contain data
                            tiles_with_data = await production_tile_service.get_tiles_with_data(
                                race_id, [zoom], db
                            )
                            
                            # Pre-generate up to max_tiles_per_zoom
                            tiles_generated = 0
                            for tile_coords in tiles_with_data.get(zoom, []):
                                if tiles_generated >= self.max_tiles_per_zoom:
                                    break
                                    
                                x, y = tile_coords
                                # This will cache the tile
                                await production_tile_service.get_or_generate_tile(
                                    race_id, zoom, x, y, db
                                )
                                tiles_generated += 1
                            
                            if tiles_generated > 0:
                                logger.debug(f"Pre-generated {tiles_generated} tiles at zoom {zoom} for race {race_id}")
                                
            except Exception as e:
                logger.error(f"Error in tile pre-generation: {str(e)}")

    async def cleanup_inactive_races(self):
        """Clean up data for races with no viewers"""
        while True:
            try:
                await asyncio.sleep(300)  # Every 5 minutes
                
                # Find inactive races
                inactive_races = []
                for race_id in self.last_update_time.keys():
                    if race_id not in tile_manager.active_connections:
                        inactive_races.append(race_id)
                
                # Clean up
                for race_id in inactive_races:
                    del self.last_update_time[race_id]
                    if race_id in self.active_tiles_by_zoom:
                        del self.active_tiles_by_zoom[race_id]
                    logger.info(f"Cleaned up inactive race {race_id}")
                
                # Also trigger tile cache cleanup
                await production_tile_service.cleanup_old_tiles()
                
            except Exception as e:
                logger.error(f"Error in cleanup: {str(e)}")


# Global instance
broadcast_manager = TileBroadcastManager()


async def start_production_tile_system():
    """Start all production tile system tasks"""
    # Initialize production tile service
    await production_tile_service.initialize()
    
    # Start all background tasks
    tasks = [
        asyncio.create_task(broadcast_manager.broadcast_tile_updates()),
        asyncio.create_task(broadcast_manager.pregenerate_popular_tiles()),
        asyncio.create_task(broadcast_manager.cleanup_inactive_races()),
    ]
    
    logger.info("Started production tile system with delta updates")
    
    # Keep tasks running
    await asyncio.gather(*tasks)


# For integration with existing app
async def production_tile_updates():
    """Entry point for app.py integration"""
    try:
        await start_production_tile_system()
    except Exception as e:
        logger.error(f"Production tile system error: {str(e)}")