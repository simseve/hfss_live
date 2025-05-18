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


@asynccontextmanager
async def lifespan(app):
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


@app.get('/health')
def root():
    now = datetime.datetime.now()
    uptime = now - system_startup_time
    response = {
        'status': 'healthy',
        'system_startup_time': system_startup_time,
        'current_time': now,
        'uptime': str(uptime),
        'scheduled_tasks': ['live_tracking_update', 'old_flights_cleanup']
    }
    logger.info(f"Healthcheck requested on {now}")
    return response


if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
