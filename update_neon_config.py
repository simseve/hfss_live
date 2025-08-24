#!/usr/bin/env python3
"""
Update configuration files for Neon DB
"""

import os
import shutil
from datetime import datetime

# New Neon DB connection string
NEON_DB_URL = "postgresql://neondb_owner:npg_WwI9ehBrZ8pg@ep-rapid-violet-a2luj2ya-pooler.eu-central-1.aws.neon.tech/neondb?sslmode=require"

def backup_file(filepath):
    """Create backup of file before modifying"""
    if os.path.exists(filepath):
        backup_path = f"{filepath}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        shutil.copy2(filepath, backup_path)
        print(f"  Backed up {filepath} to {backup_path}")
        return True
    return False

def update_env_file():
    """Update .env file with new database URL"""
    print("\nUpdating .env file...")
    
    env_file = ".env"
    if not os.path.exists(env_file):
        print("  Creating new .env file")
        with open(env_file, 'w') as f:
            f.write(f"DATABASE_URL={NEON_DB_URL}\n")
    else:
        backup_file(env_file)
        
        with open(env_file, 'r') as f:
            lines = f.readlines()
        
        updated = False
        new_lines = []
        for line in lines:
            if line.startswith('DATABASE_URL=') or line.startswith('postgresql://'):
                new_lines.append(f"DATABASE_URL={NEON_DB_URL}\n")
                updated = True
                print(f"  Updated DATABASE_URL")
            else:
                new_lines.append(line)
        
        if not updated:
            new_lines.append(f"DATABASE_URL={NEON_DB_URL}\n")
            print(f"  Added DATABASE_URL")
        
        with open(env_file, 'w') as f:
            f.writelines(new_lines)
    
    print("✓ .env file updated")

def update_alembic_ini():
    """Update alembic.ini with new database URL"""
    print("\nUpdating alembic.ini...")
    
    if not os.path.exists('alembic.ini'):
        print("  alembic.ini not found, skipping")
        return
    
    backup_file('alembic.ini')
    
    with open('alembic.ini', 'r') as f:
        content = f.read()
    
    # Replace the old URL with new one
    import re
    old_pattern = r'sqlalchemy\.url = postgresql://[^\n]+'
    new_line = f'sqlalchemy.url = {NEON_DB_URL}'
    
    content = re.sub(old_pattern, new_line, content)
    
    with open('alembic.ini', 'w') as f:
        f.write(content)
    
    print("✓ alembic.ini updated")

def update_config_py():
    """Update config.py if it exists"""
    print("\nChecking config.py...")
    
    config_files = ['config.py', 'app/config.py', 'src/config.py']
    
    for config_file in config_files:
        if os.path.exists(config_file):
            print(f"  Found {config_file}")
            backup_file(config_file)
            
            with open(config_file, 'r') as f:
                content = f.read()
            
            # Check if it uses environment variables (good practice)
            if 'os.environ' in content or 'os.getenv' in content:
                print("  ✓ config.py uses environment variables (no changes needed)")
            else:
                print("  ⚠ config.py may have hardcoded database URL")
                print("    Please update manually if needed")
            break

def create_neon_optimizations():
    """Create Neon-specific optimizations"""
    print("\nCreating Neon optimization scripts...")
    
    # Create connection pool configuration
    pool_config = """# Neon DB Connection Pool Configuration
# Add this to your database connection setup

from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

# For Neon, use NullPool to avoid connection issues with serverless
engine = create_engine(
    DATABASE_URL,
    poolclass=NullPool,  # Important for Neon
    connect_args={
        "sslmode": "require",
        "connect_timeout": 10,
        "options": "-c statement_timeout=60000"  # 60 second timeout
    }
)

# For async connections with asyncpg
async_engine = create_async_engine(
    DATABASE_URL,
    poolclass=NullPool,
    connect_args={
        "ssl": "require",
        "timeout": 10,
        "command_timeout": 60
    }
)
"""
    
    with open('neon_pool_config.py', 'w') as f:
        f.write(pool_config)
    
    print("  Created neon_pool_config.py with connection pool settings")
    
    # Create index optimization script
    index_script = """-- Neon-specific index optimizations
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
"""
    
    with open('neon_indexes.sql', 'w') as f:
        f.write(index_script)
    
    print("  Created neon_indexes.sql with performance optimizations")

def main():
    print("=== Neon DB Configuration Updater ===")
    
    update_env_file()
    update_alembic_ini()
    update_config_py()
    create_neon_optimizations()
    
    print("\n✓ Configuration updates complete!")
    print("\nNext steps:")
    print("1. Review the backup files created")
    print("2. Apply index optimizations: psql $DATABASE_URL -f neon_indexes.sql")
    print("3. Update your application's connection pool settings (see neon_pool_config.py)")
    print("4. Test your application thoroughly")
    print("\nImportant Neon considerations:")
    print("- Use NullPool for SQLAlchemy to avoid connection issues")
    print("- Neon has automatic scaling, no need for connection pooling")
    print("- Neon handles compression automatically")
    print("- Consider using Neon's branching for development/staging")

if __name__ == "__main__":
    main()