from slowapi import Limiter
from slowapi.util import get_remote_address
from fastapi import Request
import logging

logger = logging.getLogger(__name__)

def get_real_client_ip(request: Request) -> str:
    """
    Extract the real client IP address from the request.
    Handles proxy headers (X-Forwarded-For, X-Real-IP) for containerized deployments.
    """
    # Check X-Forwarded-For header first (standard proxy header)
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # X-Forwarded-For can contain multiple IPs, take the first one (original client)
        client_ip = forwarded_for.split(",")[0].strip()
        logger.debug(f"Using X-Forwarded-For IP: {client_ip}")
        return client_ip
    
    # Check X-Real-IP header (nginx proxy header)
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        logger.debug(f"Using X-Real-IP: {real_ip}")
        return real_ip
    
    # Fallback to the default remote address
    default_ip = get_remote_address(request)
    logger.debug(f"Using default remote address: {default_ip}")
    return default_ip

def create_rate_limiter():
    """
    Create a rate limiter that properly handles proxy headers.
    """
    limiter = Limiter(key_func=get_real_client_ip, default_limits=["100/5seconds"])
    return limiter

rate_limiter = create_rate_limiter()
