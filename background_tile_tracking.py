from datetime import datetime, timezone, timedelta
from database.models import Flight, LiveTrackPoint, Race
import asyncio
from ws_tile_conn import tile_manager
from services.tile_generation_service import tile_service
from database.db_replica import ReplicaSession
import logging
from typing import Dict, Set, Tuple

logger = logging.getLogger(__name__)


async def tile_based_tracking_update(interval_seconds: int = 10):
    """
    Background task to send tile-based tracking updates to connected clients.
    More frequent than point-based updates since we're only sending changed tiles.
    """
    
    # Track last update time per race to generate deltas
    last_update_times: Dict[str, datetime] = {}
    
    while True:
        try:
            await asyncio.sleep(interval_seconds)
            
            # Get active races with connected clients in tile system
            active_races = list(tile_manager.active_connections.keys())
            
            if not active_races:
                continue
            
            for race_id in active_races:
                # Skip if no viewers
                if len(tile_manager.active_connections.get(race_id, [])) == 0:
                    continue
                
                # Get tiles that have active viewers
                watched_tiles = tile_manager.get_tiles_with_viewers(race_id)
                if not watched_tiles:
                    continue
                
                logger.debug(f"Processing {len(watched_tiles)} watched tiles for race {race_id}")
                
                # Get last update time for this race
                last_update = last_update_times.get(race_id, datetime.now(timezone.utc) - timedelta(seconds=interval_seconds))
                current_time = datetime.now(timezone.utc)
                
                # Use read-only DB session
                with ReplicaSession() as db:
                    # Check if there are new points since last update
                    new_points_query = (
                        db.query(LiveTrackPoint)
                        .join(Flight, Flight.id == LiveTrackPoint.flight_uuid)
                        .filter(
                            Flight.race_id == race_id,
                            LiveTrackPoint.datetime > last_update,
                            Flight.source.like('%live%')
                        )
                        .limit(1)
                        .first()
                    )
                    
                    if not new_points_query:
                        # No new data, skip this race
                        continue
                    
                    # Group tiles by zoom level for efficient processing
                    tiles_by_zoom: Dict[int, Set[Tuple[int, int]]] = {}
                    for z, x, y in watched_tiles:
                        if z not in tiles_by_zoom:
                            tiles_by_zoom[z] = set()
                        tiles_by_zoom[z].add((x, y))
                    
                    # Process each zoom level
                    tiles_updated = 0
                    for zoom, xy_tiles in tiles_by_zoom.items():
                        for x, y in xy_tiles:
                            try:
                                # Generate tile with new data
                                tile_data = await tile_service.generate_live_tile(
                                    race_id, zoom, x, y, db, since_timestamp=last_update
                                )
                                
                                if tile_data and len(tile_data) > 0:
                                    # Check if tile has actually changed
                                    if tile_manager.should_update_tile(race_id, (zoom, x, y), tile_data):
                                        # Broadcast to all viewers of this tile
                                        sent_count = await tile_manager.broadcast_tile_update(
                                            race_id, (zoom, x, y), tile_data, is_delta=False
                                        )
                                        if sent_count > 0:
                                            tiles_updated += 1
                                
                            except Exception as e:
                                logger.error(f"Error updating tile {zoom}/{x}/{y}: {str(e)}")
                    
                    if tiles_updated > 0:
                        logger.info(f"Updated {tiles_updated} tiles for race {race_id}")
                
                # Update last processed time for this race
                last_update_times[race_id] = current_time
                
                # Clean up old races from tracking
                if race_id not in tile_manager.active_connections:
                    del last_update_times[race_id]
                    
        except Exception as e:
            logger.error(f"Error in tile-based tracking update: {str(e)}")


async def tile_cache_cleanup(interval_seconds: int = 300):
    """
    Periodic cleanup of tile cache to prevent memory bloat.
    Runs every 5 minutes by default.
    """
    while True:
        try:
            await asyncio.sleep(interval_seconds)
            
            # Clean up in-memory cache for inactive races
            for race_id in list(tile_manager.tile_cache.keys()):
                if race_id not in tile_manager.active_connections:
                    # No active connections, clear cache
                    del tile_manager.tile_cache[race_id]
                    if race_id in tile_manager.tile_last_update:
                        del tile_manager.tile_last_update[race_id]
                    logger.info(f"Cleaned up tile cache for inactive race {race_id}")
                else:
                    # Remove old tiles from cache
                    cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=10)
                    tiles_to_remove = []
                    
                    for tile_coords, tile_data in tile_manager.tile_cache[race_id].items():
                        if tile_data["timestamp"] < cutoff_time:
                            # Check if tile still has viewers
                            if (race_id in tile_manager.tile_subscribers and 
                                tile_coords not in tile_manager.tile_subscribers[race_id]):
                                tiles_to_remove.append(tile_coords)
                    
                    for tile_coords in tiles_to_remove:
                        del tile_manager.tile_cache[race_id][tile_coords]
                    
                    if tiles_to_remove:
                        logger.debug(f"Removed {len(tiles_to_remove)} old tiles from cache for race {race_id}")
                        
        except Exception as e:
            logger.error(f"Error in tile cache cleanup: {str(e)}")


async def tile_pregenerator(interval_seconds: int = 60):
    """
    Pre-generate popular tiles for active races to improve response times.
    Runs every minute by default.
    """
    # Popular zoom levels to pre-generate
    popular_zooms = [10, 11, 12, 13, 14]
    
    while True:
        try:
            await asyncio.sleep(interval_seconds)
            
            # Only pre-generate for races with active viewers
            active_races = [
                race_id for race_id in tile_manager.active_connections.keys()
                if len(tile_manager.active_connections[race_id]) > 0
            ]
            
            if not active_races:
                continue
            
            with ReplicaSession() as db:
                for race_id in active_races:
                    try:
                        # Get active zoom levels being viewed
                        active_zooms = tile_manager.get_active_zoom_levels(race_id)
                        
                        # Pre-generate tiles for zoom levels near what's being viewed
                        zooms_to_generate = set()
                        for z in active_zooms:
                            # Add adjacent zoom levels
                            if z - 1 >= 8:
                                zooms_to_generate.add(z - 1)
                            zooms_to_generate.add(z)
                            if z + 1 <= 16:
                                zooms_to_generate.add(z + 1)
                        
                        # Find tiles with data for these zoom levels
                        tiles_with_data = await tile_service.get_tiles_with_data(
                            race_id, list(zooms_to_generate), db
                        )
                        
                        tiles_generated = 0
                        for zoom, xy_tiles in tiles_with_data.items():
                            # Limit pre-generation to prevent overload
                            max_tiles_per_zoom = 50
                            for x, y in list(xy_tiles)[:max_tiles_per_zoom]:
                                # Check if tile is already cached
                                cached = await tile_service.get_cached_tile(race_id, zoom, x, y)
                                if not cached:
                                    # Generate and cache the tile
                                    tile_data = await tile_service.generate_live_tile(
                                        race_id, zoom, x, y, db
                                    )
                                    if tile_data:
                                        await tile_service.cache_tile(race_id, zoom, x, y, tile_data)
                                        tiles_generated += 1
                        
                        if tiles_generated > 0:
                            logger.info(f"Pre-generated {tiles_generated} tiles for race {race_id}")
                            
                    except Exception as e:
                        logger.error(f"Error pre-generating tiles for race {race_id}: {str(e)}")
                        
        except Exception as e:
            logger.error(f"Error in tile pre-generator: {str(e)}")


# Start all tile-based background tasks
async def start_tile_background_tasks():
    """Start all tile-based background tasks"""
    # Initialize tile service
    await tile_service.initialize()
    
    # Create tasks
    tasks = [
        asyncio.create_task(tile_based_tracking_update(interval_seconds=10)),
        asyncio.create_task(tile_cache_cleanup(interval_seconds=300)),
        asyncio.create_task(tile_pregenerator(interval_seconds=60))
    ]
    
    logger.info("Started tile-based background tracking tasks")
    
    # Keep tasks running
    await asyncio.gather(*tasks)