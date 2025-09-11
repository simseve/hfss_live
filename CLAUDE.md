# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

### Local Development
```bash
# Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run the application
uvicorn app:app --reload

# Run with specific host/port
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

### Docker Deployment
```bash
# Build and start containers
docker-compose up -d

# Development environment (host networking)
docker-compose -f docker-compose-dev.yml up -d

# Debug environment (with debugpy on port 5678)
docker-compose -f docker-compose.debug.yml up -d

# View logs
docker-compose logs -f
```

### Database Management
```bash
# Create new migration
alembic revision -m "description" --autogenerate

# Apply migrations
alembic upgrade head

# Database backup/restore
./scripts/pg_backup.sh
./scripts/pg_restore.sh
```

### Testing
```bash
# Run individual test files
python test_api_endpoint.py
python tests/test_mvt.py
python tests/test_scoring_batch.py

# Run all tests with pytest
pytest tests/
pytest test_*.py
```

## Architecture Overview

### Core Stack
- **FastAPI** async web framework with WebSocket support
- **PostgreSQL** with **PostGIS** and **TimescaleDB** extensions for geospatial time-series data
- **Redis** for caching, rate limiting, and queue management
- **MinIO** for object storage
- **SQLAlchemy** with GeoAlchemy2 for ORM

### Key Components

**Time-Series Data**:
- TimescaleDB hypertables for `live_track_points`, `uploaded_track_points`, and `scoring_tracks`
- Automatic 48-hour retention for live flight data
- Batch insertion via Redis queue system

**Authentication & Security**:
- JWT-based authentication (`api/auth.py`)
- Tracking tokens for live tracking endpoints
- Rate limiting: 100 requests per 5 seconds (configurable)
- bcrypt password hashing

**Real-time Features**:
- WebSocket connections (`ws_conn.py`) with ConnectionManager
- Background tracking updates every 10 seconds
- Push notifications via Firebase FCM and Expo

**Background Services**:
- APScheduler for scheduled tasks (cleanup at midnight)
- Redis queue processors for batch point insertions
- Automatic database cleanup of old data

**Geospatial Features**:
- MVT (Mapbox Vector Tile) endpoint for map visualization
- PostGIS for spatial queries and indexing
- Track simplification and analysis

### API Endpoints

**Health & Monitoring**:
- `/health`: Comprehensive health check (DB, Redis, queues)
- `/queue/status`: Redis queue statistics

**Authentication**:
- `/auth/login`, `/auth/refresh`, `/auth/logout`
- JWT tokens with refresh capability

**Live Tracking**:
- `/api/v2/live/add_live_track_points`: Batch point insertion
- WebSocket: `/ws/{race_id}`: Real-time updates

**Data Management**:
- MVT tiles: `/mvt/{race_id}/{z}/{x}/{y}`
- Flight scoring and analysis endpoints

### Configuration

**Environment Variables**:
- `DATABASE_URL`: PostgreSQL connection string
- `REDIS_URL`: Redis connection (defaults to localhost:6379)
- `FIREBASE_SERVICE_ACCOUNT_PATH`: Path to Firebase credentials
- `SECRET_KEY`: JWT signing key
- `PROD`: Production mode flag (affects Redis hostname)
- `MINIO_*`: MinIO configuration

**Key Settings** (`config.py`):
- Pydantic settings with validation
- Environment-based configuration
- CORS configuration for web clients

### Data Models

**Core Models**:
- **Race**: Competition management with timezone support
- **Flight**: Live and uploaded track data
- **LiveTrackPoint/UploadedTrackPoint**: Time-series location data with altitude
- **NotificationTokenDB**: Push notification management
- **User**: Authentication and profile data

**TimescaleDB Optimizations**:
- Hypertables with time-based partitioning
- Automatic compression policies
- Efficient time-range queries

### Development Notes

**Redis Queue System**:
- Located in `redis_queue_system/`
- Handles batch processing of track points
- Monitors queue health and processing times

**WebSocket Management**:
- ConnectionManager handles client connections per race
- Automatic broadcast of flight updates
- Connection cleanup on disconnect

**Firebase Integration**:
- Optional FCM support (graceful fallback if not configured)
- Notification token management
- Both Firebase and Expo push notification support

**Security Considerations**:
- Never commit `.env` files
- Secure `alembic.ini` database credentials in production
- Use environment variables for all sensitive configuration
- "command docker-compose is deprecated"