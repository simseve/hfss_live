"""
Database connection recovery middleware for handling Neon PostgreSQL connection issues.
Automatically retries failed database operations and manages connection pool health.
"""

import logging
import time
import asyncio
from typing import Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy.exc import OperationalError, DBAPIError, DisconnectionError
from database.db_conf import engine

logger = logging.getLogger(__name__)


class DatabaseRecoveryMiddleware(BaseHTTPMiddleware):
    """
    Middleware to handle database connection recovery for Neon PostgreSQL.
    
    This middleware:
    1. Monitors for SSL connection errors
    2. Automatically disposes stale connections
    3. Implements retry logic for failed requests
    4. Logs connection issues for monitoring
    """
    
    def __init__(self, app, max_retries: int = 3, retry_delay: float = 0.5):
        super().__init__(app)
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.connection_error_count = 0
        self.last_pool_refresh = time.time()
        
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Process the request with automatic retry logic for database failures.
        """
        for attempt in range(self.max_retries):
            try:
                # Reset the error count on successful requests
                response = await call_next(request)
                
                # If we had errors before but this succeeded, log recovery
                if self.connection_error_count > 0:
                    logger.info(f"Database connection recovered after {self.connection_error_count} errors")
                    self.connection_error_count = 0
                    
                return response
                
            except (OperationalError, DBAPIError, DisconnectionError) as e:
                error_msg = str(e)
                self.connection_error_count += 1
                
                # Check for SSL connection errors specifically
                if "SSL connection has been closed unexpectedly" in error_msg:
                    logger.warning(
                        f"SSL connection error detected on attempt {attempt + 1}/{self.max_retries} "
                        f"for {request.url.path}"
                    )
                    
                    # Dispose the connection pool to get fresh connections
                    await self._refresh_connection_pool()
                    
                elif "server closed the connection unexpectedly" in error_msg:
                    logger.warning(
                        f"Server closed connection on attempt {attempt + 1}/{self.max_retries} "
                        f"for {request.url.path}"
                    )
                    await self._refresh_connection_pool()
                    
                else:
                    logger.error(
                        f"Database error on attempt {attempt + 1}/{self.max_retries} "
                        f"for {request.url.path}: {error_msg}"
                    )
                
                # If this is not the last attempt, wait and retry
                if attempt < self.max_retries - 1:
                    delay = self.retry_delay * (2 ** attempt)  # Exponential backoff
                    logger.info(f"Retrying request in {delay} seconds...")
                    await asyncio.sleep(delay)
                else:
                    # Last attempt failed, return error response
                    logger.error(
                        f"Request failed after {self.max_retries} attempts: {request.url.path}"
                    )
                    
                    # Return a proper error response
                    return Response(
                        content=f"Database connection error: {error_msg}",
                        status_code=503,
                        headers={"Retry-After": "30"}
                    )
                    
            except Exception as e:
                # Non-database errors should not be retried
                logger.error(f"Non-database error for {request.url.path}: {str(e)}")
                raise
                
        # Should not reach here, but just in case
        return Response(
            content="Maximum retries exceeded",
            status_code=503,
            headers={"Retry-After": "60"}
        )
    
    async def _refresh_connection_pool(self):
        """
        Refresh the database connection pool.
        Implements rate limiting to avoid excessive pool refreshes.
        """
        current_time = time.time()
        
        # Only refresh pool if at least 5 seconds have passed since last refresh
        if current_time - self.last_pool_refresh > 5:
            try:
                logger.info("Disposing stale database connections...")
                engine.dispose()
                self.last_pool_refresh = current_time
                logger.info("Database connection pool refreshed")
                
                # Small delay to allow new connections to establish
                await asyncio.sleep(0.1)
                
            except Exception as e:
                logger.error(f"Error refreshing connection pool: {e}")
        else:
            logger.debug(
                f"Skipping pool refresh, last refresh was "
                f"{current_time - self.last_pool_refresh:.1f} seconds ago"
            )


def setup_database_recovery(app, max_retries: int = 3, retry_delay: float = 0.5):
    """
    Setup the database recovery middleware for the FastAPI application.
    
    Args:
        app: FastAPI application instance
        max_retries: Maximum number of retry attempts for failed requests
        retry_delay: Initial delay between retries (will use exponential backoff)
    """
    app.add_middleware(
        DatabaseRecoveryMiddleware,
        max_retries=max_retries,
        retry_delay=retry_delay
    )
    logger.info(
        f"Database recovery middleware configured with "
        f"max_retries={max_retries}, retry_delay={retry_delay}"
    )