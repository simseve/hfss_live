# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

### Local Development
```bash
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

# Development environment
docker-compose -f docker-compose-dev.yml up -d

# Debug environment
docker-compose -f docker-compose.debug.yml up -d
```

### Database Management
```bash
# Create new migration
alembic revision -m "description" --autogenerate

# Apply migrations
alembic upgrade head

# Database backup/restore (scripts available)
./scripts/pg_backup.sh
./scripts/pg_restore.sh
```

### Testing
Tests are integration-focused and run as standalone scripts:
```bash
# Individual test files
python test_api_endpoint.py
python test_firebase_setup.py
python test_notifications.py

# Tests directory
python tests/test_mvt.py
python tests/test_scoring_batch.py

# Or with pytest
pytest tests/
pytest test_*.py
```

## Architecture Overview

### Core Application Structure
- **FastAPI application** (`app.py`) with lifespan management for background tasks
- **Database layer** (`database/`) using SQLAlchemy with TimescaleDB for time-series data
- **API routes** (`api/`) organized by functionality (tracking, scoring, authentication)
- **Background services** for tracking updates and cleanup tasks

### Key Components

**Time-Series Data**:
- Uses PostgreSQL with TimescaleDB extension
- Hypertables for `live_track_points`, `uploaded_track_points`, and `scoring_tracks`
- Automatic data cleanup for live flights (48-hour retention)

**Authentication**:
- JWT-based authentication (`api/auth.py`)
- Tracking tokens for live tracking endpoints
- Rate limiting with Redis backend

**Real-time Features**:
- WebSocket connections for live tracking (`ws_conn.py`)
- Background periodic updates (`background_tracking.py`)
- Push notifications via Firebase and Expo

**Data Storage**:
- PostgreSQL with PostGIS for geospatial data
- MinIO for object storage
- TimescaleDB for time-series optimization

### Critical Services
- Database connection is checked at startup and in health endpoint
- Firebase initialization for FCM notifications (optional)
- Background scheduler for cleanup tasks
- Rate limiting middleware for API protection

### Configuration
- Environment-based configuration via `config.py` and `.env`
- Pydantic settings for type validation
- CORS configured for web clients

### Data Models
- **Race**: Competition management with timezone support
- **Flight**: Live and uploaded track data with geospatial points
- **LiveTrackPoint/UploadedTrackPoint**: Time-series location data
- **NotificationTokenDB**: Push notification token management

The application serves as the backend for a flight tracking system with real-time capabilities, supporting both live tracking during flights and uploaded track analysis for competitions.