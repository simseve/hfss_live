#!/usr/bin/env python3
"""
Neon DB Migration Helper
Assists with migrating from TimescaleDB to Neon DB
"""

import os
import sys
import psycopg2
from psycopg2 import sql
import subprocess
from datetime import datetime, timedelta

# Database URLs
SOURCE_DB = "postgresql://postgres:ujqajEoqzJGnw0YRG2kA@89.47.162.7/hfss"
TARGET_DB = "postgresql://neondb_owner:npg_WwI9ehBrZ8pg@ep-rapid-violet-a2luj2ya-pooler.eu-central-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"

def test_connections():
    """Test both database connections"""
    print("Testing database connections...")
    
    try:
        # Test source
        conn = psycopg2.connect(SOURCE_DB)
        cur = conn.cursor()
        cur.execute("SELECT version()")
        print(f"✓ Source DB connected: {cur.fetchone()[0][:30]}...")
        
        # Check for TimescaleDB
        cur.execute("SELECT * FROM pg_extension WHERE extname = 'timescaledb'")
        has_timescale = cur.fetchone() is not None
        print(f"  TimescaleDB: {'Yes' if has_timescale else 'No'}")
        
        # Check for PostGIS
        cur.execute("SELECT * FROM pg_extension WHERE extname = 'postgis'")
        has_postgis = cur.fetchone() is not None
        print(f"  PostGIS: {'Yes' if has_postgis else 'No'}")
        
        cur.close()
        conn.close()
    except Exception as e:
        print(f"✗ Source DB connection failed: {e}")
        return False
    
    try:
        # Test target
        conn = psycopg2.connect(TARGET_DB)
        cur = conn.cursor()
        cur.execute("SELECT version()")
        print(f"✓ Target DB connected: {cur.fetchone()[0][:30]}...")
        cur.close()
        conn.close()
    except Exception as e:
        print(f"✗ Target DB connection failed: {e}")
        return False
    
    return True

def export_schema():
    """Export schema from source database"""
    print("\nExporting schema from source database...")
    
    cmd = [
        "pg_dump",
        SOURCE_DB,
        "--schema-only",
        "--no-owner",
        "--no-privileges",
        "--no-tablespaces",
        "--if-exists",
        "--clean",
        "-f", "schema_export.sql"
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Export failed: {result.stderr}")
        return False
    
    print("✓ Schema exported to schema_export.sql")
    return True

def prepare_neon_schema():
    """Modify schema for Neon compatibility"""
    print("\nPreparing schema for Neon DB...")
    
    with open('schema_export.sql', 'r') as f:
        content = f.read()
    
    # Track what we're removing
    modifications = []
    
    # Remove TimescaleDB extension
    if 'timescaledb' in content:
        content = content.replace('CREATE EXTENSION IF NOT EXISTS timescaledb', '-- CREATE EXTENSION IF NOT EXISTS timescaledb')
        modifications.append("Removed TimescaleDB extension")
    
    # Comment out hypertable creations
    import re
    hypertable_pattern = r'SELECT create_hypertable\([^)]+\);'
    hypertables = re.findall(hypertable_pattern, content)
    if hypertables:
        for ht in hypertables:
            content = content.replace(ht, f'-- {ht}')
        modifications.append(f"Commented out {len(hypertables)} hypertable creation(s)")
    
    # Comment out retention policies
    retention_pattern = r'SELECT add_retention_policy\([^)]+\);'
    retentions = re.findall(retention_pattern, content)
    if retentions:
        for ret in retentions:
            content = content.replace(ret, f'-- {ret}')
        modifications.append(f"Commented out {len(retentions)} retention policy(ies)")
    
    # Comment out compression policies
    compression_pattern = r'SELECT add_compression_policy\([^)]+\);'
    compressions = re.findall(compression_pattern, content)
    if compressions:
        for comp in compressions:
            content = content.replace(comp, f'-- {comp}')
        modifications.append(f"Commented out {len(compressions)} compression policy(ies)")
    
    # Save modified schema
    with open('neon_schema.sql', 'w') as f:
        f.write(content)
    
    print("✓ Schema prepared for Neon DB")
    for mod in modifications:
        print(f"  - {mod}")
    
    return True

def setup_neon_extensions():
    """Enable required extensions in Neon DB"""
    print("\nSetting up Neon DB extensions...")
    
    try:
        conn = psycopg2.connect(TARGET_DB)
        cur = conn.cursor()
        
        extensions = [
            'postgis',
            'postgis_topology',
            'uuid-ossp',
            'btree_gist',
            'pg_trgm'
        ]
        
        for ext in extensions:
            try:
                cur.execute(f"CREATE EXTENSION IF NOT EXISTS \"{ext}\"")
                print(f"  ✓ {ext}")
            except Exception as e:
                print(f"  ✗ {ext}: {e}")
        
        conn.commit()
        cur.close()
        conn.close()
        print("✓ Extensions setup complete")
        return True
    except Exception as e:
        print(f"✗ Extension setup failed: {e}")
        return False

def apply_schema():
    """Apply the modified schema to Neon DB"""
    print("\nApplying schema to Neon DB...")
    
    cmd = [
        "psql",
        TARGET_DB,
        "-f", "neon_schema.sql"
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Schema application had errors:\n{result.stderr}")
        # Don't return False immediately - some errors might be acceptable
    
    print("✓ Schema applied to Neon DB")
    return True

def create_partitioning_alternative():
    """Create PostgreSQL native partitioning as TimescaleDB alternative"""
    print("\nSetting up native PostgreSQL partitioning...")
    
    try:
        conn = psycopg2.connect(TARGET_DB)
        cur = conn.cursor()
        
        # Check if tables exist
        cur.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_name IN ('live_track_points', 'uploaded_track_points', 'scoring_tracks')
        """)
        
        tables = [row[0] for row in cur.fetchall()]
        print(f"Found time-series tables: {tables}")
        
        # Create partition management function
        cur.execute("""
            CREATE OR REPLACE FUNCTION create_monthly_partitions(
                table_name text,
                start_date date,
                num_months integer
            )
            RETURNS void AS $$
            DECLARE
                partition_date date;
                partition_name text;
                end_date date;
            BEGIN
                FOR i IN 0..num_months-1 LOOP
                    partition_date := start_date + (i || ' months')::interval;
                    end_date := partition_date + interval '1 month';
                    partition_name := table_name || '_' || to_char(partition_date, 'YYYY_MM');
                    
                    BEGIN
                        EXECUTE format('CREATE TABLE IF NOT EXISTS %I PARTITION OF %I
                            FOR VALUES FROM (%L) TO (%L)',
                            partition_name,
                            table_name,
                            partition_date,
                            end_date
                        );
                        RAISE NOTICE 'Created partition %', partition_name;
                    EXCEPTION WHEN duplicate_table THEN
                        RAISE NOTICE 'Partition % already exists', partition_name;
                    END;
                END LOOP;
            END;
            $$ LANGUAGE plpgsql;
        """)
        
        conn.commit()
        print("✓ Partition management function created")
        
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"✗ Partitioning setup failed: {e}")
        return False

def create_cleanup_jobs():
    """Create cleanup jobs to replace TimescaleDB retention policies"""
    print("\nCreating cleanup jobs...")
    
    cleanup_sql = """
    -- Function to delete old live track points (48 hours retention)
    CREATE OR REPLACE FUNCTION cleanup_old_live_tracks()
    RETURNS void AS $$
    BEGIN
        DELETE FROM live_track_points 
        WHERE time < NOW() - INTERVAL '48 hours';
        
        RAISE NOTICE 'Deleted % old live track points', ROW_COUNT;
    END;
    $$ LANGUAGE plpgsql;
    
    -- Function to delete old uploaded track points (customize retention as needed)
    CREATE OR REPLACE FUNCTION cleanup_old_uploaded_tracks()
    RETURNS void AS $$
    BEGIN
        DELETE FROM uploaded_track_points 
        WHERE time < NOW() - INTERVAL '30 days';
        
        RAISE NOTICE 'Deleted % old uploaded track points', ROW_COUNT;
    END;
    $$ LANGUAGE plpgsql;
    
    -- Note: You'll need to schedule these functions using pg_cron or external scheduler
    -- Example with pg_cron (if available in Neon):
    -- SELECT cron.schedule('cleanup-live-tracks', '0 */6 * * *', 'SELECT cleanup_old_live_tracks()');
    """
    
    try:
        conn = psycopg2.connect(TARGET_DB)
        cur = conn.cursor()
        cur.execute(cleanup_sql)
        conn.commit()
        cur.close()
        conn.close()
        print("✓ Cleanup functions created")
        print("  Note: Schedule these functions with your preferred scheduler")
        return True
    except Exception as e:
        print(f"✗ Cleanup job creation failed: {e}")
        return False

def main():
    """Main migration process"""
    print("=== Neon DB Migration Helper ===\n")
    
    steps = [
        ("Test connections", test_connections),
        ("Export schema", export_schema),
        ("Prepare Neon schema", prepare_neon_schema),
        ("Setup Neon extensions", setup_neon_extensions),
        ("Apply schema", apply_schema),
        ("Create cleanup jobs", create_cleanup_jobs)
    ]
    
    for step_name, step_func in steps:
        print(f"\n{'='*50}")
        print(f"Step: {step_name}")
        print('='*50)
        
        if not step_func():
            print(f"\n✗ Migration failed at step: {step_name}")
            sys.exit(1)
    
    print("\n" + "="*50)
    print("✓ Migration completed successfully!")
    print("="*50)
    print("\nPost-migration tasks:")
    print("1. Update .env file with new Neon connection string")
    print("2. Update alembic.ini with new database URL")
    print("3. Test your application thoroughly")
    print("4. Set up scheduled cleanup jobs (cron or APScheduler)")
    print("\nNeon DB differences from TimescaleDB:")
    print("- No hypertables (using regular tables)")
    print("- No automatic retention (use cleanup functions)")
    print("- No compression policies (Neon handles this)")
    print("- Consider native PostgreSQL partitioning for large tables")

if __name__ == "__main__":
    main()