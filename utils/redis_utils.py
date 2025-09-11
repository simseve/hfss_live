"""
Redis connection utilities for consistent connection handling across services
"""
import logging
from typing import Optional
import redis.asyncio as redis
from config import settings

logger = logging.getLogger(__name__)


async def get_redis_client(
    encoding: str = "utf-8",
    decode_responses: bool = False,
    service_name: str = "Service"
) -> Optional[redis.Redis]:
    """
    Get a Redis client with automatic fallback for development environments.
    
    In production (PROD=True): connects to 'redis' hostname
    In development (PROD=False): tries 'redis' first (Docker), then 'localhost' (local dev)
    
    Args:
        encoding: Character encoding for Redis operations
        decode_responses: Whether to decode responses to strings
        service_name: Name of the service for logging purposes
        
    Returns:
        Redis client instance or None if connection fails
    """
    try:
        if settings.PROD:
            # Production: use redis hostname directly
            redis_host = "redis"
            client = await redis.from_url(
                f"redis://{redis_host}:6379",
                encoding=encoding,
                decode_responses=decode_responses
            )
            await client.ping()
            logger.info(f"{service_name} initialized with Redis at {redis_host}:6379")
            return client
        else:
            # Development: try 'redis' first (Docker), fallback to 'localhost' (laptop)
            for redis_host in ["redis", "localhost"]:
                try:
                    client = await redis.from_url(
                        f"redis://{redis_host}:6379",
                        encoding=encoding,
                        decode_responses=decode_responses
                    )
                    await client.ping()
                    logger.info(f"{service_name} initialized with Redis at {redis_host}:6379")
                    return client
                except Exception as e:
                    logger.debug(f"Could not connect to Redis at {redis_host}:6379: {e}")
                    continue
            
            # If we get here, neither connection worked
            raise Exception("Could not connect to Redis at either 'redis' or 'localhost'")
            
    except Exception as e:
        logger.warning(f"Redis not available for {service_name}: {str(e)}")
        return None


async def get_redis_url_client(
    redis_url: Optional[str] = None,
    encoding: str = "utf-8", 
    decode_responses: bool = True,
    max_connections: Optional[int] = None,
    service_name: str = "Service"
) -> redis.Redis:
    """
    Get a Redis client using the configured REDIS_URL from settings.
    
    This is used by services that need the full Redis URL with authentication.
    
    Args:
        redis_url: Optional Redis URL override
        encoding: Character encoding for Redis operations
        decode_responses: Whether to decode responses to strings
        max_connections: Maximum number of connections in the pool
        service_name: Name of the service for logging purposes
        
    Returns:
        Redis client instance
        
    Raises:
        Exception if connection fails
    """
    try:
        # Use provided URL or get from settings
        url = redis_url or settings.get_redis_url()
        
        client_kwargs = {
            "encoding": encoding,
            "decode_responses": decode_responses
        }
        
        if max_connections:
            client_kwargs["max_connections"] = max_connections
            
        client = redis.from_url(url, **client_kwargs)
        await client.ping()
        logger.info(f"{service_name} connected to Redis: {url}")
        return client
        
    except Exception as e:
        logger.error(f"Failed to connect to Redis for {service_name}: {e}")
        raise