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
from api.gps_tcp_status import router as gps_tcp_status_router
from api.monitoring import router as monitoring_router
from api.queue_admin import router as queue_admin_router
from background_tracking import periodic_tracking_update
from db_cleanup import setup_scheduler
from contextlib import asynccontextmanager
from database.db_conf import engine, test_db_connection
import sqlalchemy
from redis_queue_system.redis_queue import redis_queue
from redis_queue_system.point_processor import point_processor
from middleware.db_recovery import setup_database_recovery
from config import settings


def check_database_connection():
    """
    Check if the database connection is working.
    Returns (success, message) tuple.
    """
    return test_db_connection(max_retries=3)


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
    
    # Check replica connection if configured
    try:
        from database.db_replica import test_replica_connection
        replica_connected, replica_message = test_replica_connection()
        if replica_connected:
            logger.info(f"Replica database check: {replica_message}")
        else:
            logger.warning(f"Replica database check: {replica_message}")
            logger.warning("Falling back to primary database for all operations")
    except ImportError:
        logger.debug("Replica database module not available")

    # Initialize Redis connection
    try:
        await redis_queue.initialize()
        logger.info("Redis connection initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize Redis connection: {e}")
        logger.warning("Queue functionality will not be available")

    # Start background point processors
    try:
        await point_processor.start()
        logger.info("Background point processors started successfully")
    except Exception as e:
        logger.error(f"Failed to start background processors: {e}")

    # Initialize Firebase for FCM notifications
    try:
        from api.send_notifications import initialize_firebase
        initialize_firebase()
    except Exception as e:
        logger.error(f"Failed to initialize Firebase: {e}")
        logger.warning("FCM notifications will not be available")
    
    # Initialize Datadog monitoring
    try:
        from monitoring.datadog_integration import initialize_datadog
        await initialize_datadog()
        logger.info("Datadog monitoring initialized")
    except Exception as e:
        logger.warning(f"Failed to initialize Datadog monitoring: {e}")
        logger.warning("Metrics will be logged locally only")

    # Start GPS TCP Server if enabled
    tcp_server_task = None
    if settings.GPS_TCP_ENABLED:
        try:
            from tcp_server.gps_tcp_server import GPSTrackerTCPServer
            tcp_server = GPSTrackerTCPServer(host='0.0.0.0', port=settings.GPS_TCP_PORT)
            tcp_server_task = asyncio.create_task(tcp_server.start())
            logger.info(f"GPS TCP Server started on port {settings.GPS_TCP_PORT}")
        except Exception as e:
            logger.error(f"Failed to start GPS TCP Server: {e}")
            logger.warning("GPS TCP Server will not be available")
    else:
        logger.info("GPS TCP Server is disabled in configuration")

    # Start the background tracking task when the application starts
    track_task = asyncio.create_task(
        periodic_tracking_update(10))  # Update every 10 seconds

    # Set up and start the cleanup scheduler
    scheduler = setup_scheduler()
    scheduler.start()
    
    # Store tcp_server reference in app state for status endpoint
    if settings.GPS_TCP_ENABLED and 'tcp_server' in locals():
        app.state.tcp_server = tcp_server

    # Yield control back to FastAPI
    yield

    # Cleanup when the application shuts down
    logger.info("Starting application shutdown...")

    # Stop background processors
    try:
        await point_processor.stop()
        logger.info("Background processors stopped")
    except Exception as e:
        logger.error(f"Error stopping background processors: {e}")

    # Close Redis connections
    try:
        await redis_queue.close()
        logger.info("Redis connections closed")
    except Exception as e:
        logger.error(f"Error closing Redis connections: {e}")

    # Shutdown GPS TCP Server if running
    if tcp_server_task:
        try:
            if 'tcp_server' in locals():
                await tcp_server.shutdown()
                logger.info("GPS TCP Server stopped")
        except Exception as e:
            logger.error(f"Error stopping GPS TCP Server: {e}")
        
        tcp_server_task.cancel()
        try:
            await tcp_server_task
        except asyncio.CancelledError:
            pass

    # Cancel tracking task
    track_task.cancel()
    try:
        await track_task
    except asyncio.CancelledError:
        # Task was successfully cancelled
        pass

    # Shut down the scheduler
    scheduler.shutdown()
    logger.info("Application shutdown completed")


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

# Setup database recovery middleware for Neon connection issues
setup_database_recovery(app, max_retries=3, retry_delay=0.5)


@app.middleware("http")
async def log_request(request: Request, call_next):
    logger.info(f"Incoming request: {request.method} {request.url}")
    response = await call_next(request)
    logger.info(f"Outgoing response: {response.status_code}")
    return response


app.include_router(routes.router, tags=['Tracking'], prefix='/tracking')
app.include_router(scoring.router, tags=['Scoring'], prefix='/scoring')
app.include_router(gps_tcp_status_router, tags=['GPS TCP Server'])
app.include_router(monitoring_router, tags=['Monitoring'])
app.include_router(queue_admin_router, tags=['Queue Admin'])

# TK905B GPS Tracker endpoint (learning mode)
try:
    from api.tk905b import router as tk905b_router
    app.include_router(tk905b_router, tags=['TK905B'], prefix='/tracking')
    logger.info("TK905B learning endpoint registered at /tracking/tk905b/*")
except ImportError:
    logger.warning("TK905B endpoint not available")



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


@app.get('/')
async def root():
    """
    Simple root endpoint that provides basic system status.
    Returns minimal system information to confirm the service is running.
    """
    now = datetime.datetime.now()
    uptime = now - system_startup_time

    return {
        'service': 'HFSS Live Tracking API',
        'status': 'up',
        'version': '1.0.0',
        'uptime': str(uptime),
        'timestamp': now.isoformat(),
        'endpoints': {
            'health': '/health',
            'tracking': '/tracking',
            'scoring': '/scoring',
            'queue_status': '/queue/status'
        }
    }


@app.get('/health')
async def health():
    now = datetime.datetime.now()
    uptime = now - system_startup_time

    # Check database connection
    is_db_connected, db_message = check_database_connection()

    # Check Redis connection
    is_redis_connected = await redis_queue.is_connected()

    # Check queue statistics
    queue_stats = await redis_queue.get_queue_stats()
    
    # Get Redis connection pool info
    redis_pool_info = {}
    try:
        if redis_queue.redis_client and hasattr(redis_queue.redis_client, 'connection_pool'):
            pool = redis_queue.redis_client.connection_pool
            redis_pool_info = {
                'created_connections': getattr(pool, 'created_connections', 'N/A'),
                'available_connections': len(getattr(pool, '_available_connections', [])),
                'in_use_connections': len(getattr(pool, '_in_use_connections', [])),
                'max_connections': getattr(settings, 'REDIS_MAX_CONNECTIONS', 10)
            }
    except Exception as e:
        redis_pool_info = {'error': str(e)}

    status = 'healthy' if (
        is_db_connected and is_redis_connected) else 'unhealthy'

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
        },
        'redis': {
            'status': 'connected' if is_redis_connected else 'disconnected',
            'queue_stats': queue_stats,
            'connection_pool': redis_pool_info
        }
    }
    
    # Add GPS TCP Server status if enabled
    if settings.GPS_TCP_ENABLED:
        try:
            if hasattr(app.state, 'tcp_server'):
                tcp_status = app.state.tcp_server.get_status()
                response['gps_tcp_server'] = tcp_status
            else:
                response['gps_tcp_server'] = {
                    'running': False,
                    'message': 'Server not initialized'
                }
        except Exception as e:
            response['gps_tcp_server'] = {
                'running': False,
                'error': str(e)
            }

    logger.info(
        f"Healthcheck requested on {now}. Database status: {response['database']['status']}, Redis status: {response['redis']['status']}")

    # Return an appropriate status code based on health
    # 503 Service Unavailable if DB or Redis is down
    status_code = 200 if (is_db_connected and is_redis_connected) else 503

    # Return the response with pre-serialized datetime values
    return JSONResponse(content=response, status_code=status_code)


@app.get('/gps-tcp/status')
async def gps_tcp_status():
    """Get GPS TCP Server status"""
    if not settings.GPS_TCP_ENABLED:
        return JSONResponse(
            content={"error": "GPS TCP Server is disabled in configuration"},
            status_code=404
        )
    
    try:
        if hasattr(app.state, 'tcp_server'):
            status = app.state.tcp_server.get_status()
            status['timestamp'] = datetime.datetime.now().isoformat()
            return status
        else:
            return JSONResponse(
                content={"error": "GPS TCP Server not initialized"},
                status_code=503
            )
    except Exception as e:
        logger.error(f"Error getting GPS TCP status: {e}")
        return JSONResponse(
            content={"error": str(e)},
            status_code=500
        )


@app.get('/queue/status')
async def queue_status():
    """Get detailed queue status and statistics"""
    try:
        if not await redis_queue.is_connected():
            return JSONResponse(
                content={"error": "Redis not connected"},
                status_code=503
            )

        stats = await redis_queue.get_queue_stats()
        processor_stats = point_processor.get_stats()

        return {
            "redis_connected": True,
            "queue_stats": stats,
            "processor_stats": processor_stats,
            "timestamp": datetime.datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Error getting queue status: {e}")
        return JSONResponse(
            content={"error": str(e)},
            status_code=500
        )


@app.delete('/queue/clear')
async def clear_queues():
    """Clear all Redis queues - useful for removing stuck items"""
    try:
        if not await redis_queue.is_connected():
            return JSONResponse(
                content={"error": "Redis not connected"},
                status_code=503
            )
        
        from redis_queue_system.redis_queue import QUEUE_NAMES
        
        cleared = {}
        for queue_name in QUEUE_NAMES.values():
            # Get count before clearing
            queue_key = f"queue:{queue_name}"
            count = await redis_queue.redis_client.zcard(queue_key)
            if count > 0:
                # Clear the queue
                await redis_queue.redis_client.delete(queue_key)
                cleared[queue_name] = count
                logger.warning(f"Cleared {count} items from {queue_name}")
        
        return {
            "success": True,
            "cleared_queues": cleared,
            "timestamp": datetime.datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Error clearing queues: {e}")
        return JSONResponse(
            content={"error": str(e)},
            status_code=500
        )


if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
