# Database Switching Guide

## Current Setup
You now have both Neon DB (cloud) and your original TimescaleDB configured. The system is fully backward compatible.

## Quick Switch Between Databases

### To use Neon DB (current):
```bash
# Already configured in .env
USE_NEON=True
DATABASE_URI=postgresql://neondb_owner:npg_WwI9ehBrZ8pg@ep-rapid-violet-a2luj2ya-pooler.eu-central-1.aws.neon.tech/neondb?sslmode=require
DATABASE_URL=postgresql://neondb_owner:npg_WwI9ehBrZ8pg@ep-rapid-violet-a2luj2ya-pooler.eu-central-1.aws.neon.tech/neondb?sslmode=require
```

### To switch back to TimescaleDB:
Edit `.env` and uncomment Option 1, comment Option 2:
```bash
# Option 1: Original TimescaleDB (local)
DATABASE_URI=postgresql://py_ll_user:7JijoHPvHXyHjajDK00V@192.168.68.130/hfss
DATABASE_URL=postgresql://py_ll_user:7JijoHPvHXyHjajDK00V@192.168.68.130/hfss
USE_NEON=False

# Option 2: Neon DB (cloud) - COMMENTED OUT
# DATABASE_URI=postgresql://neondb_owner:npg_WwI9ehBrZ8pg@ep-rapid-violet-a2luj2ya-pooler.eu-central-1.aws.neon.tech/neondb?sslmode=require
# DATABASE_URL=postgresql://neondb_owner:npg_WwI9ehBrZ8pg@ep-rapid-violet-a2luj2ya-pooler.eu-central-1.aws.neon.tech/neondb?sslmode=require
# USE_NEON=True
```

## Using the Database Helper

The `database_helper.py` module automatically detects which database you're using and configures connections appropriately:

```python
from database_helper import get_sync_engine, get_async_engine

# Sync connection
engine = get_sync_engine()

# Async connection  
async_engine = get_async_engine()
```

## Key Differences

### Neon DB
- ✅ Cloud-hosted, auto-scaling
- ✅ Automatic backups
- ✅ PostGIS support
- ❌ No TimescaleDB hypertables
- ❌ No automatic retention policies
- 📝 Uses NullPool for connections
- 📝 Manual cleanup functions instead of retention policies

### TimescaleDB (Original)
- ✅ Hypertables for time-series data
- ✅ Automatic retention policies
- ✅ Compression policies
- ✅ Local/self-hosted
- 📝 Uses connection pooling
- 📝 48-hour automatic cleanup for live data

## Migration Status

### Completed
- ✅ Schema migrated (tables, indexes, triggers)
- ✅ PostGIS extension enabled
- ✅ Cleanup functions created
- ✅ Connection configurations updated
- ✅ Backward compatibility maintained

### Data Migration
- ⚠️ No data was migrated (fresh start)
- To migrate data later, use: `pg_dump` with `--data-only` flag

## Backup Files Created
- `.env.backup_*` - Original environment configuration
- `alembic.ini.backup_*` - Original Alembic configuration  
- `config.py.backup_*` - Original config file
- `schema_export.sql` - Full schema from TimescaleDB
- `neon_schema.sql` - Modified schema for Neon

## Testing Connection

```bash
# Test current database connection
python database_helper.py

# Check which database is active
python -c "from database_helper import is_neon_db; print(f'Using Neon: {is_neon_db()}')"
```

## Troubleshooting

### Connection Issues
1. Check `.env` file has correct DATABASE_URI/DATABASE_URL
2. Verify USE_NEON flag matches your intention
3. For Neon: Ensure you're using the pooler connection string
4. For TimescaleDB: Ensure local database is running

### Performance
- Neon: Use `NullPool` to avoid connection issues
- TimescaleDB: Standard connection pooling works fine

### Missing Features in Neon
- Hypertables → Use regular tables with BRIN indexes
- Retention policies → Use cleanup functions with scheduler
- Compression → Neon handles automatically