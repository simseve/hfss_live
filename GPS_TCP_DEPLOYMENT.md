# GPS TCP Server Deployment Modes

## Configuration Options

The GPS TCP server can run in 3 different modes controlled by environment variables:

### 1. **Embedded Mode** (Original - runs inside FastAPI)
```bash
# .env configuration
GPS_TCP_ENABLED=true
GPS_TCP_PORT=9090

# Run locally
uvicorn app:app --reload

# Docker (original docker-compose.yml)
docker-compose up -d
```
- TCP server runs as async task inside FastAPI process
- Single container deployment
- Good for development and simple deployments

### 2. **Separated Service Mode** (New - separate Docker container)
```bash
# .env configuration for FastAPI container
GPS_TCP_ENABLED=false  # Disable embedded server in FastAPI
GPS_TCP_PORT=9090

# .env configuration for GPS TCP container
GPS_TCP_ENABLED=true
GPS_TCP_HOST=0.0.0.0
GPS_TCP_PORT=9090

# Docker deployment
docker-compose -f docker-compose-gps.yml up -d
```
- TCP server runs in separate container
- Can scale independently
- Better for production with high GPS traffic

### 3. **Disabled Mode** (No GPS TCP server)
```bash
# .env configuration
GPS_TCP_ENABLED=false
GPS_TCP_PORT=9090  # Still set but not used

# Run locally or Docker
uvicorn app:app --reload
# or
docker-compose up -d
```
- No TCP server runs anywhere
- FastAPI runs without GPS tracking capability

## Local Development Options

### Run GPS TCP Server Standalone (Outside Docker)
```bash
# Terminal 1: Run Redis (required)
redis-server

# Terminal 2: Run PostgreSQL (required)
# Make sure your local PostgreSQL is running

# Terminal 3: Run GPS TCP server standalone
export GPS_TCP_ENABLED=true
export GPS_TCP_PORT=9090
export DATABASE_URL="postgresql://user:pass@localhost/dbname"
export REDIS_URL="redis://localhost:6379"
python tcp_server/standalone_server.py

# Terminal 4: Run FastAPI with embedded server disabled
export GPS_TCP_ENABLED=false
uvicorn app:app --reload --port 8000
```

### Run GPS TCP Server Embedded in FastAPI (Local)
```bash
# Terminal 1: Run Redis
redis-server

# Terminal 2: Run PostgreSQL
# Make sure your local PostgreSQL is running

# Terminal 3: Run FastAPI with embedded GPS server
export GPS_TCP_ENABLED=true
export GPS_TCP_PORT=9090
uvicorn app:app --reload --port 8000
```

## Environment Variable Reference

| Variable | Description | Default | Used By |
|----------|-------------|---------|---------|
| `GPS_TCP_ENABLED` | Enable/disable GPS TCP server | `false` | Both FastAPI and Standalone |
| `GPS_TCP_PORT` | Port for GPS TCP server | `9090` | Both |
| `GPS_TCP_HOST` | Host to bind GPS TCP server | `0.0.0.0` | Standalone only |
| `DATABASE_URL` | PostgreSQL connection string | Required | Both |
| `REDIS_URL` | Redis connection string | `redis://localhost:6379` | Both |
| `PROD` | Production mode flag | `false` | Both |

## Quick Decision Guide

### Use **Embedded Mode** when:
- Developing locally
- Low GPS device count (<100 devices)
- Want simplest deployment
- Don't need to scale GPS processing separately

### Use **Separated Service Mode** when:
- Production environment
- High GPS device count (>100 devices)
- Need to scale GPS processing independently
- Want to update GPS server without affecting API
- Need better fault isolation

### Use **Disabled Mode** when:
- Don't need GPS tracking
- Testing other features
- Running API-only deployment

## Testing Different Modes

### Test Embedded Mode (Local)
```bash
# Start with embedded server
export GPS_TCP_ENABLED=true
export GPS_TCP_PORT=9090
uvicorn app:app --reload

# Test connection
nc -v localhost 9090

# Check status
curl http://localhost:8000/gps-tcp/status
```

### Test Standalone Mode (Local)
```bash
# Terminal 1: Start standalone GPS server
export GPS_TCP_ENABLED=true
export GPS_TCP_PORT=9090
export DATABASE_URL="postgresql://..."
export REDIS_URL="redis://localhost:6379"
python tcp_server/standalone_server.py

# Terminal 2: Start FastAPI without embedded server
export GPS_TCP_ENABLED=false
uvicorn app:app --reload

# Test connection
nc -v localhost 9090

# Check external server status
curl http://localhost:8000/api/gps-tcp/external/status
```

### Test Separated Docker Mode
```bash
# Deploy with separated services
./deploy-gps-separated.sh

# Test connection
nc -v localhost 9090

# Check status
curl http://localhost:5012/api/gps-tcp/external/status
```

## Migration Path

To migrate from embedded to separated mode:

1. **Test locally first:**
   ```bash
   # Run standalone server
   python tcp_server/standalone_server.py
   
   # Verify it connects to DB and Redis
   # Check logs for successful initialization
   ```

2. **Deploy to dev/staging:**
   ```bash
   # Update .env
   GPS_TCP_ENABLED=false  # for FastAPI
   
   # Deploy separated services
   docker-compose -f docker-compose-gps.yml up -d
   ```

3. **Monitor and verify:**
   - Check `/api/gps-tcp/external/status` endpoint
   - Monitor Redis queue for GPS data flow
   - Check logs: `docker-compose -f docker-compose-gps.yml logs -f gps-tcp-server`

4. **Rollback if needed:**
   ```bash
   # Re-enable embedded mode
   GPS_TCP_ENABLED=true
   
   # Deploy original configuration
   docker-compose up -d
   ```

## Monitoring

### Check GPS TCP Server Status
```bash
# Embedded mode
curl http://localhost:8000/gps-tcp/status

# Separated mode
curl http://localhost:8000/api/gps-tcp/external/status

# Health check
curl http://localhost:8000/health
```

### View Logs
```bash
# Embedded mode (local)
# Logs appear in FastAPI console

# Separated mode (Docker)
docker-compose -f docker-compose-gps.yml logs -f gps-tcp-server

# Standalone mode (local)
# Logs appear in terminal running standalone_server.py
```

### Monitor Redis Queue
```bash
# Check queue status
curl http://localhost:8000/queue/status

# Connect to Redis CLI
redis-cli
> LLEN track_points_queue
> MONITOR  # Watch commands in real-time
```