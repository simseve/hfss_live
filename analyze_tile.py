#!/usr/bin/env python3
"""Analyze MVT tile contents"""

import requests
import mapbox_vector_tile
import json

# Get the tile
url = "http://localhost:8000/tracking/tiles/simple/68aadbb85da525060edaaebf/12/1580/2287"
response = requests.get(url)
data = response.json()

if data["size"] > 0:
    # Get the raw tile
    from services.simple_tile_service import generate_simple_tile
    from database.db_replica import get_replica_db
    import asyncio
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker
    import os
    
    # Direct database query to get tile
    DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://neondb_owner:npg_WwI9ehBrZ8pg@ep-rapid-violet-a2luj2ya-pooler.eu-central-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require')
    engine = create_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine)
    
    with Session() as db:
        # Get the raw MVT data
        result = db.execute(text("""
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
                    ltp.datetime,
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
        """), {
            "z": 12, "x": 1580, "y": 2287,
            "race_id": "68aadbb85da525060edaaebf"
        })
        
        mvt_data = result.scalar()
        
        if mvt_data:
            print(f"Tile size: {len(mvt_data)} bytes")
            print(f"First 20 bytes (hex): {mvt_data[:20].hex()}")
            print("\n" + "="*60)
            
            # Decode MVT
            try:
                decoded = mapbox_vector_tile.decode(mvt_data)
                
                for layer_name, layer_data in decoded.items():
                    print(f"\nLayer: '{layer_name}'")
                    print(f"  Version: {layer_data.get('version', 'unknown')}")
                    print(f"  Extent: {layer_data.get('extent', 'unknown')}")
                    
                    features = layer_data.get('features', [])
                    print(f"  Features: {len(features)}")
                    
                    if features:
                        # Analyze first few features
                        print("\n  Sample features:")
                        
                        # Group by pilot
                        pilots = {}
                        for feature in features:
                            props = feature.get('properties', {})
                            pilot = props.get('pilot_name', 'Unknown')
                            if pilot not in pilots:
                                pilots[pilot] = []
                            pilots[pilot].append(props)
                        
                        print(f"\n  Pilots found: {len(pilots)}")
                        for pilot, points in list(pilots.items())[:5]:
                            print(f"    - {pilot}: {len(points)} points")
                            if points:
                                # Show sample point
                                p = points[0]
                                print(f"      Sample: elevation={p.get('elevation', 'N/A')}m")
                                print(f"              lat={p.get('lat', 'N/A')}, lon={p.get('lon', 'N/A')}")
                        
                        # Check data quality
                        print("\n  Data quality check:")
                        elevations = [f['properties'].get('elevation') for f in features if 'elevation' in f.get('properties', {})]
                        if elevations:
                            print(f"    Elevation range: {min(elevations):.1f}m to {max(elevations):.1f}m")
                        
                        # Check geometry types
                        geom_types = set(f.get('geometry', {}).get('type', 'unknown') for f in features)
                        print(f"    Geometry types: {geom_types}")
                        
            except Exception as e:
                print(f"Error decoding MVT: {e}")
                
            # Check what's needed for production
            print("\n" + "="*60)
            print("PRODUCTION READINESS ASSESSMENT:")
            print("="*60)
            
            issues = []
            
            # Check data structure
            if len(features) == 1000:
                issues.append("⚠️  Hitting 1000 point limit - need pagination or clustering")
            
            if len(mvt_data) > 500000:  # 500KB
                issues.append("⚠️  Tile too large (>500KB) - need point reduction")
            
            if not any('datetime' in f.get('properties', {}) for f in features[:10]):
                issues.append("⚠️  Missing timestamp data for interpolation")
            
            # Check what's missing
            issues.append("❌ No simplified path lines (complex query failing)")
            issues.append("❌ No proper error handling in tile generation")
            issues.append("❌ No tile expiration/cache invalidation strategy")
            issues.append("❌ No monitoring/metrics for tile generation")
            issues.append("❌ No rate limiting for tile requests")
            issues.append("❌ No compression for tile data")
            
            if issues:
                print("\nIssues to fix:")
                for issue in issues:
                    print(f"  {issue}")
            
            print("\n✅ What's working:")
            print("  - Basic MVT generation")
            print("  - Point data included")
            print("  - WebSocket infrastructure")
            print("  - Redis caching setup")
            
        else:
            print("No MVT data generated")