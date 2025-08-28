-- Flight Update Triggers for Automatic Flight Statistics
-- This script creates triggers to automatically update flight records when points are inserted
-- Deploy directly to Neon primary endpoint

-- Drop existing triggers if they exist (safe for re-running)
DROP TRIGGER IF EXISTS update_flight_on_live_insert ON live_track_points;
DROP TRIGGER IF EXISTS update_flight_on_upload_insert ON uploaded_track_points;
DROP FUNCTION IF EXISTS update_flight_from_live_points() CASCADE;
DROP FUNCTION IF EXISTS update_flight_from_upload_points() CASCADE;

-- ============================================
-- TRIGGER FOR LIVE_TRACK_POINTS
-- ============================================
CREATE OR REPLACE FUNCTION update_flight_from_live_points()
RETURNS TRIGGER AS $$
BEGIN
    -- Update flight statistics for live tracking points
    UPDATE flights 
    SET 
        -- Update last_fix with latest point data
        last_fix = json_build_object(
            'lat', NEW.lat,
            'lon', NEW.lon,
            'elevation', NEW.elevation,
            'datetime', NEW.datetime::text
        ),
        -- Only update first_fix if it's null (first point for this flight)
        first_fix = CASE 
            WHEN first_fix IS NULL THEN 
                json_build_object(
                    'lat', NEW.lat,
                    'lon', NEW.lon,
                    'elevation', NEW.elevation,
                    'datetime', NEW.datetime::text
                )
            ELSE first_fix
        END,
        -- Increment total points counter
        total_points = COALESCE(total_points, 0) + 1
    WHERE flight_id = NEW.flight_id;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ============================================
-- TRIGGER FOR UPLOADED_TRACK_POINTS
-- ============================================
CREATE OR REPLACE FUNCTION update_flight_from_upload_points()
RETURNS TRIGGER AS $$
BEGIN
    -- Update flight statistics for uploaded track points
    UPDATE flights 
    SET 
        -- Update last_fix with latest point data
        last_fix = json_build_object(
            'lat', NEW.lat,
            'lon', NEW.lon,
            'elevation', NEW.elevation,
            'datetime', NEW.datetime::text
        ),
        -- Only update first_fix if it's null
        first_fix = CASE 
            WHEN first_fix IS NULL THEN 
                json_build_object(
                    'lat', NEW.lat,
                    'lon', NEW.lon,
                    'elevation', NEW.elevation,
                    'datetime', NEW.datetime::text
                )
            ELSE first_fix
        END,
        -- Increment total points counter
        total_points = COALESCE(total_points, 0) + 1
    WHERE flight_id = NEW.flight_id;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Note: Flymaster points now go directly to live_track_points
-- The triggers above will handle flight updates for all tracking data

-- ============================================
-- CREATE TRIGGERS
-- ============================================

-- Trigger for live_track_points
CREATE TRIGGER update_flight_on_live_insert
AFTER INSERT ON live_track_points
FOR EACH ROW 
EXECUTE FUNCTION update_flight_from_live_points();

-- Trigger for uploaded_track_points
CREATE TRIGGER update_flight_on_upload_insert
AFTER INSERT ON uploaded_track_points
FOR EACH ROW 
EXECUTE FUNCTION update_flight_from_upload_points();

-- ============================================
-- OPTIMIZED BATCH VERSION (Optional - for better performance)
-- ============================================
-- If you frequently insert many points at once, consider using statement-level triggers
-- Uncomment below to use batch processing instead

/*
-- Statement-level trigger for batch processing (more efficient for bulk inserts)
CREATE OR REPLACE FUNCTION update_flight_from_live_batch()
RETURNS TRIGGER AS $$
BEGIN
    -- Update all affected flights in one query
    WITH flight_stats AS (
        SELECT 
            flight_id,
            COUNT(*) as new_points,
            MAX(datetime) as latest_time,
            MIN(datetime) as earliest_time,
            LAST_VALUE(lat) OVER (PARTITION BY flight_id ORDER BY datetime 
                ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) as last_lat,
            LAST_VALUE(lon) OVER (PARTITION BY flight_id ORDER BY datetime 
                ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) as last_lon,
            LAST_VALUE(alt) OVER (PARTITION BY flight_id ORDER BY datetime 
                ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) as last_alt,
            FIRST_VALUE(lat) OVER (PARTITION BY flight_id ORDER BY datetime) as first_lat,
            FIRST_VALUE(lon) OVER (PARTITION BY flight_id ORDER BY datetime) as first_lon,
            FIRST_VALUE(alt) OVER (PARTITION BY flight_id ORDER BY datetime) as first_alt
        FROM new_table
        GROUP BY flight_id, lat, lon, alt, datetime
    ),
    aggregated AS (
        SELECT 
            flight_id,
            SUM(new_points) as total_new_points,
            MAX(latest_time) as max_time,
            MIN(earliest_time) as min_time,
            FIRST_VALUE(last_lat) OVER (PARTITION BY flight_id ORDER BY latest_time DESC) as final_lat,
            FIRST_VALUE(last_lon) OVER (PARTITION BY flight_id ORDER BY latest_time DESC) as final_lon,
            FIRST_VALUE(last_alt) OVER (PARTITION BY flight_id ORDER BY latest_time DESC) as final_alt,
            FIRST_VALUE(first_lat) OVER (PARTITION BY flight_id ORDER BY earliest_time) as initial_lat,
            FIRST_VALUE(first_lon) OVER (PARTITION BY flight_id ORDER BY earliest_time) as initial_lon,
            FIRST_VALUE(first_alt) OVER (PARTITION BY flight_id ORDER BY earliest_time) as initial_alt
        FROM flight_stats
        GROUP BY flight_id
    )
    UPDATE flights f
    SET 
        last_fix = json_build_object(
            'lat', a.final_lat,
            'lon', a.final_lon,
            'elevation', a.final_alt,
            'datetime', a.max_time::text
        ),
        first_fix = COALESCE(
            f.first_fix,
            json_build_object(
                'lat', a.initial_lat,
                'lon', a.initial_lon,
                'elevation', a.initial_alt,
                'datetime', a.min_time::text
            )
        ),
        total_points = COALESCE(f.total_points, 0) + a.total_new_points
    FROM aggregated a
    WHERE f.flight_id = a.flight_id;
    
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

-- Drop row-level trigger and create statement-level trigger for batch processing
DROP TRIGGER IF EXISTS update_flight_on_live_insert ON live_track_points;
CREATE TRIGGER update_flight_batch_live
AFTER INSERT ON live_track_points
REFERENCING NEW TABLE AS new_table
FOR EACH STATEMENT 
EXECUTE FUNCTION update_flight_from_live_batch();
*/

-- ============================================
-- VERIFICATION QUERIES
-- ============================================
-- Run these to verify triggers are working:

-- Check if triggers are created:
/*
SELECT 
    tgname as trigger_name,
    tgrelid::regclass as table_name,
    proname as function_name
FROM pg_trigger t
JOIN pg_proc p ON t.tgfoid = p.oid
WHERE tgname LIKE 'update_flight%'
ORDER BY tgname;
*/

-- Test the trigger with sample data:
/*
-- Insert a test point and check if flight is updated
INSERT INTO live_track_points (flight_id, datetime, lat, lon, alt)
VALUES ('test-flight-123', NOW(), 45.123, 6.789, 1500);

-- Check the flight record
SELECT flight_id, first_fix, last_fix, total_points
FROM flights
WHERE flight_id = 'test-flight-123';
*/