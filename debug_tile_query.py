#!/usr/bin/env python3
"""
Debug why tile query returns empty
"""

from database.db_replica import get_read_db_with_fallback
from sqlalchemy import text
from datetime import datetime, timezone, timedelta

db = next(get_read_db_with_fallback())

try:
    race_id = "68aadbb85da525060edaaebf"
    z, x, y = 12, 1864, 1894
    delayed_time = datetime.now(timezone.utc) - timedelta(seconds=60)
    
    # Step 1: Check if we have flights
    print("Step 1: Checking flights...")
    result = db.execute(text("""
        SELECT COUNT(*) as count
        FROM flights f
        WHERE f.race_id = :race_id
        AND f.source LIKE '%live%'
    """), {"race_id": race_id})
    
    count = result.scalar()
    print(f"  Found {count} live flights")
    
    # Step 2: Check recent flights with valid timestamps
    print("\nStep 2: Checking recent flights with timestamps...")
    result = db.execute(text("""
        SELECT DISTINCT ON (f.pilot_id)
            f.pilot_id,
            f.pilot_name,
            f.last_fix->>'datetime' as last_update,
            (f.last_fix->>'lat')::float as lat,
            (f.last_fix->>'lon')::float as lon
        FROM flights f
        WHERE f.race_id = :race_id
        AND f.source LIKE '%live%'
        AND f.last_fix->>'datetime' <= :delayed_time_str
        AND f.last_fix->>'datetime' > :cutoff_time_str
        ORDER BY f.pilot_id, f.created_at DESC
    """), {
        "race_id": race_id,
        "delayed_time_str": delayed_time.isoformat(),
        "cutoff_time_str": (delayed_time - timedelta(hours=2)).isoformat()
    })
    
    pilots = list(result)
    print(f"  Found {len(pilots)} pilots with recent data")
    for pilot in pilots[:3]:
        print(f"    - {pilot.pilot_name}: ({pilot.lat:.4f}, {pilot.lon:.4f}) at {pilot.last_update}")
    
    # Step 3: Check tile envelope intersection
    print(f"\nStep 3: Checking tile {z}/{x}/{y} envelope...")
    result = db.execute(text("""
        WITH bounds AS (
            SELECT 
                ST_TileEnvelope(:z, :x, :y) AS geom,
                ST_AsText(ST_Transform(ST_TileEnvelope(:z, :x, :y), 4326)) as wgs84_bounds
        )
        SELECT wgs84_bounds FROM bounds
    """), {"z": z, "x": x, "y": y})
    
    bounds = result.scalar()
    print(f"  Tile bounds (WGS84): {bounds}")
    
    # Step 4: Check if any points fall within tile
    print("\nStep 4: Checking points in tile...")
    result = db.execute(text("""
        WITH bounds AS (
            SELECT ST_TileEnvelope(:z, :x, :y) AS geom
        ),
        recent_flights AS (
            SELECT DISTINCT ON (f.pilot_id)
                f.pilot_id,
                f.pilot_name,
                (f.last_fix->>'lat')::float as lat,
                (f.last_fix->>'lon')::float as lon
            FROM flights f
            WHERE f.race_id = :race_id
            AND f.source LIKE '%live%'
            AND f.last_fix->>'datetime' <= :delayed_time_str
            ORDER BY f.pilot_id, f.created_at DESC
        )
        SELECT 
            rf.pilot_name,
            rf.lat,
            rf.lon,
            ST_Intersects(
                ST_SetSRID(ST_MakePoint(rf.lon, rf.lat), 4326),
                ST_Transform(bounds.geom, 4326)
            ) as in_tile
        FROM recent_flights rf
        CROSS JOIN bounds
    """), {
        "race_id": race_id,
        "z": z, "x": x, "y": y,
        "delayed_time_str": delayed_time.isoformat()
    })
    
    in_tile_count = 0
    for row in result:
        if row.in_tile:
            in_tile_count += 1
            print(f"  ✓ {row.pilot_name} at ({row.lat:.4f}, {row.lon:.4f}) IS in tile")
        else:
            print(f"  ✗ {row.pilot_name} at ({row.lat:.4f}, {row.lon:.4f}) NOT in tile")
    
    print(f"\n  Total points in tile: {in_tile_count}")
    
    # Step 5: Try simplified MVT generation
    print("\nStep 5: Generating simplified MVT...")
    result = db.execute(text("""
        WITH recent_flights AS (
            SELECT DISTINCT ON (f.pilot_id)
                f.pilot_id,
                f.pilot_name,
                (f.last_fix->>'lat')::float as lat,
                (f.last_fix->>'lon')::float as lon
            FROM flights f
            WHERE f.race_id = :race_id
            AND f.source LIKE '%live%'
            ORDER BY f.pilot_id, f.created_at DESC
            LIMIT 10
        ),
        features AS (
            SELECT 
                ST_AsMVTGeom(
                    ST_Transform(ST_SetSRID(ST_MakePoint(lon, lat), 4326), 3857),
                    ST_TileEnvelope(:z, :x, :y),
                    4096, 256, true
                ) AS geom,
                pilot_id,
                pilot_name
            FROM recent_flights
        )
        SELECT ST_AsMVT(f.*, 'positions', 4096, 'geom') as mvt
        FROM features f
        WHERE geom IS NOT NULL
    """), {
        "race_id": race_id,
        "z": z, "x": x, "y": y
    })
    
    mvt = result.scalar()
    if mvt:
        print(f"  ✓ MVT generated: {len(mvt)} bytes")
    else:
        print(f"  ✗ MVT is None/empty")
        
finally:
    db.close()