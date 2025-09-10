"""
Simplified tile generation service for testing
"""

import logging
from typing import Optional
from datetime import datetime, timezone, timedelta
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


async def generate_simple_tile(race_id: str, z: int, x: int, y: int, 
                               db: Session, delay_seconds: int = 60) -> bytes:
    """
    Generate a simple MVT tile with just points for testing
    """
    try:
        delayed_time = datetime.now(timezone.utc) - timedelta(seconds=delay_seconds)
        logger.info(f"Generating simple tile {z}/{x}/{y} for race {race_id}")
        
        # Much simpler query - just get points and make tiles
        query = text("""
            WITH 
            bounds AS (
                SELECT ST_TileEnvelope(:z, :x, :y) AS geom
            ),
            tile_points AS (
                SELECT 
                    ltp.flight_uuid::text as flight_id,
                    f.pilot_name,
                    ltp.lat,
                    ltp.lon,
                    ltp.elevation,
                    ST_AsMVTGeom(
                        ST_Transform(ST_SetSRID(ST_MakePoint(ltp.lon, ltp.lat), 4326), 3857),
                        ST_TileEnvelope(:z, :x, :y),
                        4096,
                        256,
                        true
                    ) AS geom
                FROM live_track_points ltp
                JOIN flights f ON f.id = ltp.flight_uuid
                CROSS JOIN bounds
                WHERE f.race_id = :race_id
                AND ltp.datetime > NOW() - INTERVAL '30 days'
                AND ST_Intersects(
                    ST_SetSRID(ST_MakePoint(ltp.lon, ltp.lat), 4326),
                    ST_Transform(bounds.geom, 4326)
                )
                LIMIT 1000
            )
            SELECT ST_AsMVT(tile_points.*, 'points', 4096, 'geom') as mvt
            FROM tile_points
            WHERE geom IS NOT NULL
        """)
        
        result = db.execute(query, {
            "z": z, "x": x, "y": y,
            "race_id": race_id
        }).scalar()
        
        if result:
            logger.info(f"Simple tile generated: {len(result)} bytes")
            return result
        else:
            logger.info(f"Simple tile empty for {z}/{x}/{y}")
            return b""
            
    except Exception as e:
        logger.error(f"Error generating simple tile: {str(e)}")
        return b""