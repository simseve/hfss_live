import asyncio
import logging
from typing import Dict, List, Optional, Tuple, Set
from datetime import datetime, timezone, timedelta
import redis.asyncio as redis
import hashlib
import base64
import json
from sqlalchemy import text
from sqlalchemy.orm import Session
from database.db_replica import get_replica_db, get_db
from database.models import Flight, LiveTrackPoint, Race
from config import settings

logger = logging.getLogger(__name__)


class TileGenerationService:
    def __init__(self):
        self.redis_client: Optional[redis.Redis] = None
        self.tile_ttl_seconds = 300  # 5 minutes for live tiles
        self.historical_tile_ttl = 3600  # 1 hour for historical tiles
        self.max_points_per_tile = 10000  # Limit points per tile for performance
        
    async def initialize(self):
        """Initialize Redis connection for tile caching"""
        try:
            redis_url = settings.get_redis_url()
            self.redis_client = await redis.from_url(
                redis_url,
                encoding="utf-8",
                decode_responses=False  # We'll handle encoding for binary data
            )
            await self.redis_client.ping()
            logger.info("Tile generation service initialized with Redis caching")
        except Exception as e:
            logger.warning(f"Redis not available for tile caching: {str(e)}")
            self.redis_client = None

    async def close(self):
        """Close Redis connection"""
        if self.redis_client:
            await self.redis_client.close()

    def _get_tile_cache_key(self, race_id: str, z: int, x: int, y: int, 
                           timestamp_bucket: Optional[int] = None) -> str:
        """Generate Redis cache key for a tile"""
        if timestamp_bucket:
            return f"mvt:{race_id}:{z}:{x}:{y}:{timestamp_bucket}"
        return f"mvt:{race_id}:{z}:{x}:{y}:latest"

    def _get_timestamp_bucket(self, timestamp: datetime, bucket_size_seconds: int = 30) -> int:
        """Get timestamp bucket for cache invalidation"""
        epoch = int(timestamp.timestamp())
        return epoch // bucket_size_seconds * bucket_size_seconds

    async def get_cached_tile(self, race_id: str, z: int, x: int, y: int) -> Optional[bytes]:
        """Retrieve a tile from cache if available"""
        if not self.redis_client:
            return None
        
        try:
            key = self._get_tile_cache_key(race_id, z, x, y)
            data = await self.redis_client.get(key)
            if data:
                logger.debug(f"Cache hit for tile {z}/{x}/{y}")
                return data
        except Exception as e:
            logger.error(f"Error retrieving cached tile: {str(e)}")
        
        return None

    async def cache_tile(self, race_id: str, z: int, x: int, y: int, 
                        tile_data: bytes, is_historical: bool = False):
        """Store a tile in cache"""
        if not self.redis_client:
            return
        
        try:
            key = self._get_tile_cache_key(race_id, z, x, y)
            ttl = self.historical_tile_ttl if is_historical else self.tile_ttl_seconds
            await self.redis_client.setex(key, ttl, tile_data)
            logger.debug(f"Cached tile {z}/{x}/{y} with TTL {ttl}s")
        except Exception as e:
            logger.error(f"Error caching tile: {str(e)}")

    async def generate_live_tile(self, race_id: str, z: int, x: int, y: int,
                                db: Session, since_timestamp: Optional[datetime] = None,
                                delay_seconds: int = 60) -> bytes:
        """
        Generate MVT tile for live tracking data with optional delay and simplified paths.

        Args:
            delay_seconds: Delay in seconds for live data (default 60s for broadcast delay)
        """
        try:
            # Validate tile coordinates
            max_coord = 2 ** z
            if not (0 <= x < max_coord and 0 <= y < max_coord):
                logger.warning(f"Invalid tile coordinates: {z}/{x}/{y} (max valid: {max_coord-1})")
                return b''

            # Validate zoom level
            if not (0 <= z <= 20):
                logger.warning(f"Invalid zoom level: {z} (must be 0-20)")
                return b''

            # Calculate delayed timestamp for "live" data
            delayed_time = datetime.now(timezone.utc) - timedelta(seconds=delay_seconds)
            logger.debug(f"Generating tile {z}/{x}/{y} for race {race_id}, delayed_time: {delayed_time}")
            
            # Build the time filter
            time_filter = ""
            if since_timestamp:
                time_filter = f"AND ltp.datetime > '{since_timestamp.isoformat()}'"
            
            # Use PostGIS to generate MVT tile with both simplified paths and current positions
            # This query now includes historical paths simplified using ST_SimplifyPreserveTopology
            query = text(f"""
                WITH 
                bounds AS (
                    SELECT ST_TileEnvelope(:z, :x, :y) AS geom
                ),
                flight_colors AS (
                    SELECT DISTINCT 
                        f.id as flight_uuid,
                        f.pilot_name,
                        (('x' || substr(md5(f.id::text), 1, 6))::bit(24)::int % 10) as color_index
                    FROM flights f
                    WHERE f.race_id = :race_id
                    AND f.source LIKE '%live%'
                ),
                -- Historical simplified paths (everything before delay)
                historical_paths AS (
                    SELECT 
                        ltp.flight_uuid,
                        fc.pilot_name,
                        fc.color_index,
                        -- Create linestring from historical points and simplify based on zoom
                        ST_SimplifyPreserveTopology(
                            ST_MakeLine(
                                ST_SetSRID(ST_MakePoint(ltp.lon, ltp.lat), 4326)
                                ORDER BY ltp.datetime
                            ),
                            -- Simplification tolerance based on zoom level
                            CASE 
                                WHEN :z <= 10 THEN 0.01  -- Very simplified at low zoom
                                WHEN :z <= 12 THEN 0.005
                                WHEN :z <= 14 THEN 0.001
                                ELSE 0.0005  -- Less simplified at high zoom
                            END
                        ) as path_geom,
                        MIN(ltp.datetime) as start_time,
                        MAX(ltp.datetime) as end_time,
                        COUNT(*) as point_count
                    FROM live_track_points ltp
                    JOIN flight_colors fc ON fc.flight_uuid = ltp.flight_uuid
                    CROSS JOIN bounds
                    WHERE ltp.datetime <= :delayed_time
                    AND ltp.datetime > :delayed_time - INTERVAL '7 days'
                    AND ST_Intersects(
                        ST_SetSRID(ST_MakePoint(ltp.lon, ltp.lat), 4326),
                        ST_Transform(bounds.geom, 4326)
                    )
                    GROUP BY ltp.flight_uuid, fc.pilot_name, fc.color_index
                ),
                -- Current positions (at the delayed timestamp)
                current_positions AS (
                    SELECT DISTINCT ON (ltp.flight_uuid)
                        ltp.flight_uuid,
                        ltp.datetime,
                        ltp.lat,
                        ltp.lon,
                        ltp.elevation,
                        fc.pilot_name,
                        fc.color_index,
                        ST_SetSRID(ST_MakePoint(ltp.lon, ltp.lat), 4326) as geom,
                        -- Calculate speed and heading for interpolation hint
                        LAG(ltp.lon) OVER (PARTITION BY ltp.flight_uuid ORDER BY ltp.datetime) as prev_lon,
                        LAG(ltp.lat) OVER (PARTITION BY ltp.flight_uuid ORDER BY ltp.datetime) as prev_lat,
                        LAG(ltp.datetime) OVER (PARTITION BY ltp.flight_uuid ORDER BY ltp.datetime) as prev_time
                    FROM live_track_points ltp
                    JOIN flight_colors fc ON fc.flight_uuid = ltp.flight_uuid
                    CROSS JOIN bounds
                    WHERE ltp.datetime <= :delayed_time
                    AND ltp.datetime > :delayed_time - INTERVAL '7 days'
                    AND ST_Intersects(
                        ST_SetSRID(ST_MakePoint(ltp.lon, ltp.lat), 4326),
                        ST_Transform(bounds.geom, 4326)
                    )
                    ORDER BY ltp.flight_uuid, ltp.datetime DESC
                ),
                -- Calculate movement vectors for interpolation
                positions_with_vectors AS (
                    SELECT 
                        *,
                        CASE 
                            WHEN prev_lon IS NOT NULL AND prev_lat IS NOT NULL THEN
                                DEGREES(ST_Azimuth(
                                    ST_MakePoint(prev_lon, prev_lat)::geography,
                                    ST_MakePoint(lon, lat)::geography
                                ))
                            ELSE 0
                        END as heading,
                        CASE
                            WHEN prev_lon IS NOT NULL AND prev_lat IS NOT NULL AND prev_time IS NOT NULL THEN
                                ST_Distance(
                                    ST_MakePoint(prev_lon, prev_lat)::geography,
                                    ST_MakePoint(lon, lat)::geography
                                ) / EXTRACT(EPOCH FROM (datetime - prev_time))
                            ELSE 0
                        END as speed_ms
                    FROM current_positions
                ),
                -- Combine path features for MVT
                path_features AS (
                    SELECT 
                        ST_AsMVTGeom(
                            path_geom,
                            ST_TileEnvelope(:z, :x, :y),
                            4096,
                            256,
                            true
                        ) AS geom,
                        flight_uuid::text as flight_id,
                        pilot_name,
                        color_index,
                        'path' as feature_type,
                        to_char(start_time, 'YYYY-MM-DD"T"HH24:MI:SS"Z"') as start_time,
                        to_char(end_time, 'YYYY-MM-DD"T"HH24:MI:SS"Z"') as end_time,
                        point_count
                    FROM historical_paths
                    WHERE path_geom IS NOT NULL
                ),
                -- Current position features for MVT
                position_features AS (
                    SELECT 
                        ST_AsMVTGeom(
                            geom,
                            ST_TileEnvelope(:z, :x, :y),
                            4096,
                            256,
                            true
                        ) AS geom,
                        flight_uuid::text as flight_id,
                        pilot_name,
                        color_index,
                        'position' as feature_type,
                        elevation,
                        to_char(datetime, 'YYYY-MM-DD"T"HH24:MI:SS"Z"') as dt,
                        heading,
                        speed_ms
                    FROM positions_with_vectors
                ),
                -- Union all features
                all_features AS (
                    SELECT
                        geom,
                        flight_id,
                        pilot_name,
                        color_index,
                        feature_type,
                        start_time,
                        end_time,
                        point_count,
                        NULL::integer as elevation,
                        NULL::real as heading,
                        NULL::real as speed_ms
                    FROM path_features
                    UNION ALL
                    SELECT
                        geom,
                        flight_id,
                        pilot_name,
                        color_index,
                        feature_type,
                        NULL as start_time,
                        dt as end_time,
                        NULL::integer as point_count,
                        elevation,
                        heading,
                        speed_ms
                    FROM position_features
                )
                SELECT 
                    COALESCE(
                        (SELECT ST_AsMVT(f.*, 'tracks', 4096, 'geom') 
                         FROM all_features f 
                         WHERE f.geom IS NOT NULL),
                        ''::bytea
                    ) as mvt
            """)
            
            result = db.execute(query, {
                "z": z, "x": x, "y": y,
                "race_id": race_id,
                "delayed_time": delayed_time
            }).scalar()
            
            if result:
                logger.info(f"Generated tile {z}/{x}/{y} for race {race_id}: {len(result)} bytes")
            else:
                logger.debug(f"Empty tile {z}/{x}/{y} for race {race_id}")
            
            return result or b""
            
        except Exception as e:
            logger.error(f"Error generating live tile {z}/{x}/{y}: {str(e)}")
            # Rollback the transaction if it's in a failed state
            try:
                db.rollback()
            except:
                pass
            return b""

    async def generate_delta_tile(self, race_id: str, z: int, x: int, y: int, 
                                 db: Session, since_timestamp: datetime) -> Dict:
        """Generate a delta update containing only new points since timestamp"""
        try:
            # Query for new points in this tile since the last update
            query = text("""
                WITH 
                bounds AS (
                    SELECT ST_TileEnvelope(:z, :x, :y) AS geom
                ),
                new_points AS (
                    SELECT 
                        ltp.flight_uuid::text as flight_id,
                        ltp.datetime,
                        ltp.lat,
                        ltp.lon,
                        ltp.elevation,
                        f.pilot_name
                    FROM live_track_points ltp
                    JOIN flights f ON f.id = ltp.flight_uuid
                    JOIN bounds ON ST_Intersects(
                        ST_MakePoint(ltp.lon, ltp.lat),
                        bounds.geom
                    )
                    WHERE ltp.datetime > :since_timestamp
                    AND f.race_id = :race_id
                    AND f.source LIKE '%live%'
                    ORDER BY ltp.datetime DESC
                    LIMIT 1000
                )
                SELECT 
                    flight_id,
                    pilot_name,
                    json_agg(json_build_object(
                        'lat', lat,
                        'lon', lon,
                        'elevation', elevation,
                        'datetime', to_char(datetime, 'YYYY-MM-DD"T"HH24:MI:SS"Z"')
                    ) ORDER BY datetime) as points
                FROM new_points
                GROUP BY flight_id, pilot_name
            """)
            
            result = db.execute(query, {
                "z": z, "x": x, "y": y,
                "race_id": race_id,
                "since_timestamp": since_timestamp
            }).fetchall()
            
            delta_data = {
                "type": "delta",
                "tile": {"z": z, "x": x, "y": y},
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "flights": []
            }
            
            for row in result:
                delta_data["flights"].append({
                    "flight_id": row.flight_id,
                    "pilot_name": row.pilot_name,
                    "new_points": json.loads(row.points) if row.points else []
                })
            
            return delta_data
            
        except Exception as e:
            logger.error(f"Error generating delta tile {z}/{x}/{y}: {str(e)}")
            return {"type": "delta", "flights": []}

    async def get_tiles_with_data(self, race_id: str, zoom_levels: List[int], 
                                 db: Session) -> Dict[int, Set[Tuple[int, int]]]:
        """Find which tiles contain data for given zoom levels"""
        try:
            tiles_by_zoom = {}
            
            for z in zoom_levels:
                # Calculate tile bounds for this zoom level
                query = text("""
                    WITH flight_bounds AS (
                        SELECT 
                            MIN(ltp.lon) as min_lon,
                            MAX(ltp.lon) as max_lon,
                            MIN(ltp.lat) as min_lat,
                            MAX(ltp.lat) as max_lat
                        FROM live_track_points ltp
                        JOIN flights f ON f.id = ltp.flight_uuid
                        WHERE f.race_id = :race_id
                        AND ltp.datetime > NOW() - INTERVAL '4 hours'
                    )
                    SELECT DISTINCT
                        floor((lon + 180) / 360 * power(2, :z))::int as tile_x,
                        floor((1 - ln(tan(radians(lat)) + 1/cos(radians(lat))) / pi()) 
                              / 2 * power(2, :z))::int as tile_y
                    FROM live_track_points ltp
                    JOIN flights f ON f.id = ltp.flight_uuid
                    WHERE f.race_id = :race_id
                    AND ltp.datetime > NOW() - INTERVAL '4 hours'
                    AND f.source LIKE '%live%'
                """)
                
                result = db.execute(query, {"race_id": race_id, "z": z}).fetchall()
                tiles_by_zoom[z] = {(row.tile_x, row.tile_y) for row in result}
                
            return tiles_by_zoom
            
        except Exception as e:
            logger.error(f"Error finding tiles with data: {str(e)}")
            return {}

    async def generate_tile_batch(self, race_id: str, tiles: List[Tuple[int, int, int]], 
                                 db: Session) -> Dict[Tuple[int, int, int], bytes]:
        """Generate multiple tiles in batch for efficiency"""
        generated_tiles = {}
        
        # Group tiles by zoom level for potential optimization
        tiles_by_zoom = {}
        for z, x, y in tiles:
            if z not in tiles_by_zoom:
                tiles_by_zoom[z] = []
            tiles_by_zoom[z].append((x, y))
        
        for z, xy_pairs in tiles_by_zoom.items():
            for x, y in xy_pairs:
                # Check cache first
                cached = await self.get_cached_tile(race_id, z, x, y)
                if cached:
                    generated_tiles[(z, x, y)] = cached
                else:
                    # Generate new tile
                    tile_data = await self.generate_live_tile(race_id, z, x, y, db)
                    if tile_data:
                        generated_tiles[(z, x, y)] = tile_data
                        await self.cache_tile(race_id, z, x, y, tile_data)
        
        return generated_tiles

    async def invalidate_tiles_for_flight(self, race_id: str, flight_id: str, 
                                         zoom_levels: List[int], db: Session):
        """Invalidate cache for tiles affected by a flight update"""
        if not self.redis_client:
            return
        
        try:
            # Find tiles containing this flight's recent points
            query = text("""
                SELECT DISTINCT
                    :z as z,
                    floor((lon + 180) / 360 * power(2, :z))::int as x,
                    floor((1 - ln(tan(radians(lat)) + 1/cos(radians(lat))) / pi()) 
                          / 2 * power(2, :z))::int as y
                FROM live_track_points
                WHERE flight_uuid = :flight_id
                AND datetime > NOW() - INTERVAL '10 minutes'
            """)
            
            for z in zoom_levels:
                result = db.execute(query, {"z": z, "flight_id": flight_id}).fetchall()
                
                for row in result:
                    key = self._get_tile_cache_key(race_id, row.z, row.x, row.y)
                    await self.redis_client.delete(key)
                    
            logger.debug(f"Invalidated tiles for flight {flight_id}")
            
        except Exception as e:
            logger.error(f"Error invalidating tiles: {str(e)}")

    def calculate_tiles_for_viewport(self, bbox: List[float], zoom: int) -> List[Tuple[int, int, int]]:
        """Calculate which tiles cover a given bounding box at a zoom level"""
        min_lon, min_lat, max_lon, max_lat = bbox
        
        # Convert lat/lon to tile coordinates
        min_x = int((min_lon + 180) / 360 * (2 ** zoom))
        max_x = int((max_lon + 180) / 360 * (2 ** zoom))
        
        min_y = int((1 - __import__('math').log(
            __import__('math').tan(__import__('math').radians(max_lat)) + 
            1/__import__('math').cos(__import__('math').radians(max_lat))
        ) / __import__('math').pi) / 2 * (2 ** zoom))
        
        max_y = int((1 - __import__('math').log(
            __import__('math').tan(__import__('math').radians(min_lat)) + 
            1/__import__('math').cos(__import__('math').radians(min_lat))
        ) / __import__('math').pi) / 2 * (2 ** zoom))
        
        tiles = []
        for x in range(min_x, max_x + 1):
            for y in range(min_y, max_y + 1):
                tiles.append((zoom, x, y))
        
        return tiles


# Create singleton instance
tile_service = TileGenerationService()