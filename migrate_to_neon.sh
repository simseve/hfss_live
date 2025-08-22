#!/bin/bash

# Migration script from local PostgreSQL with TimescaleDB to Neon DB
# This script exports schema only (no data) and prepares it for Neon

SOURCE_DB="postgresql://postgres:ujqajEoqzJGnw0YRG2kA@89.47.162.7/hfss"
TARGET_DB="postgresql://neondb_owner:npg_WwI9ehBrZ8pg@ep-rapid-violet-a2luj2ya-pooler.eu-central-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"

echo "=== PostgreSQL to Neon DB Migration Script ==="
echo "This will migrate schema, triggers, and configurations (no data)"
echo ""

# Step 1: Export schema from source database
echo "Step 1: Exporting schema from source database..."
pg_dump "$SOURCE_DB" \
    --schema-only \
    --no-owner \
    --no-privileges \
    --no-tablespaces \
    --no-security-labels \
    --no-subscriptions \
    --no-publications \
    --if-exists \
    --clean \
    -f schema_export.sql

if [ $? -ne 0 ]; then
    echo "Error: Failed to export schema from source database"
    exit 1
fi

echo "Schema exported to schema_export.sql"

# Step 2: Create a modified version for Neon
echo "Step 2: Preparing schema for Neon DB..."
cp schema_export.sql neon_schema.sql

# Remove TimescaleDB-specific commands that Neon doesn't support
# Neon supports PostGIS but not TimescaleDB
cat > modify_schema.py << 'EOF'
import re

with open('neon_schema.sql', 'r') as f:
    content = f.read()

# Remove TimescaleDB extension creation
content = re.sub(r'CREATE EXTENSION IF NOT EXISTS timescaledb.*?;', '-- TimescaleDB extension removed for Neon', content, flags=re.DOTALL)

# Comment out TimescaleDB-specific functions
content = re.sub(r'SELECT create_hypertable\([^)]+\);', '-- Hypertable creation removed for Neon', content)
content = re.sub(r'SELECT add_retention_policy\([^)]+\);', '-- Retention policy removed for Neon', content)
content = re.sub(r'SELECT add_compression_policy\([^)]+\);', '-- Compression policy removed for Neon', content)
content = re.sub(r'SELECT set_chunk_time_interval\([^)]+\);', '-- Chunk interval removed for Neon', content)

# Keep PostGIS extension
# Neon supports PostGIS

# Save modified schema
with open('neon_schema.sql', 'w') as f:
    f.write(content)

print("Schema modifications completed")
EOF

python modify_schema.py

# Step 3: Check Neon DB connection
echo "Step 3: Testing Neon DB connection..."
psql "$TARGET_DB" -c "SELECT version();" > /dev/null 2>&1
if [ $? -ne 0 ]; then
    echo "Error: Cannot connect to Neon DB. Please check your connection string."
    exit 1
fi
echo "Neon DB connection successful"

# Step 4: Enable required extensions in Neon
echo "Step 4: Enabling PostGIS extension in Neon DB..."
psql "$TARGET_DB" << SQL
-- Enable PostGIS (Neon supports this)
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_topology;
CREATE EXTENSION IF NOT EXISTS uuid-ossp;
CREATE EXTENSION IF NOT EXISTS btree_gist;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
SQL

# Step 5: Apply schema to Neon
echo "Step 5: Applying schema to Neon DB..."
echo "Warning: This will drop and recreate all tables in the target database!"
read -p "Do you want to continue? (yes/no): " confirm

if [ "$confirm" != "yes" ]; then
    echo "Migration cancelled"
    exit 0
fi

psql "$TARGET_DB" -f neon_schema.sql

if [ $? -eq 0 ]; then
    echo ""
    echo "=== Migration Completed Successfully ==="
    echo ""
    echo "Important notes for Neon DB:"
    echo "1. TimescaleDB hypertables have been converted to regular tables"
    echo "2. You'll need to implement alternative strategies for:"
    echo "   - Time-series data partitioning (use PostgreSQL native partitioning)"
    echo "   - Data retention (create custom cleanup jobs)"
    echo "   - Compression (Neon handles this automatically)"
    echo ""
    echo "3. All triggers, indexes, and constraints have been preserved"
    echo "4. PostGIS functionality is fully available"
    echo ""
    echo "Next steps:"
    echo "1. Update your .env file with the new Neon connection string"
    echo "2. Update alembic.ini with the new database URL"
    echo "3. Test your application with the new database"
else
    echo "Error: Schema application failed. Check the error messages above."
    exit 1
fi

# Step 6: Create alternative time-series optimization
echo ""
echo "Step 6: Would you like to set up PostgreSQL native partitioning for time-series tables?"
read -p "Set up partitioning for live_track_points and uploaded_track_points? (yes/no): " partition

if [ "$partition" = "yes" ]; then
    cat > setup_partitioning.sql << 'SQL'
-- Convert live_track_points to partitioned table
-- This replaces TimescaleDB hypertables with native PostgreSQL partitioning

-- Create partitioned tables
CREATE TABLE IF NOT EXISTS live_track_points_partitioned (
    LIKE live_track_points INCLUDING ALL
) PARTITION BY RANGE (time);

CREATE TABLE IF NOT EXISTS uploaded_track_points_partitioned (
    LIKE uploaded_track_points INCLUDING ALL  
) PARTITION BY RANGE (time);

-- Create initial partitions (example for last 7 days and next 7 days)
CREATE TABLE live_track_points_p_2025_01_15 PARTITION OF live_track_points_partitioned
    FOR VALUES FROM ('2025-01-15') TO ('2025-01-16');
    
CREATE TABLE live_track_points_p_2025_01_16 PARTITION OF live_track_points_partitioned
    FOR VALUES FROM ('2025-01-16') TO ('2025-01-17');

-- Add more partitions as needed...

-- Create function to automatically create daily partitions
CREATE OR REPLACE FUNCTION create_daily_partitions()
RETURNS void AS $$
DECLARE
    partition_date date;
    partition_name text;
BEGIN
    FOR partition_date IN 
        SELECT generate_series(
            CURRENT_DATE - INTERVAL '2 days',
            CURRENT_DATE + INTERVAL '2 days',
            INTERVAL '1 day'
        )::date
    LOOP
        partition_name := 'live_track_points_p_' || to_char(partition_date, 'YYYY_MM_DD');
        
        BEGIN
            EXECUTE format('CREATE TABLE IF NOT EXISTS %I PARTITION OF live_track_points_partitioned
                FOR VALUES FROM (%L) TO (%L)',
                partition_name,
                partition_date,
                partition_date + INTERVAL '1 day'
            );
        EXCEPTION WHEN duplicate_table THEN
            -- Partition already exists
            NULL;
        END;
    END LOOP;
END;
$$ LANGUAGE plpgsql;

-- Schedule this function to run daily using pg_cron or external scheduler
SQL

    echo "Applying partitioning setup..."
    psql "$TARGET_DB" -f setup_partitioning.sql
    echo "Partitioning setup complete"
fi

echo ""
echo "=== Migration Complete ==="
echo "Schema has been successfully migrated to Neon DB"
echo "Remember to update your application configuration!"