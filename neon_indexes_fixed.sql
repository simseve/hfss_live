-- Neon-specific index optimizations
-- Run this after migration to optimize performance

-- Create BRIN indexes for time-based queries (replacing TimescaleDB automatic indexes)
CREATE INDEX IF NOT EXISTS idx_live_track_points_datetime_brin 
    ON live_track_points USING BRIN (datetime);

CREATE INDEX IF NOT EXISTS idx_live_track_points_flight_datetime 
    ON live_track_points (flight_id, datetime DESC);

CREATE INDEX IF NOT EXISTS idx_uploaded_track_points_datetime_brin 
    ON uploaded_track_points USING BRIN (datetime);

CREATE INDEX IF NOT EXISTS idx_uploaded_track_points_flight_datetime 
    ON uploaded_track_points (flight_id, datetime DESC);

-- Geospatial indexes already exist (idx_live_track_points_geom, etc.)
-- Just ensure they're optimized

-- Analyze tables for query planner
ANALYZE live_track_points;
ANALYZE uploaded_track_points;
ANALYZE scoring_tracks;
ANALYZE flights;
ANALYZE races;

-- Create composite indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_flights_race_datetime 
    ON flights (race_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_scoring_tracks_flight_datetime 
    ON scoring_tracks (flight_id, datetime DESC);

-- Vacuum to clean up after migration
VACUUM ANALYZE;