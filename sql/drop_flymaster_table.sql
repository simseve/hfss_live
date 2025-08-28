-- Script to remove Flymaster hypertable and related objects
-- Flymaster data will be stored in live_track_points instead

-- Drop triggers first
DROP TRIGGER IF EXISTS trig_update_flymaster_geom ON flymaster;
DROP TRIGGER IF EXISTS update_flight_on_flymaster_insert ON flymaster;
DROP TRIGGER IF EXISTS ts_insert_blocker ON flymaster;

-- Drop function
DROP FUNCTION IF EXISTS update_flymaster_track_point_geom() CASCADE;
DROP FUNCTION IF EXISTS update_flight_from_flymaster_points() CASCADE;

-- Drop indexes (they will be dropped with table, but being explicit)
DROP INDEX IF EXISTS idx_flymaster_datetime;
DROP INDEX IF EXISTS idx_flymaster_device_id;
DROP INDEX IF EXISTS idx_flymaster_device_datetime;
DROP INDEX IF EXISTS idx_flymaster_geom;

-- Drop the hypertable
DROP TABLE IF EXISTS flymaster CASCADE;

-- Verify removal
SELECT 
    'Flymaster table removed' as status,
    NOT EXISTS (
        SELECT 1 FROM information_schema.tables 
        WHERE table_schema = 'public' 
        AND table_name = 'flymaster'
    ) as removed_successfully;