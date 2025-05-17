from config import settings
import sqlalchemy
from sqlalchemy import create_engine, text
import sys
import os
# Add parent directory to path to import from config
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def check_scoring_data():
    engine = create_engine(settings.DATABASE_URI)

    with engine.connect() as conn:
        # Check total count
        result = conn.execute(text('SELECT COUNT(*) FROM scoring_tracks'))
        total_count = result.scalar()
        print(f'Total scoring track points: {total_count}')

        if total_count == 0:
            print("No points in scoring_tracks table. This is the root issue.")
            return

        # Get sample flight UUIDs
        result = conn.execute(
            text('SELECT DISTINCT flight_uuid FROM scoring_tracks LIMIT 5'))
        print('Sample flight UUIDs:')
        flight_uuids = []
        for row in result:
            flight_uuid = row[0]
            print(f"- {flight_uuid}")
            flight_uuids.append(flight_uuid)

        # Check points for each flight UUID
        for flight_uuid in flight_uuids:
            result = conn.execute(
                text(f"SELECT COUNT(*) FROM scoring_tracks WHERE flight_uuid = '{flight_uuid}'"))
            count = result.scalar()
            print(f"Flight UUID {flight_uuid} has {count} points")

            # Check if any points have NULL lat/lon
            result = conn.execute(text(
                f"SELECT COUNT(*) FROM scoring_tracks WHERE flight_uuid = '{flight_uuid}' AND (lat IS NULL OR lon IS NULL)"
            ))
            null_count = result.scalar()
            print(f"  - Points with NULL lat/lon: {null_count}")

            # Check if points are in valid range
            result = conn.execute(text(
                f"SELECT MIN(lat), MAX(lat), MIN(lon), MAX(lon) FROM scoring_tracks WHERE flight_uuid = '{flight_uuid}'"
            ))
            min_lat, max_lat, min_lon, max_lon = result.fetchone()
            print(f"  - Lat range: {min_lat} to {max_lat}")
            print(f"  - Lon range: {min_lon} to {max_lon}")

            # Try a simple tile bound check for zoom level 0
            result = conn.execute(text(f"""
            WITH bounds AS (
                SELECT ST_TileEnvelope(0, 0, 0) AS geom
            )
            SELECT COUNT(*) FROM scoring_tracks t, bounds b
            WHERE t.flight_uuid = '{flight_uuid}'
            AND t.lat IS NOT NULL AND t.lon IS NOT NULL
            AND ST_Intersects(
                ST_Transform(ST_SetSRID(ST_MakePoint(t.lon, t.lat), 4326), 3857),
                b.geom
            )
            """))
            points_in_bounds = result.scalar()
            print(f"  - Points in global tile (z=0): {points_in_bounds}")


if __name__ == "__main__":
    check_scoring_data()
