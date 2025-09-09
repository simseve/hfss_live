"""
Datadog middleware for automatic metrics collection on API requests
"""
import time
import logging
from typing import Optional, Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)

class DatadogMiddleware(BaseHTTPMiddleware):
    """Middleware to automatically send metrics to Datadog for each API request"""
    
    def __init__(self, app: ASGIApp):
        super().__init__(app)
        self.statsd_client = None
        self._initialize_statsd()
    
    def _initialize_statsd(self):
        """Initialize StatsD client for sending metrics"""
        try:
            from datadog import DogStatsd
            from config import settings
            
            # Initialize DogStatsD client
            self.statsd_client = DogStatsd(
                host=settings.DD_AGENT_HOST,
                port=settings.DD_DOGSTATSD_PORT,
                namespace='hfss',
                constant_tags=[
                    f'env:{settings.DD_ENV or "production"}',
                    f'version:{settings.DD_VERSION or "1.0.0"}'
                ]
            )
            logger.info(f"Datadog StatsD client initialized: {settings.DD_AGENT_HOST}:{settings.DD_DOGSTATSD_PORT}")
        except Exception as e:
            logger.warning(f"Failed to initialize Datadog StatsD: {e}")
            self.statsd_client = None
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request and send metrics to Datadog"""
        start_time = time.time()
        
        # Extract endpoint info
        path = request.url.path
        method = request.method
        
        # Skip health checks and static files
        if path in ['/health', '/favicon.ico', '/docs', '/openapi.json', '/redoc']:
            return await call_next(request)
        
        # Process request
        response = None
        error_occurred = False
        
        try:
            response = await call_next(request)
            status_code = response.status_code
            
            # Check for errors
            if status_code >= 400:
                error_occurred = True
                
        except Exception as e:
            error_occurred = True
            status_code = 500
            logger.error(f"Request failed: {e}")
            raise
        finally:
            # Calculate response time
            response_time = (time.time() - start_time) * 1000  # Convert to ms
            
            # Send metrics if StatsD is available
            if self.statsd_client:
                try:
                    # Normalize endpoint for tagging
                    endpoint = self._normalize_endpoint(path)
                    
                    # Request count
                    self.statsd_client.increment(
                        'api.requests',
                        tags=[
                            f'endpoint:{endpoint}',
                            f'method:{method}',
                            f'status:{status_code}',
                            f'status_family:{status_code // 100}xx'
                        ]
                    )
                    
                    # Response time
                    self.statsd_client.histogram(
                        'api.response_time',
                        response_time,
                        tags=[
                            f'endpoint:{endpoint}',
                            f'method:{method}'
                        ]
                    )
                    
                    # Error count
                    if error_occurred:
                        self.statsd_client.increment(
                            'api.errors',
                            tags=[
                                f'endpoint:{endpoint}',
                                f'method:{method}',
                                f'status:{status_code}',
                                f'status_family:{status_code // 100}xx'
                            ]
                        )
                    
                    # Track specific endpoint categories
                    if '/live/' in path:
                        self.statsd_client.increment('api.live.requests')
                        self.statsd_client.histogram('api.live.response_time', response_time)
                    elif '/upload/' in path:
                        self.statsd_client.increment('api.upload.requests')
                        self.statsd_client.histogram('api.upload.response_time', response_time)
                    elif '/scoring' in path:
                        self.statsd_client.increment('api.scoring.requests')
                        self.statsd_client.histogram('api.scoring.response_time', response_time)
                    elif '/gps-tcp' in path:
                        self.statsd_client.increment('api.gps_tcp.requests')
                        self.statsd_client.histogram('api.gps_tcp.response_time', response_time)
                    
                    # Log slow requests
                    if response_time > 1000:  # Over 1 second
                        self.statsd_client.increment(
                            'api.slow_requests',
                            tags=[
                                f'endpoint:{endpoint}',
                                f'method:{method}'
                            ]
                        )
                        logger.warning(f"Slow request: {method} {path} took {response_time:.2f}ms")
                    
                except Exception as e:
                    logger.debug(f"Failed to send metrics to Datadog: {e}")
        
        return response
    
    def _normalize_endpoint(self, path: str) -> str:
        """Normalize endpoint path for consistent tagging"""
        # Remove query parameters
        path = path.split('?')[0]
        
        # Replace IDs with placeholders
        import re
        
        # UUID pattern
        path = re.sub(r'/[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}', '/{id}', path)
        
        # Numeric IDs
        path = re.sub(r'/\d+', '/{id}', path)
        
        # MVT tiles pattern
        path = re.sub(r'/mvt/[^/]+/\d+/\d+/\d+', '/mvt/{race_id}/{z}/{x}/{y}', path)
        
        # Remove trailing slashes
        path = path.rstrip('/')
        
        return path or '/'