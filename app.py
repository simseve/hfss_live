import json
import logging
import uuid
from logs.logconfig import configure_logging
from fastapi import FastAPI, APIRouter, Request
from fastapi.responses import JSONResponse

import logging
import uvicorn
from fastapi.middleware.cors import CORSMiddleware
import datetime
import asyncio  # Add this import for background tasks
from rate_limiter import rate_limiter
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from fastapi import FastAPI
from fastapi.security import HTTPBasic
import api.routes as routes
import api.scoring as scoring
from background_tracking import periodic_tracking_update
from db_cleanup import setup_scheduler
from contextlib import asynccontextmanager
from database.db_conf import engine
import sqlalchemy


def check_database_connection():
    """
    Check if the database connection is working.
    Raises exception if connection fails.
    """
    try:
        # Execute a simple query to check connection
        with engine.connect() as connection:
            connection.execute(sqlalchemy.text("SELECT 1"))
        return True, "Database connection successful"
    except Exception as e:
        return False, f"Database connection failed: {str(e)}"


@asynccontextmanager
async def lifespan(app):
    # Check database connection first
    logger = logging.getLogger(__name__)
    is_connected, message = check_database_connection()
    if not is_connected:
        logger.critical(f"Failed to connect to PostgreSQL database: {message}")
        raise RuntimeError(f"Database connection check failed: {message}")
    else:
        logger.info(f"Database connection check: {message}")

    # Start the background tracking task when the application starts
    track_task = asyncio.create_task(
        periodic_tracking_update(10))  # Update every 10 seconds

    # Set up and start the cleanup scheduler
    scheduler = setup_scheduler()
    scheduler.start()

    # Yield control back to FastAPI
    yield

    # Cleanup when the application shuts down
    track_task.cancel()
    try:
        await track_task
    except asyncio.CancelledError:
        # Task was successfully cancelled
        pass

    # Shut down the scheduler
    scheduler.shutdown()


app = FastAPI(lifespan=lifespan)
# Apply the lifespan context
app.router.lifespan_context = lifespan


system_startup_time = datetime.datetime.now()

router = APIRouter()

security = HTTPBasic()

session_id_run = str(uuid.uuid4())

# Initialize logging at the start of your application
configure_logging(session_id_run=session_id_run, enable_db_logging=False)

# Create a logger for each module
logger = logging.getLogger(__name__)


origins = [
    "https://hikeandfly.app",
    "https://api.hikeandfly.app",
    "http://localhost:3000",  # For local development
    "*"
]

# Update CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE",
                   "OPTIONS"],  # Explicitly list allowed methods
    allow_headers=["*"],
)


@app.middleware("http")
async def log_request(request: Request, call_next):
    logger.info(f"Incoming request: {request.method} {request.url}")
    response = await call_next(request)
    logger.info(f"Outgoing response: {response.status_code}")
    return response


app.include_router(routes.router, tags=['Tracking'], prefix='/tracking')
app.include_router(scoring.router, tags=['Scoring'], prefix='/scoring')


# Attach the rate limiter as a middleware
app.state.limiter = rate_limiter
app.add_middleware(SlowAPIMiddleware)
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


class DateTimeEncoder(json.JSONEncoder):
    """Custom JSON encoder that handles datetime objects."""

    def default(self, obj):
        if isinstance(obj, datetime.datetime):
            return obj.isoformat()
        return super().default(obj)


@app.get('/health')
async def root():
    now = datetime.datetime.now()
    uptime = now - system_startup_time

    # Check database connection
    is_db_connected, db_message = check_database_connection()
    status = 'healthy' if is_db_connected else 'unhealthy'

    response = {
        'status': status,
        # Convert to ISO format string
        'system_startup_time': system_startup_time.isoformat(),
        'current_time': now.isoformat(),  # Convert to ISO format string
        'uptime': str(uptime),
        'scheduled_tasks': ['live_tracking_update', 'old_flights_cleanup'],
        'database': {
            'status': 'connected' if is_db_connected else 'disconnected',
            'message': db_message
        }
    }

    logger.info(
        f"Healthcheck requested on {now}. Database status: {response['database']['status']}")

    # Return an appropriate status code based on health
    # 503 Service Unavailable if DB is down
    status_code = 200 if is_db_connected else 503

    # Return the response with pre-serialized datetime values
    return JSONResponse(content=response, status_code=status_code)


if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
