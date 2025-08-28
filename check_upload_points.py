#!/usr/bin/env python3
import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

# Get database URL from environment
database_url = os.getenv("DATABASE_URL")
if not database_url:
    print("DATABASE_URL not set")
    exit(1)

# Create engine
engine = create_engine(database_url)

# Check uploaded_track_points
with engine.connect() as conn:
    # Check for the specific flight
    result = conn.execute(text("""
        SELECT COUNT(*) as count 
        FROM uploaded_track_points 
        WHERE flight_uuid = '65009939-0877-4c36-8369-9d4bba7637f8'
    """))
    count = result.scalar()
    print(f"Points for flight 65009939-0877-4c36-8369-9d4bba7637f8: {count}")
    
    # Check all uploaded points
    result = conn.execute(text("""
        SELECT flight_uuid, COUNT(*) as count 
        FROM uploaded_track_points 
        GROUP BY flight_uuid
        ORDER BY count DESC
        LIMIT 5
    """))
    
    print("\nTop 5 flights by uploaded points count:")
    for row in result:
        print(f"  Flight {row.flight_uuid}: {row.count} points")
    
    # Check flights with source containing 'upload'
    result = conn.execute(text("""
        SELECT flight_id, source, created_at
        FROM flights
        WHERE source LIKE '%upload%'
        ORDER BY created_at DESC
        LIMIT 5
    """))
    
    print("\nRecent flights with 'upload' in source:")
    for row in result:
        print(f"  {row.flight_id} ({row.source}): {row.created_at}")