"""
Asynchronous delete endpoint that returns 202 Accepted immediately
"""
from fastapi import APIRouter, HTTPException, Query, Security, Depends, BackgroundTasks, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from sqlalchemy import or_
from typing import Dict, Any
import jwt
import logging
import asyncio
from datetime import datetime
from uuid import uuid4

from database.db_conf import get_db
from database.models import Flight
from config import settings
from redis_queue_system.redis_queue import redis_queue

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tracking")
security = HTTPBearer()

# Store deletion status in Redis
deletion_status = {}

async def delete_single_flight_background(
    flight_uuid: str,
    race_id: str,
    source: str,
    deletion_id: str
):
    """Background task to delete a single flight with potentially thousands of points"""
    try:
        # Get a new database session for background task
        from database.db_conf import SessionLocal
        db = SessionLocal()
        
        # Update status
        await redis_queue.redis.hset(
            f"deletion:{deletion_id}",
            mapping={
                "status": "processing",
                "started_at": datetime.utcnow().isoformat()
            }
        )
        
        # Find the flight
        flight = db.query(Flight).filter(
            Flight.id == flight_uuid,
            Flight.race_id == race_id,
            Flight.source == source
        ).first()
        
        if not flight:
            await redis_queue.redis.hset(
                f"deletion:{deletion_id}",
                mapping={
                    "status": "failed",
                    "error": "Flight not found",
                    "failed_at": datetime.utcnow().isoformat()
                }
            )
            return
        
        # Track statistics
        total_points = flight.total_points or 0
        pilot_name = flight.pilot_name or "Unknown"
        
        # Delete the flight (cascade will delete all track points)
        db.delete(flight)
        db.commit()
        
        # Update final status
        await redis_queue.redis.hset(
            f"deletion:{deletion_id}",
            mapping={
                "status": "completed",
                "completed_at": datetime.utcnow().isoformat(),
                "deleted_flights": "1",
                "deleted_points": str(total_points),
                "pilot_name": pilot_name,
                "flight_uuid": flight_uuid
            }
        )
        
        # Set expiry for status (1 hour)
        await redis_queue.redis.expire(f"deletion:{deletion_id}", 3600)
        
        logger.info(f"Background deletion completed: flight {flight_uuid} with {total_points} points")
        
    except Exception as e:
        logger.error(f"Background flight deletion failed: {e}")
        await redis_queue.redis.hset(
            f"deletion:{deletion_id}",
            mapping={
                "status": "failed",
                "error": str(e),
                "failed_at": datetime.utcnow().isoformat()
            }
        )
    finally:
        db.close()

async def delete_pilot_flights_background(
    pilot_id: str,
    source_type: str,
    deletion_id: str
):
    """Background task to delete pilot flights"""
    try:
        # Get a new database session for background task
        from database.db_conf import SessionLocal
        db = SessionLocal()
        
        # Update status
        await redis_queue.redis.hset(
            f"deletion:{deletion_id}",
            mapping={
                "status": "processing",
                "started_at": datetime.utcnow().isoformat()
            }
        )
        
        # Build query
        query = db.query(Flight).filter(Flight.pilot_id == pilot_id)
        
        if source_type == 'live':
            query = query.filter(Flight.source.ilike('%live%'))
        elif source_type == 'upload':
            query = query.filter(Flight.source.ilike('%upload%'))
        elif source_type == 'live_and_upload':
            query = query.filter(
                or_(
                    Flight.source.ilike('%live%'),
                    Flight.source.ilike('%upload%')
                )
            )
        
        flights = query.all()
        
        # Track statistics
        deleted_count = 0
        total_points = 0
        
        # Delete in batches to avoid locking
        for flight in flights:
            total_points += flight.total_points or 0
            db.delete(flight)
            deleted_count += 1
            
            # Commit every 10 flights to avoid long transactions
            if deleted_count % 10 == 0:
                db.commit()
                # Update progress
                await redis_queue.redis.hset(
                    f"deletion:{deletion_id}",
                    "progress", f"{deleted_count}/{len(flights)}"
                )
        
        # Final commit
        db.commit()
        
        # Update final status
        await redis_queue.redis.hset(
            f"deletion:{deletion_id}",
            mapping={
                "status": "completed",
                "completed_at": datetime.utcnow().isoformat(),
                "deleted_flights": str(deleted_count),
                "deleted_points": str(total_points)
            }
        )
        
        # Set expiry for status (1 hour)
        await redis_queue.redis.expire(f"deletion:{deletion_id}", 3600)
        
        logger.info(f"Background deletion completed: {deleted_count} flights for pilot {pilot_id}")
        
    except Exception as e:
        logger.error(f"Background deletion failed: {e}")
        await redis_queue.redis.hset(
            f"deletion:{deletion_id}",
            mapping={
                "status": "failed",
                "error": str(e),
                "failed_at": datetime.utcnow().isoformat()
            }
        )
    finally:
        db.close()

@router.delete("/tracks/fuuid-async/{flight_uuid}")
async def delete_single_flight_async(
    flight_uuid: str,
    background_tasks: BackgroundTasks,
    source: str = Query(..., regex="^.*(?:live|upload).*$",
                        description="Track source (must contain 'live' or 'upload')"),
    credentials: HTTPAuthorizationCredentials = Security(security),
    db: Session = Depends(get_db)
):
    """
    Asynchronously delete a single flight with potentially thousands of points.
    Returns 202 Accepted immediately and processes deletion in background.
    
    Perfect for deleting flights with many track points without blocking the UI.
    Check status via GET /deletion-status/{deletion_id}
    """
    try:
        # Verify JWT token
        token = credentials.credentials
        token_data = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=["HS256"],
            audience="api.hikeandfly.app",
            issuer="hikeandfly.app",
            verify=True
        )
        
        if not token_data.get("sub", "").startswith("contest:"):
            raise HTTPException(
                status_code=403,
                detail="Invalid token subject - must be contest-specific"
            )
        
        race_id = token_data["sub"].split(":")[1]
        
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except Exception:
        raise HTTPException(status_code=403, detail="Invalid or expired token")
    
    # Quick check if flight exists
    flight = db.query(Flight).filter(
        Flight.id == flight_uuid,
        Flight.race_id == race_id,
        Flight.source == source
    ).first()
    
    if not flight:
        raise HTTPException(
            status_code=404,
            detail=f"Flight not found with id {flight_uuid} and source {source}"
        )
    
    # Generate deletion ID
    deletion_id = str(uuid4())
    
    # Initialize status in Redis
    await redis_queue.redis.hset(
        f"deletion:{deletion_id}",
        mapping={
            "status": "accepted",
            "flight_uuid": flight_uuid,
            "source": source,
            "pilot_name": flight.pilot_name or "Unknown",
            "total_points": str(flight.total_points or 0),
            "created_at": datetime.utcnow().isoformat()
        }
    )
    
    # Add background task
    background_tasks.add_task(
        delete_single_flight_background,
        flight_uuid,
        race_id,
        source,
        deletion_id
    )
    
    # Return 202 Accepted immediately
    return {
        "status_code": status.HTTP_202_ACCEPTED,
        "deletion_id": deletion_id,
        "message": f"Flight deletion accepted (contains {flight.total_points or 0} points)",
        "status_url": f"/tracking/deletion-status/{deletion_id}"
    }

@router.delete("/admin/delete-pilot-flights-async/{pilot_id}")
async def delete_pilot_flights_async(
    pilot_id: str,
    background_tasks: BackgroundTasks,
    source_type: str = Query("all", description="Type of flights to delete"),
    credentials: HTTPAuthorizationCredentials = Security(security),
    db: Session = Depends(get_db)
):
    """
    Asynchronously delete flights for a pilot. Returns 202 Accepted immediately.
    
    Returns a deletion_id that can be used to check status via GET /deletion-status/{deletion_id}
    """
    # Verify JWT token
    try:
        jwt.decode(
            credentials.credentials,
            settings.SECRET_KEY,
            algorithms=["HS256"],
            audience="api.hikeandfly.app",
            issuer="hikeandfly.app",
            verify=True
        )
    except Exception:
        raise HTTPException(status_code=403, detail="Invalid or expired token")
    
    # Validate source_type
    valid_source_types = ['all', 'live', 'upload', 'live_and_upload']
    if source_type not in valid_source_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid source_type: {source_type}"
        )
    
    # Quick check if pilot has any flights
    has_flights = db.query(Flight).filter(
        Flight.pilot_id == pilot_id
    ).limit(1).first() is not None
    
    if not has_flights:
        return {
            "success": False,
            "message": f"No flights found for pilot_id: {pilot_id}"
        }
    
    # Generate deletion ID
    deletion_id = str(uuid4())
    
    # Initialize status in Redis
    await redis_queue.redis.hset(
        f"deletion:{deletion_id}",
        mapping={
            "status": "accepted",
            "pilot_id": pilot_id,
            "source_type": source_type,
            "created_at": datetime.utcnow().isoformat()
        }
    )
    
    # Add background task
    background_tasks.add_task(
        delete_pilot_flights_background,
        pilot_id,
        source_type,
        deletion_id
    )
    
    # Return 202 Accepted immediately
    return {
        "status_code": status.HTTP_202_ACCEPTED,
        "deletion_id": deletion_id,
        "message": "Deletion request accepted and processing in background",
        "status_url": f"/tracking/deletion-status/{deletion_id}"
    }

@router.get("/deletion-status/{deletion_id}")
async def get_deletion_status(deletion_id: str):
    """Check the status of an async deletion"""
    
    # Get status from Redis
    status_data = await redis_queue.redis.hgetall(f"deletion:{deletion_id}")
    
    if not status_data:
        raise HTTPException(
            status_code=404,
            detail="Deletion ID not found or expired"
        )
    
    # Convert bytes to strings
    result = {
        k.decode() if isinstance(k, bytes) else k: 
        v.decode() if isinstance(v, bytes) else v 
        for k, v in status_data.items()
    }
    
    return result