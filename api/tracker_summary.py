"""
Optimized summary endpoint for HFSS tracker page
Returns minimal data needed for initial page load
"""
from fastapi import APIRouter, HTTPException, Query, Security, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List
import jwt
import logging
from cachetools import TTLCache
from threading import Lock

from database.db_conf import get_replica_db
from database.models import Flight, LiveTrackPoint, UploadedTrackPoint
from config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tracking")
security = HTTPBearer()

# Cache for summary data (TTL = 30 seconds)
summary_cache = TTLCache(maxsize=100, ttl=30)
cache_lock = Lock()

@router.get("/live/summary")
async def get_live_summary(
    opentime: str = Query(
        ..., description="Start time for tracking window (ISO 8601 format)"),
    closetime: Optional[str] = Query(
        None, description="End time for tracking window (ISO 8601 format)"),
    source: Optional[str] = Query(None, regex="^.*(?:live|upload).*$"),
    credentials: HTTPAuthorizationCredentials = Security(security),
    db: Session = Depends(get_replica_db)
) -> Dict[str, Any]:
    """
    Optimized summary endpoint for tracker page initial load.
    Returns only essential data: pilot count, flight count, and basic stats.
    Full flight data should be loaded separately per pilot when expanded.
    """
    try:
        # Parse times
        opentime_dt = datetime.fromisoformat(
            opentime.strip().replace('Z', '+00:00'))
        
        if not closetime:
            closetime_dt = datetime.now(timezone.utc) + timedelta(hours=24)
        else:
            closetime_dt = datetime.fromisoformat(
                closetime.strip().replace('Z', '+00:00'))
        
        # Validate JWT token
        token = credentials.credentials
        try:
            payload = jwt.decode(
                token,
                settings.SECRET_KEY,
                algorithms=["HS256"],
                audience="api.hikeandfly.app",
                issuer="hikeandfly.app",
                verify=True
            )
            
            if not payload.get("sub", "").startswith("contest:"):
                raise HTTPException(
                    status_code=403,
                    detail="Invalid token subject"
                )
            
            race_id = payload["sub"].split(":")[1]
            
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Token has expired")
        except Exception as e:
            logger.error(f"Token validation error: {e}")
            raise HTTPException(status_code=401, detail="Invalid token")
        
        # Check cache
        cache_key = f"{race_id}:{opentime}:{closetime}:{source}"
        with cache_lock:
            if cache_key in summary_cache:
                logger.debug(f"Returning cached summary for {cache_key}")
                return summary_cache[cache_key]
        
        # Build optimized query - just get counts and basic stats
        flight_query = db.query(Flight).filter(
            Flight.race_id == race_id,
            Flight.created_at >= opentime_dt,
            Flight.created_at <= closetime_dt
        )
        
        if source:
            flight_query = flight_query.filter(Flight.source == source)
        
        # Get summary statistics using aggregation
        stats = db.query(
            func.count(Flight.id).label('total_flights'),
            func.count(func.distinct(Flight.pilot_id)).label('total_pilots'),
            func.min(Flight.created_at).label('earliest_flight'),
            func.max(Flight.created_at).label('latest_flight')
        ).filter(
            Flight.race_id == race_id,
            Flight.created_at >= opentime_dt,
            Flight.created_at <= closetime_dt
        )
        
        if source:
            stats = stats.filter(Flight.source == source)
        
        stats_result = stats.first()
        
        # Get pilot list with flight counts (limited data)
        pilot_summary = db.query(
            Flight.pilot_id,
            Flight.pilot_name,
            func.count(Flight.id).label('flight_count'),
            func.max(Flight.created_at).label('last_activity')
        ).filter(
            Flight.race_id == race_id,
            Flight.created_at >= opentime_dt,
            Flight.created_at <= closetime_dt
        )
        
        if source:
            pilot_summary = pilot_summary.filter(Flight.source == source)
        
        pilot_summary = pilot_summary.group_by(
            Flight.pilot_id,
            Flight.pilot_name
        ).order_by(
            func.max(Flight.created_at).desc()
        ).limit(100).all()  # Limit to 100 pilots for performance
        
        # Build response
        response = {
            "summary": {
                "total_flights": stats_result.total_flights or 0,
                "total_pilots": stats_result.total_pilots or 0,
                "time_range": {
                    "start": opentime_dt.isoformat(),
                    "end": closetime_dt.isoformat()
                },
                "earliest_activity": stats_result.earliest_flight.isoformat() if stats_result.earliest_flight else None,
                "latest_activity": stats_result.latest_flight.isoformat() if stats_result.latest_flight else None
            },
            "pilots": [
                {
                    "pilot_id": str(pilot.pilot_id),
                    "pilot_name": pilot.pilot_name or "Unknown",
                    "flight_count": pilot.flight_count,
                    "last_activity": pilot.last_activity.isoformat() if pilot.last_activity else None
                }
                for pilot in pilot_summary
            ]
        }
        
        # Cache the response
        with cache_lock:
            summary_cache[cache_key] = response
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating summary: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to generate tracker summary"
        )

@router.get("/live/pilot/{pilot_id}/flights")
async def get_pilot_flights(
    pilot_id: str,
    opentime: str = Query(..., description="Start time"),
    closetime: Optional[str] = Query(None, description="End time"),
    source: Optional[str] = Query(None),
    credentials: HTTPAuthorizationCredentials = Security(security),
    db: Session = Depends(get_replica_db)
) -> Dict[str, Any]:
    """
    Get flights for a specific pilot - called when pilot accordion is expanded.
    This avoids loading all pilot data at once.
    """
    try:
        # Parse times
        opentime_dt = datetime.fromisoformat(
            opentime.strip().replace('Z', '+00:00'))
        
        if not closetime:
            closetime_dt = datetime.now(timezone.utc) + timedelta(hours=24)
        else:
            closetime_dt = datetime.fromisoformat(
                closetime.strip().replace('Z', '+00:00'))
        
        # Validate token (simplified - reuse from above)
        token = credentials.credentials
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=["HS256"],
            audience="api.hikeandfly.app",
            issuer="hikeandfly.app"
        )
        race_id = payload["sub"].split(":")[1]
        
        # Get flights for specific pilot
        flights_query = db.query(Flight).filter(
            Flight.race_id == race_id,
            Flight.pilot_id == pilot_id,
            Flight.created_at >= opentime_dt,
            Flight.created_at <= closetime_dt
        )
        
        if source:
            flights_query = flights_query.filter(Flight.source == source)
        
        flights = flights_query.order_by(Flight.created_at.desc()).limit(20).all()
        
        # Build response with essential flight data
        flight_list = []
        for flight in flights:
            if flight.first_fix and flight.last_fix:
                flight_list.append({
                    "uuid": str(flight.id),
                    "source": flight.source,
                    "created_at": flight.created_at.isoformat(),
                    "first_fix": flight.first_fix,
                    "last_fix": flight.last_fix,
                    "device_id": flight.device_id,
                    # Add basic stats if available
                    "duration_seconds": (
                        datetime.fromisoformat(flight.last_fix['datetime'].replace('Z', '+00:00')) -
                        datetime.fromisoformat(flight.first_fix['datetime'].replace('Z', '+00:00'))
                    ).total_seconds() if flight.first_fix and flight.last_fix else 0
                })
        
        return {
            "pilot_id": pilot_id,
            "flights": flight_list
        }
        
    except Exception as e:
        logger.error(f"Error getting pilot flights: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to get pilot flights"
        )