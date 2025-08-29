"""
GPS TCP Server status endpoint for external service monitoring
"""
import asyncio
import socket
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from datetime import datetime
import logging
from typing import Dict, Any
from config import settings
from redis_queue_system.redis_queue import redis_queue

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/gps-tcp", tags=["GPS TCP Server"])


async def check_tcp_port(host: str, port: int, timeout: float = 5.0) -> bool:
    """Check if TCP port is open and accepting connections"""
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=timeout
        )
        writer.close()
        await writer.wait_closed()
        return True
    except (asyncio.TimeoutError, ConnectionRefusedError, OSError):
        return False


@router.get("/external/status")
async def get_external_gps_tcp_status() -> Dict[str, Any]:
    """
    Get status of external GPS TCP Server service
    This endpoint is used when GPS TCP Server runs as a separate Docker service
    """
    status = {
        "timestamp": datetime.now().isoformat(),
        "mode": "external_service",
        "configured": settings.GPS_TCP_ENABLED
    }
    
    if not settings.GPS_TCP_ENABLED:
        status["running"] = False
        status["message"] = "GPS TCP Server is disabled in configuration"
        return JSONResponse(content=status, status_code=200)
    
    # Check if the GPS TCP port is accessible
    gps_host = settings.GPS_TCP_HOST if hasattr(settings, 'GPS_TCP_HOST') else 'gps-tcp-server'
    gps_port = settings.GPS_TCP_PORT
    
    try:
        # Check if port is open
        is_running = await check_tcp_port(gps_host, gps_port)
        status["running"] = is_running
        status["host"] = gps_host
        status["port"] = gps_port
        
        if is_running:
            status["message"] = f"GPS TCP Server is running on {gps_host}:{gps_port}"
            
            # Check Redis queue for GPS data processing stats
            try:
                queue_status = await redis_queue.get_queue_status()
                if queue_status and 'track_points' in queue_status:
                    status["queue_stats"] = {
                        "pending_points": queue_status['track_points'].get('pending', 0),
                        "processing_rate": queue_status['track_points'].get('processing_rate', 0)
                    }
            except Exception as e:
                logger.warning(f"Could not get queue stats: {e}")
                
        else:
            status["message"] = f"GPS TCP Server is not accessible at {gps_host}:{gps_port}"
            
    except Exception as e:
        logger.error(f"Error checking GPS TCP Server status: {e}")
        status["running"] = False
        status["error"] = str(e)
        return JSONResponse(content=status, status_code=503)
    
    return status


@router.get("/external/health")
async def check_external_gps_tcp_health():
    """
    Health check for external GPS TCP Server
    Returns 200 if server is running, 503 if not
    """
    gps_host = settings.GPS_TCP_HOST if hasattr(settings, 'GPS_TCP_HOST') else 'gps-tcp-server'
    gps_port = settings.GPS_TCP_PORT
    
    is_running = await check_tcp_port(gps_host, gps_port, timeout=3.0)
    
    if is_running:
        return {"status": "healthy", "timestamp": datetime.now().isoformat()}
    else:
        raise HTTPException(
            status_code=503,
            detail=f"GPS TCP Server not responding at {gps_host}:{gps_port}"
        )