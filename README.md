# HFSS Live Tracking Service

A FastAPI backend service for the Hike & Fly application that provides real-time tracking capabilities, flight data management, and race tracking.

## Features

- Live tracking for pilots
- Uploaded track management
- Race tracking and management
- Push notifications
- User authentication
- Time-series data storage with TimescaleDB
- Rate limiting for API endpoints
- Dockerized deployment

## Tech Stack

- **Backend**: FastAPI (Python)
- **Database**: PostgreSQL with TimescaleDB extension
- **Deployment**: Docker, Docker Compose
- **Data Storage**: MinIO service for object storage
- **Migration**: Alembic for database migrations

## Development Setup

### Prerequisites

- Python 3.10+
- PostgreSQL with TimescaleDB extension
- Docker and Docker Compose

### Local Development

1. Clone the repository:

   ```bash
   git clone <repository-url>
   cd hfss_live
   ```

2. Create a virtual environment:

   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows use: venv\Scripts\activate
   ```

3. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

4. Create a `.env` file with necessary environment variables (see `.env.example` if available)

5. Run the application:

   ```bash
   uvicorn app:app --reload
   ```

6. Access the API documentation at `http://localhost:8000/docs`

### Docker Deployment

1. Build and start the containers:

   ```bash
   docker-compose up -d
   ```

2. The API will be available at `http://localhost:5012`

## Database Management

### Setting Up TimescaleDB

Run the following SQL commands to set up TimescaleDB:

```sql
CREATE EXTENSION IF NOT EXISTS timescaledb;

SELECT create_hypertable('live_track_points', 'datetime', chunk_time_interval => INTERVAL '1 day');
SELECT create_hypertable('uploaded_track_points', 'datetime', chunk_time_interval => INTERVAL '1 day');

SELECT create_hypertable('scoring_tracks', 'date_time', 
                        chunk_time_interval => INTERVAL '1 day',
                        if_not_exists => TRUE);

-- Grant privileges
GRANT ALL PRIVILEGES ON TABLE live_track_points TO py_ll_user;
GRANT ALL PRIVILEGES ON TABLE uploaded_track_points TO py_ll_user;
GRANT ALL PRIVILEGES ON TABLE flights TO py_ll_user;
GRANT ALL PRIVILEGES ON TABLE races TO py_ll_user;
GRANT ALL PRIVILEGES ON TABLE notification_tokens TO py_ll_user;
GRANT ALL PRIVILEGES ON TABLE scoring_tracks TO py_ll_user;

-- Common privileges needed for both tables
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO py_ll_user;
GRANT USAGE ON SCHEMA public TO py_ll_user;
```

### Data Retention

We use automatic cleanup for old data:

```sql
-- Create a function to delete old live flights
CREATE OR REPLACE FUNCTION cleanup_live_flights()
RETURNS void AS $$
BEGIN
    DELETE FROM flights
    WHERE source = 'live'
    AND created_at < (NOW() - INTERVAL '48 hours');
    -- All associated live_track_points will be automatically deleted due to CASCADE
END;
$$ LANGUAGE plpgsql;

-- Create a scheduled job using pg_cron to run daily
CREATE EXTENSION IF NOT EXISTS pg_cron;
SELECT cron.schedule('0 0 * * *', 'SELECT cleanup_live_flights()');
```

For postgis
``` -- Connect to your TimescaleDB database first
CREATE EXTENSION IF NOT EXISTS postgis;

-- Verify installation
SELECT PostGIS_version();
```

### Working with Alembic

Database migrations are handled with Alembic:

1. Initialize Alembic (if not already done):

   ```bash
   alembic init alembic
   ```

2. Create a new migration:

   ```bash
   alembic revision -m "description of the migration" --autogenerate
   ```

3. Apply migrations:
   ```bash
   alembic upgrade head
   ```

## API Endpoints

- `GET /health`: API health check
- `POST /tracking/...`: Tracking-related endpoints
- See API documentation for complete list of endpoints

## Logging

Logging is configured in the `logs` module. The application logs are stored in `logs/logs.log`.

For React Native client app logging:

```bash
npx react-native log-android
```

## License

[License information]

## Contributors

[List of contributors]
Simone Severini