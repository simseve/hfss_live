import logging
import uuid
from logs.logconfig import configure_logging
from fastapi import FastAPI, APIRouter, Request
import logging
import uvicorn
from fastapi.middleware.cors import CORSMiddleware
import datetime
from rate_limiter import rate_limiter
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi import FastAPI
from fastapi.security import HTTPBasic
import api.routes as routes

app = FastAPI()

system_startup_time = datetime.datetime.now()

router = APIRouter()

security = HTTPBasic()


session_id_run = str(uuid.uuid4())

# Initialize logging at the start of your application
configure_logging(session_id_run=session_id_run, enable_db_logging=False)

# Create a logger for each module
logger = logging.getLogger(__name__)


origins = [
    "http://hikeandfly.app",
    "http://0.0.0.0"
]


@app.middleware("http")
async def log_request(request: Request, call_next):
    logger.info(f"Incoming request: {request.method} {request.url}")
    response = await call_next(request)
    logger.info(f"Outgoing response: {response.status_code}")
    return response


# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(routes.router, tags=['Tracking'], prefix='/tracking')


# Attach the rate limiter as a middleware
app.state.limiter = rate_limiter
app.add_middleware(SlowAPIMiddleware)
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get('/health')
def root():
    now = datetime.datetime.now()
    uptime = now - system_startup_time
    response = {
        'status': 'healthy',
        'system_startup_time': system_startup_time,
        'current_time': now,
        'uptime': str(uptime),
    }
    logger.info(f"Healthcheck requested on {now}")
    return response



if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)

