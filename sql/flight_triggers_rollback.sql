-- Rollback script for flight update triggers
-- Use this if you need to remove the triggers and restore manual updates

-- Drop all flight update triggers
DROP TRIGGER IF EXISTS update_flight_on_live_insert ON live_track_points;
DROP TRIGGER IF EXISTS update_flight_on_upload_insert ON uploaded_track_points;
DROP TRIGGER IF EXISTS update_flight_on_flymaster_insert ON flymaster;
DROP TRIGGER IF EXISTS update_flight_batch_live ON live_track_points;
DROP TRIGGER IF EXISTS update_flight_batch_upload ON uploaded_track_points;

-- Drop all flight update functions
DROP FUNCTION IF EXISTS update_flight_from_live_points() CASCADE;
DROP FUNCTION IF EXISTS update_flight_from_upload_points() CASCADE;
DROP FUNCTION IF EXISTS update_flight_from_flymaster_points() CASCADE;
DROP FUNCTION IF EXISTS update_flight_from_live_batch() CASCADE;
DROP FUNCTION IF EXISTS update_flight_from_upload_batch() CASCADE;

-- Verify triggers are removed
SELECT 
    'Remaining triggers:' as info,
    COUNT(*) as count
FROM pg_trigger 
WHERE tgname LIKE 'update_flight%';

-- List any remaining triggers (should be empty)
SELECT 
    tgname as trigger_name,
    tgrelid::regclass as table_name
FROM pg_trigger 
WHERE tgname LIKE 'update_flight%';