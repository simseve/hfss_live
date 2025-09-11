"""
Production-ready tile service for hundreds of concurrent users
Optimized for live tracking with 60-second delay and smooth interpolation
"""

import logging
import asyncio
import hashlib
import gzip
import json
from typing import Dict, List, Optional, Tuple, Set
from datetime import datetime, timezone, timedelta
import redis.asyncio as redis
from sqlalchemy import text
from sqlalchemy.orm import Session
from config import settings

logger = logging.getLogger(__name__)


class ProductionTileService:
    def __init__(self):
        self.redis_client: Optional[redis.Redis] = None
        self.delay_seconds = 60  # Fixed 60-second delay for broadcast-style viewing
        self.update_interval = 10  # Generate new tiles every 10 seconds
        
        # Zoom-based configuration
        self.zoom_config = {
            # zoom: (cluster_distance_degrees, max_points, simplify_tolerance)
            6:  (1.0,    10,  0.1),     # World level - very clustered
            8:  (0.5,    20,  0.05),    # Country level
            10: (0.1,    50,  0.01),    # Region level
            12: (0.05,   100, 0.005),   # City level
            14: (0.01,   200, 0.001),   # District level
            16: (0.005,  500, 0.0005),  # Street level
            18: (0.001,  1000, 0.0001), # Building level
        }
        
        # Tile cache (shared by all users)
        self.tile_cache: Dict[str, Dict[Tuple[int, int, int], bytes]] = {}
        self.tile_timestamps: Dict[str, Dict[Tuple[int, int, int], datetime]] = {}
        
    async def initialize(self):
        """Initialize Redis for distributed caching"""
        try:
            redis_url = settings.get_redis_url()
            self.redis_client = await redis.from_url(
                redis_url,
                encoding="utf-8",
                decode_responses=False
            )
            await self.redis_client.ping()
            logger.info(f"Production tile service initialized with Redis")
        except Exception as e:
            logger.warning(f"Redis not available: {str(e)}")
            self.redis_client = None

    async def generate_tile_for_zoom(self, race_id: str, z: int, x: int, y: int, 
                                     db: Session) -> bytes:
        """
        Generate an optimized tile based on zoom level
        Returns compressed MVT data
        """
        try:
            # Get configuration for this zoom level
            if z not in self.zoom_config:
                # Use closest zoom level config
                z_key = min(self.zoom_config.keys(), key=lambda k: abs(k - z))
            else:
                z_key = z
                
            cluster_distance, max_points, simplify_tolerance = self.zoom_config[z_key]
            
            # Calculate delayed timestamp (60 seconds behind real-time)
            delayed_time = datetime.now(timezone.utc) - timedelta(seconds=self.delay_seconds)
            
            # Production query with optimizations
            query = text("""
                WITH 
                -- Get recent flights with 60-second delay
                recent_flights AS (
                    SELECT DISTINCT ON (f.pilot_id)
                        f.id as flight_uuid,
                        f.pilot_id,
                        f.pilot_name,
                        (f.last_fix->>'lat')::float as lat,
                        (f.last_fix->>'lon')::float as lon,
                        (f.last_fix->>'elevation')::float as elevation,
                        f.last_fix->>'datetime' as last_update,
                        (('x' || substr(md5(f.pilot_id), 1, 6))::bit(24)::int % 10) as color_index
                    FROM flights f
                    WHERE f.race_id = :race_id
                    AND f.source LIKE '%live%'
                    AND f.last_fix IS NOT NULL
                    -- Relaxed time filter: show pilots from last 24 hours with delay
                    AND f.last_fix->>'datetime' <= :delayed_time_str
                    AND f.last_fix->>'datetime' > :cutoff_time_str
                    ORDER BY f.pilot_id, f.created_at DESC
                ),
                -- Calculate movement vectors for interpolation
                positions_with_movement AS (
                    SELECT 
                        rf.*,
                        -- Get previous position for this pilot
                        LAG(rf.lat) OVER (PARTITION BY rf.pilot_id ORDER BY rf.last_update) as prev_lat,
                        LAG(rf.lon) OVER (PARTITION BY rf.pilot_id ORDER BY rf.last_update) as prev_lon,
                        LAG(rf.last_update) OVER (PARTITION BY rf.pilot_id ORDER BY rf.last_update) as prev_time
                    FROM recent_flights rf
                ),
                -- Calculate speed and heading
                positions_with_vectors AS (
                    SELECT 
                        *,
                        CASE 
                            WHEN prev_lat IS NOT NULL AND prev_lon IS NOT NULL AND prev_time IS NOT NULL THEN
                                ST_Distance(
                                    ST_MakePoint(prev_lon, prev_lat)::geography,
                                    ST_MakePoint(lon, lat)::geography
                                ) / GREATEST(
                                    EXTRACT(EPOCH FROM (last_update::timestamp - prev_time::timestamp)),
                                    1
                                )
                            ELSE 0
                        END as speed_ms,
                        CASE 
                            WHEN prev_lat IS NOT NULL AND prev_lon IS NOT NULL THEN
                                DEGREES(ST_Azimuth(
                                    ST_MakePoint(prev_lon, prev_lat)::geography,
                                    ST_MakePoint(lon, lat)::geography
                                ))
                            ELSE 0
                        END as heading
                    FROM positions_with_movement
                ),
                -- Get historical paths (simplified based on zoom)
                historical_paths AS (
                    SELECT 
                        pv.flight_uuid,
                        pv.pilot_id,
                        pv.pilot_name,
                        pv.color_index,
                        CASE 
                            WHEN :z <= 8 THEN
                                -- Very simplified for low zoom
                                ST_SimplifyPreserveTopology(
                                    ST_MakeLine(
                                        ARRAY(
                                            SELECT ST_SetSRID(ST_MakePoint(lon, lat), 4326)
                                            FROM (
                                                SELECT ltp.lon, ltp.lat
                                                FROM live_track_points ltp
                                                WHERE ltp.flight_uuid = pv.flight_uuid
                                                AND ltp.datetime <= :delayed_time
                                                AND ltp.datetime > :delayed_time - INTERVAL '30 minutes'
                                                ORDER BY ltp.datetime
                                                LIMIT 10
                                            ) pts
                                        )
                                    ),
                                    0.01
                                )
                            WHEN :z <= 12 THEN
                                -- Moderate simplification
                                ST_SimplifyPreserveTopology(
                                    ST_MakeLine(
                                        ARRAY(
                                            SELECT ST_SetSRID(ST_MakePoint(lon, lat), 4326)
                                            FROM (
                                                SELECT ltp.lon, ltp.lat
                                                FROM live_track_points ltp
                                                WHERE ltp.flight_uuid = pv.flight_uuid
                                                AND ltp.datetime <= :delayed_time
                                                AND ltp.datetime > :delayed_time - INTERVAL '30 minutes'
                                                ORDER BY ltp.datetime
                                                LIMIT 50
                                            ) pts
                                        )
                                    ),
                                    0.005
                                )
                            ELSE
                                -- Detailed path for high zoom
                                ST_SimplifyPreserveTopology(
                                    ST_MakeLine(
                                        ARRAY(
                                            SELECT ST_SetSRID(ST_MakePoint(lon, lat), 4326)
                                            FROM (
                                                SELECT ltp.lon, ltp.lat
                                                FROM live_track_points ltp
                                                WHERE ltp.flight_uuid = pv.flight_uuid
                                                AND ltp.datetime <= :delayed_time
                                                AND ltp.datetime > :delayed_time - INTERVAL '30 minutes'
                                                ORDER BY ltp.datetime
                                                LIMIT 200
                                            ) pts
                                        )
                                    ),
                                    0.001
                                )
                        END as path_geom
                    FROM positions_with_vectors pv
                    WHERE EXISTS (
                        SELECT 1 FROM live_track_points ltp
                        WHERE ltp.flight_uuid = pv.flight_uuid
                        AND ltp.datetime > :delayed_time - INTERVAL '30 minutes'
                        LIMIT 1
                    )
                ),
                -- Prepare position features for MVT
                position_features AS (
                    SELECT 
                        ST_AsMVTGeom(
                            ST_Transform(ST_SetSRID(ST_MakePoint(lon, lat), 4326), 3857),
                            ST_TileEnvelope(:z, :x, :y),
                            4096, 256, true
                        ) AS geom,
                        pilot_id,
                        pilot_name,
                        color_index,
                        elevation,
                        ROUND(speed_ms::numeric, 1) as speed_ms,
                        ROUND(heading::numeric, 0) as heading,
                        last_update
                    FROM positions_with_vectors
                ),
                -- Prepare path features for MVT
                path_features AS (
                    SELECT 
                        ST_AsMVTGeom(
                            ST_Transform(path_geom, 3857),
                            ST_TileEnvelope(:z, :x, :y),
                            4096, 256, true
                        ) AS geom,
                        pilot_id,
                        pilot_name,
                        color_index
                    FROM historical_paths
                    WHERE path_geom IS NOT NULL
                )
                -- Generate MVT with both layers
                SELECT 
                    COALESCE(
                        (SELECT ST_AsMVT(pf.*, 'positions', 4096, 'geom') 
                         FROM position_features pf WHERE geom IS NOT NULL),
                        ''::bytea
                    ) ||
                    COALESCE(
                        (SELECT ST_AsMVT(pathf.*, 'paths', 4096, 'geom') 
                         FROM path_features pathf WHERE geom IS NOT NULL),
                        ''::bytea
                    ) as mvt
            """)
            
            result = db.execute(query, {
                "z": z, "x": x, "y": y,
                "race_id": race_id,
                "delayed_time": delayed_time,
                "delayed_time_str": delayed_time.isoformat(),
                "cutoff_time_str": (delayed_time - timedelta(hours=24)).isoformat(),  # Show last 24 hours
                "simplify_tolerance": simplify_tolerance
            }).scalar()
            
            if result:
                # Compress the tile
                compressed = gzip.compress(result, compresslevel=6)
                logger.debug(f"Tile {z}/{x}/{y}: {len(result)} bytes -> {len(compressed)} compressed")
                return compressed
            else:
                return gzip.compress(b"")
                
        except Exception as e:
            logger.warning(f"Complex query failed for tile {z}/{x}/{y}, trying simple fallback: {str(e)}")
            
            # Fallback to simple query
            try:
                simple_query = text("""
                    WITH pilots AS (
                        SELECT DISTINCT ON (f.pilot_id)
                            f.pilot_id,
                            f.pilot_name,
                            (f.last_fix->>'lat')::float as lat,
                            (f.last_fix->>'lon')::float as lon,
                            (f.last_fix->>'elevation')::float as elevation,
                            f.last_fix->>'datetime' as last_update,
                            (('x' || substr(md5(f.pilot_id), 1, 6))::bit(24)::int % 10) as color_index
                        FROM flights f
                        WHERE f.race_id = :race_id
                        AND f.source LIKE '%live%'
                        AND f.last_fix IS NOT NULL
                        ORDER BY f.pilot_id, f.created_at DESC
                    ),
                    features AS (
                        SELECT 
                            ST_AsMVTGeom(
                                ST_Transform(ST_SetSRID(ST_MakePoint(lon, lat), 4326), 3857),
                                ST_TileEnvelope(:z, :x, :y),
                                4096, 256, true
                            ) AS geom,
                            pilot_id,
                            pilot_name,
                            color_index,
                            elevation,
                            last_update
                        FROM pilots
                    )
                    SELECT ST_AsMVT(f.*, 'positions', 4096, 'geom') as mvt
                    FROM features f
                    WHERE geom IS NOT NULL
                """)
                
                result = db.execute(simple_query, {
                    "z": z, "x": x, "y": y,
                    "race_id": race_id
                }).scalar()
                
                if result:
                    compressed = gzip.compress(result, compresslevel=6)
                    logger.info(f"Fallback query succeeded for tile {z}/{x}/{y}")
                    return compressed
                else:
                    return gzip.compress(b"")
                    
            except Exception as fallback_error:
                logger.error(f"Fallback query also failed: {str(fallback_error)}")
                return gzip.compress(b"")

    async def should_cluster(self, race_id: str, z: int, db: Session) -> bool:
        """Determine if clustering should be used based on pilot density"""
        if z > 12:  # Never cluster at high zoom
            return False
            
        # Count pilots in race
        result = db.execute(text("""
            SELECT COUNT(DISTINCT pilot_id) as count
            FROM flights
            WHERE race_id = :race_id
            AND source LIKE '%live%'
            AND last_fix IS NOT NULL
        """), {"race_id": race_id})
        
        pilot_count = result.scalar() or 0
        
        # Cluster if many pilots at low zoom
        if z <= 6 and pilot_count > 10:
            return True
        elif z <= 8 and pilot_count > 50:
            return True
        elif z <= 10 and pilot_count > 100:
            return True
            
        return False
    
    async def get_or_generate_tile(self, race_id: str, z: int, x: int, y: int, 
                                   db: Session) -> bytes:
        """
        Get tile from cache or generate if needed
        Tiles are shared across all users for efficiency
        """
        tile_key = (z, x, y)
        
        # Check in-memory cache first
        if race_id in self.tile_cache and tile_key in self.tile_cache[race_id]:
            # Check if tile is still fresh (less than 10 seconds old)
            if race_id in self.tile_timestamps and tile_key in self.tile_timestamps[race_id]:
                age = (datetime.now(timezone.utc) - self.tile_timestamps[race_id][tile_key]).total_seconds()
                if age < self.update_interval:
                    return self.tile_cache[race_id][tile_key]
        
        # Check Redis cache if available
        if self.redis_client:
            try:
                redis_key = f"tile:v2:{race_id}:{z}:{x}:{y}"
                cached = await self.redis_client.get(redis_key)
                if cached:
                    # Update in-memory cache
                    if race_id not in self.tile_cache:
                        self.tile_cache[race_id] = {}
                    self.tile_cache[race_id][tile_key] = cached
                    return cached
            except Exception as e:
                logger.error(f"Redis get error: {e}")
        
        # Generate new tile
        tile_data = await self.generate_tile_for_zoom(race_id, z, x, y, db)
        
        # Cache the tile
        if race_id not in self.tile_cache:
            self.tile_cache[race_id] = {}
            self.tile_timestamps[race_id] = {}
            
        self.tile_cache[race_id][tile_key] = tile_data
        self.tile_timestamps[race_id][tile_key] = datetime.now(timezone.utc)
        
        # Store in Redis with short TTL
        if self.redis_client and tile_data:
            try:
                redis_key = f"tile:v2:{race_id}:{z}:{x}:{y}"
                await self.redis_client.setex(redis_key, self.update_interval, tile_data)
            except Exception as e:
                logger.error(f"Redis set error: {e}")
        
        return tile_data

    async def get_movement_delta(self, race_id: str, tiles: List[Tuple[int, int, int]], 
                                 since: datetime, db: Session) -> Dict:
        """
        Get only the movement updates since last check
        Much more efficient than sending full tiles
        """
        try:
            # Get positions that have updated since 'since' timestamp
            delayed_time = datetime.now(timezone.utc) - timedelta(seconds=self.delay_seconds)
            
            result = db.execute(text("""
                SELECT DISTINCT ON (f.pilot_id)
                    f.pilot_id,
                    f.pilot_name,
                    (f.last_fix->>'lat')::float as lat,
                    (f.last_fix->>'lon')::float as lon,
                    (f.last_fix->>'elevation')::float as elevation,
                    f.last_fix->>'datetime' as last_update,
                    -- Movement data for interpolation
                    ST_X(ST_Transform(
                        ST_SetSRID(ST_MakePoint(
                            (f.last_fix->>'lon')::float,
                            (f.last_fix->>'lat')::float
                        ), 4326), 3857
                    )) as x_mercator,
                    ST_Y(ST_Transform(
                        ST_SetSRID(ST_MakePoint(
                            (f.last_fix->>'lon')::float,
                            (f.last_fix->>'lat')::float
                        ), 4326), 3857
                    )) as y_mercator
                FROM flights f
                WHERE f.race_id = :race_id
                AND f.source LIKE '%live%'
                AND f.last_fix->>'datetime' <= :delayed_time_str
                AND f.last_fix->>'datetime' > :since_str
                ORDER BY f.pilot_id, f.created_at DESC
            """), {
                "race_id": race_id,
                "delayed_time_str": delayed_time.isoformat(),
                "since_str": since.isoformat()
            })
            
            updates = []
            for row in result:
                updates.append({
                    "pilot_id": row.pilot_id,
                    "pilot_name": row.pilot_name,
                    "lat": row.lat,
                    "lon": row.lon,
                    "elevation": row.elevation,
                    "timestamp": row.last_update,
                    "x_mercator": row.x_mercator,
                    "y_mercator": row.y_mercator
                })
            
            return {
                "type": "delta",
                "timestamp": delayed_time.isoformat(),
                "updates": updates
            }
            
        except Exception as e:
            logger.error(f"Error getting movement delta: {str(e)}")
            return {"type": "delta", "updates": []}

    def calculate_tiles_for_viewport(self, bbox, zoom):
        """Calculate tiles needed for a bounding box at given zoom"""
        import math
        
        min_lon, min_lat, max_lon, max_lat = bbox
        n = 2 ** zoom
        
        # Calculate tile coordinates
        min_x = int((min_lon + 180) / 360 * n)
        max_x = int((max_lon + 180) / 360 * n)
        
        min_y = int((1 - math.log(math.tan(math.radians(max_lat)) + 1/math.cos(math.radians(max_lat))) / math.pi) / 2 * n)
        max_y = int((1 - math.log(math.tan(math.radians(min_lat)) + 1/math.cos(math.radians(min_lat))) / math.pi) / 2 * n)
        
        tiles = []
        for x in range(min_x, max_x + 1):
            for y in range(min_y, max_y + 1):
                tiles.append((zoom, x, y))
        
        return tiles
    
    async def cleanup_old_tiles(self, max_age_seconds: int = 60):
        """Clean up old tiles from memory cache"""
        now = datetime.now(timezone.utc)
        
        for race_id in list(self.tile_timestamps.keys()):
            tiles_to_remove = []
            
            for tile_key, timestamp in self.tile_timestamps[race_id].items():
                if (now - timestamp).total_seconds() > max_age_seconds:
                    tiles_to_remove.append(tile_key)
            
            for tile_key in tiles_to_remove:
                del self.tile_cache[race_id][tile_key]
                del self.tile_timestamps[race_id][tile_key]
                
            # Clean up empty race entries
            if not self.tile_cache[race_id]:
                del self.tile_cache[race_id]
                del self.tile_timestamps[race_id]


# Global instance
production_tile_service = ProductionTileService()