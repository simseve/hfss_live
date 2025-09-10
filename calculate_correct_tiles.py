#!/usr/bin/env python3
"""
Calculate correct tiles for actual data location
"""

import math

def lat_lon_to_tile(lat, lon, zoom):
    """Convert lat/lon to tile coordinates"""
    n = 2 ** zoom
    x = int((lon + 180) / 360 * n)
    lat_rad = math.radians(lat)
    y = int((1 - math.log(math.tan(lat_rad) + 1/math.cos(lat_rad)) / math.pi) / 2 * n)
    return (zoom, x, y)

# Pilot locations from the debug output
pilots = [
    ("Simone Severini", 45.9732, 8.8754),
    ("Tenz B", 45.8424, 8.7191)
]

print("Correct tile coordinates for actual pilot locations:")
print("="*60)

for name, lat, lon in pilots:
    print(f"\n{name} at ({lat:.4f}, {lon:.4f}):")
    for zoom in [10, 12, 14]:
        z, x, y = lat_lon_to_tile(lat, lon, zoom)
        print(f"  Zoom {zoom}: {z}/{x}/{y}")

# Calculate center and tiles around it
center_lat = sum(p[1] for p in pilots) / len(pilots)
center_lon = sum(p[2] for p in pilots) / len(pilots)

print(f"\nCenter point: ({center_lat:.4f}, {center_lon:.4f})")
print("Tiles for testing:")

for zoom in [10, 12, 14]:
    z, x, y = lat_lon_to_tile(center_lat, center_lon, zoom)
    print(f"\nZoom {zoom} tiles (3x3 grid):")
    for dy in [-1, 0, 1]:
        for dx in [-1, 0, 1]:
            print(f"  [{z}, {x+dx}, {y+dy}],")