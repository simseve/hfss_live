# Read Replica Configuration Guide

## Overview
This application supports read replica database configuration to improve performance and scalability by distributing read operations to a read-only replica while keeping write operations on the primary database.

## Architecture

### Database Routing
- **Primary Database**: Handles all write operations (INSERT, UPDATE, DELETE)
- **Read Replica**: Handles read-heavy operations (SELECT queries)

### Optimized Endpoints

#### Read Operations (Using Replica)
- WebSocket endpoints (`/ws/track/{race_id}`) - Real-time tracking data
- Background tracking updates - Periodic data fetching
- GET endpoints:
  - `/flights` - Flight listings
  - `/live/points/{flight_uuid}` - Live tracking points
  - `/live/users` - Active user listings
  - `/mvt/{z}/{x}/{y}` - Map vector tiles
  - All other read-only endpoints

#### Write Operations (Using Primary)
- POST endpoints:
  - `/live` - Live tracking data insertion
  - `/upload` - Track upload
  - `/notifications/*` - Notification management
- DELETE endpoints - Track deletion
- All data modification operations

## Setup Instructions

### 1. Create a Read Replica in Neon

1. Log into your Neon dashboard
2. Navigate to your project
3. Go to "Branches" or "Read Replicas"
4. Create a new read-only replica
5. Copy the connection string

### 2. Configure Environment Variables

Add to your `.env` file:

```bash
# Primary database (existing)
DATABASE_URI=postgresql://user:pass@host-primary.neon.tech/dbname?sslmode=require

# Read replica (new)
DATABASE_REPLICA_URI=postgresql://user:pass@host-replica.neon.tech/dbname?sslmode=require
```

**Note**: If `DATABASE_REPLICA_URI` is not set, the application will use the primary database for all operations.

### 3. Connection Pool Configuration

The application automatically configures optimal connection pools:

#### Neon with Pooler (-pooler endpoints)
- **Primary**: 200 pool size, 300 overflow (500 total)
- **Replica**: 250 pool size, 350 overflow (600 total)

#### Direct Connections
- Uses NullPool to avoid connection issues

#### Traditional PostgreSQL
- **Primary**: 50 pool size, 50 overflow
- **Replica**: 75 pool size, 75 overflow

## Testing the Configuration

Run the test script to verify your setup:

```bash
python test_replica_connection.py
```

Expected output:
```
✅ Replica configuration detected
   Primary host: host-primary.neon.tech
   Replica host: host-replica.neon.tech

✅ Primary connected to: your_database
   Is read-only replica: No
   Write test: ✅ Can write

✅ Replica database connection successful
   Is read-only replica: Yes
   Read test: ✅ Can read (X tables in public schema)
```

## Monitoring

The application logs replica usage on startup:
- Primary database connection status
- Replica database connection status
- Fallback notifications if replica is unavailable

## Performance Benefits

With 15,000 concurrent users during live events:

1. **Read Distribution**: ~90% of requests are reads, offloaded to replica
2. **WebSocket Scalability**: All WebSocket data fetching uses replica
3. **Background Tasks**: Tracking updates read from replica
4. **Write Isolation**: Primary database focused on writes only

## Troubleshooting

### Replica Not Detected
- Check `DATABASE_REPLICA_URI` is set correctly
- Verify connection string includes proper SSL mode
- Test connection with `psql` or database client

### SSL Connection Errors
- Ensure `?sslmode=require` in connection strings
- Check network connectivity to Neon endpoints

### Performance Issues
- Monitor connection pool usage
- Check if using pooler endpoints (-pooler)
- Verify replica is in same region as application

## Code Usage

### For Developers

When creating new endpoints:

```python
# For read operations
from database.db_replica import get_replica_db

@router.get("/my-endpoint")
async def read_data(db: Session = Depends(get_replica_db)):
    # Read operations here
    pass

# For write operations
from database.db_replica import get_primary_db

@router.post("/my-endpoint")
async def write_data(db: Session = Depends(get_primary_db)):
    # Write operations here
    pass
```

### Background Tasks

```python
from database.db_replica import ReplicaSession, PrimarySession

# For reads
with ReplicaSession() as db:
    data = db.query(Model).all()

# For writes
with PrimarySession() as db:
    db.add(new_record)
    db.commit()
```