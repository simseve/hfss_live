-- Neon-specific index optimizations
-- Run this after migration to optimize performance

-- Create indexes for time-based queries (replacing TimescaleDB automatic indexes)
CREATE INDEX IF NOT EXISTS idx_live_track_points_time 
    ON live_track_points USING BRIN (time);

CREATE INDEX IF NOT EXISTS idx_live_track_points_flight_time 
    ON live_track_points (flight_id, time DESC);

CREATE INDEX IF NOT EXISTS idx_uploaded_track_points_time 
    ON uploaded_track_points USING BRIN (time);

CREATE INDEX IF NOT EXISTS idx_uploaded_track_points_flight_time 
    ON uploaded_track_points (flight_id, time DESC);

-- Create indexes for geospatial queries
CREATE INDEX IF NOT EXISTS idx_live_track_points_location 
    ON live_track_points USING GIST (location);

CREATE INDEX IF NOT EXISTS idx_uploaded_track_points_location 
    ON uploaded_track_points USING GIST (location);

-- Analyze tables for query planner
ANALYZE live_track_points;
ANALYZE uploaded_track_points;
ANALYZE scoring_tracks;
