from fastapi import APIRouter, Depends, HTTPException, Query, Security
from sqlalchemy.orm import Session
from database.schemas import LiveTrackingRequest, LiveTrackPointCreate, FlightResponse, TrackUploadRequest
from pydantic import ValidationError
from database.models import UploadedTrackPoint, Flight, LiveTrackPoint, Race
from typing import List, Dict, Any, Optional
from database.db_conf import get_db
import logging
from api.auth import verify_tracking_token
from sqlalchemy.exc import SQLAlchemyError  
from uuid import uuid4  
from sqlalchemy.dialects.postgresql import insert
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from datetime import datetime, timezone, timedelta
import jwt
from config import settings

logger = logging.getLogger(__name__)

router = APIRouter()

security = HTTPBearer()


@router.post("/live", status_code=202)
async def live_tracking(
    data: LiveTrackingRequest,
    token: str = Query(..., description="Authentication token"),
    token_data: Dict = Depends(verify_tracking_token),
    db: Session = Depends(get_db)
):
    try:
        pilot_id = token_data['pilot_id']
        race_id = token_data['race_id']
        pilot_name = token_data['pilot_name']
        race_data = token_data['race']
        
        # Check/create race record
        race = db.query(Race).filter(Race.race_id == race_id).first()
        if not race:
            race = Race(
                race_id=race_id,
                name=race_data['name'],
                date=datetime.fromisoformat(race_data['date']),
                end_date=datetime.fromisoformat(race_data['end_date']),
                timezone=race_data['timezone'],
                location=race_data['location']
            )
            db.add(race)
            try:
                db.commit()
            except SQLAlchemyError as e:
                db.rollback()
                logger.error(f"Failed to create race record: {str(e)}")
                raise HTTPException(status_code=500, detail="Failed to create race record")

        flight = db.query(Flight).filter(Flight.flight_id == data.flight_id).first()
        
        latest_point = data.track_points[-1]
        latest_datetime = datetime.fromisoformat(latest_point['datetime'].replace('Z', '+00:00')).astimezone(timezone.utc)
        
        if not flight:
            first_point = data.track_points[0]
            first_datetime = datetime.fromisoformat(first_point['datetime'].replace('Z', '+00:00')).astimezone(timezone.utc)
            
            
            flight = Flight(
                flight_id=data.flight_id,
                race_uuid=race.id,
                race_id=race_id,
                pilot_id=pilot_id,
                pilot_name=pilot_name,
                created_at=datetime.now(timezone.utc),
                source='live',
                first_fix={
                    'lat': first_point['lat'],
                    'lon': first_point['lon'],
                    'elevation': first_point.get('elevation'),
                    'datetime': first_datetime.strftime('%Y-%m-%dT%H:%M:%SZ')
                },
                last_fix={
                    'lat': latest_point['lat'],
                    'lon': latest_point['lon'],
                    'elevation': latest_point.get('elevation'),
                    'datetime': latest_datetime.strftime('%Y-%m-%dT%H:%M:%SZ')
                },
                total_points=len(data.track_points)
            )
            db.add(flight)

        elif flight.pilot_id != pilot_id:
            raise HTTPException(
                status_code=403,
                detail="Not authorized to update this flight"
            )
        else:
            # Update last_fix, total_points and ensure pilot_name is current
            flight.last_fix = {
                'lat': latest_point['lat'],
                'lon': latest_point['lon'],
                'elevation': latest_point.get('elevation'),
                'datetime': latest_datetime.strftime('%Y-%m-%dT%H:%M:%SZ')
            }
            flight.total_points = flight.total_points + len(data.track_points)
            flight.pilot_name = pilot_name  # Update pilot name in case it changed

        try:
            db.commit()
            logger.info(f"Successfully updated flight record: {data.flight_id}")
        except SQLAlchemyError as e:
            db.rollback()
            logger.error(f"Failed to update flight: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail="Failed to update flight record"
            )

        # Convert track points using Pydantic model
        track_points = [
            LiveTrackPoint(
                **LiveTrackPointCreate(
                    flight_id=data.flight_id,
                    flight_uuid=flight.id,
                    datetime=datetime.fromisoformat(point['datetime'].replace('Z', '+00:00'))
                             .astimezone(timezone.utc)
                             .strftime('%Y-%m-%dT%H:%M:%SZ'),  # Format as ISO 8601 with Z suffix
                    lat=point['lat'],
                    lon=point['lon'],
                    elevation=point.get('elevation')
                ).model_dump()
            ) for point in data.track_points
        ]

        logger.info(f"Saving {len(track_points)} track points for flight {data.flight_id}")
        
        try:
            # Use insert().on_conflict_do_nothing() instead of bulk_save_objects
            stmt = insert(LiveTrackPoint).on_conflict_do_nothing(
                index_elements=['flight_id', 'lat', 'lon', 'datetime']
            )
            db.execute(stmt, [vars(point) for point in track_points])
            db.commit()
            logger.info(f"Successfully saved track points for flight {data.flight_id}")
            
            return {
                'success': True,
                'message': f'Live tracking data processed ({len(track_points)} points)',
                'flight_id': data.flight_id,
                'pilot_name': pilot_name,
                'total_points': flight.total_points
            }
        except SQLAlchemyError as e:
            db.rollback()
            logger.error(f"Failed to save track points: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail="Failed to save track points"
            )

        except SQLAlchemyError as e:
            db.rollback()
            logger.error(f"Database error: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail="Database error while processing request"
            )
            
    except Exception as e:
        logger.error(f"Unexpected error in live_tracking: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Failed to process tracking data"
        )
        

@router.post("/upload", status_code=202, response_model=FlightResponse)
async def upload_track(
    upload_data: TrackUploadRequest,
    token: str = Query(..., description="Authentication token"),
    db: Session = Depends(get_db),
    token_data: dict = Depends(verify_tracking_token)
):
    """Handle complete track upload from mobile devices"""
    try:
        # Get data from token
        pilot_id = token_data['pilot_id']
        race_id = token_data['race_id']
        pilot_name = token_data['pilot_name']
        race_data = token_data['race']

        # Check/create race record
        race = db.query(Race).filter(Race.race_id == race_id).first()
        if not race:
            race = Race(
                race_id=race_id,
                name=race_data['name'],
                date=datetime.fromisoformat(race_data['date']),
                end_date=datetime.fromisoformat(race_data['end_date']),
                timezone=race_data['timezone'],
                location=race_data['location']
            )
            db.add(race)
            try:
                db.commit()
            except SQLAlchemyError as e:
                db.rollback()
                logger.error(f"Failed to create race record: {str(e)}")
                raise HTTPException(status_code=500, detail="Failed to create race record")

        if not upload_data.track_points:
            logger.info(f"Received empty track upload from pilot {pilot_id} - discarding")
            return Flight(
                id=uuid4(),
                flight_id=upload_data.flight_id,
                race_uuid=race.id,
                race_id=race_id,
                pilot_id=pilot_id,
                pilot_name=pilot_name,
                source='upload',
                created_at=datetime.now(timezone.utc)
            )

        logger.info(f"Received track upload from pilot {pilot_id} for race {race_id}")
        logger.info(f"Total points: {len(upload_data.track_points)}")

        try:
            # Check for existing flight
            flight = db.query(Flight).filter(
                Flight.flight_id == upload_data.flight_id,
                Flight.source == 'upload'
            ).first()            

            if flight:
                raise HTTPException(
                    status_code=409,
                    detail="Flight ID with source upload already exists. Each flight must have a unique ID."
                )

            # Process first and last points
            first_point = upload_data.track_points[0]
            last_point = upload_data.track_points[-1]
            first_datetime = datetime.fromisoformat(first_point['datetime'].replace('Z', '+00:00')).astimezone(timezone.utc)
            last_datetime = datetime.fromisoformat(last_point['datetime'].replace('Z', '+00:00')).astimezone(timezone.utc)

            # Create new flight with all fields aligned
            flight = Flight(
                flight_id=upload_data.flight_id,
                race_uuid=race.id,
                race_id=race_id,
                pilot_id=pilot_id,
                pilot_name=pilot_name,
                created_at=datetime.now(timezone.utc),
                source='upload',
                first_fix={
                    'lat': first_point['lat'],
                    'lon': first_point['lon'],
                    'elevation': first_point.get('elevation'),
                    'datetime': first_datetime.strftime('%Y-%m-%dT%H:%M:%SZ')
                },
                last_fix={
                    'lat': last_point['lat'],
                    'lon': last_point['lon'],
                    'elevation': last_point.get('elevation'),
                    'datetime': last_datetime.strftime('%Y-%m-%dT%H:%M:%SZ')
                },
                total_points=len(upload_data.track_points)
            )
            db.add(flight)
            
            try:
                db.commit()
            except SQLAlchemyError as e:
                db.rollback()
                logger.error(f"Failed to create flight record: {str(e)}")
                raise HTTPException(status_code=500, detail="Failed to create flight record")

            # Convert and store track points
            track_points_db = [
                UploadedTrackPoint(
                    flight_id=upload_data.flight_id,
                    flight_uuid=flight.id,
                    datetime=datetime.fromisoformat(point['datetime'].replace('Z', '+00:00')).astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                    lat=point['lat'],
                    lon=point['lon'],
                    elevation=point.get('elevation')
                )
                for point in upload_data.track_points
            ]
            
            try:
                stmt = insert(UploadedTrackPoint).on_conflict_do_nothing(
                    index_elements=['flight_id', 'lat', 'lon', 'datetime']
                )
                db.execute(stmt, [vars(point) for point in track_points_db])
                db.commit()
                logger.info(f"Successfully processed upload for flight {upload_data.flight_id}")
                return flight
            except SQLAlchemyError as e:
                db.rollback()
                logger.error(f"Failed to save track points: {str(e)}")
                raise HTTPException(status_code=500, detail="Failed to save track points")

        except SQLAlchemyError as e:
            db.rollback()
            logger.error(f"Database error while processing upload: {str(e)}")
            raise HTTPException(status_code=500, detail="Database error while processing upload")
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing track upload: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to process track data")
        


        
@router.get("/flights")
async def get_flights(
    pilot_id: Optional[str] = Query(None, description="Filter by pilot ID"),
    race_id: Optional[str] = Query(None, description="Filter by race ID"),
    source: Optional[str] = Query(None, description="Filter by source ('live' or 'upload')"),
    db: Session = Depends(get_db)
):
    """Get all flights with optional filtering"""
    try:
        # Start with base query
        query = db.query(Flight)
        
        # Apply filters if provided
        if pilot_id:
            query = query.filter(Flight.pilot_id == pilot_id)
        if race_id:
            query = query.filter(Flight.race_id == race_id)
        if source:
            query = query.filter(Flight.source == source)
            
        # Order by created_at descending (newest first)
        query = query.order_by(Flight.created_at.desc())
        
        flights = query.all()
        
        return {
            'success': True,
            'total': len(flights),
            'flights': [{
                'flight_id': flight.flight_id,
                'pilot_id': flight.pilot_id,
                'race_id': flight.race_id,
                'source': flight.source,
                'created_at': flight.created_at.isoformat() if flight.created_at else None,
                'start_time': flight.start_time.isoformat() if flight.start_time else None,
                'end_time': flight.end_time.isoformat() if flight.end_time else None,
                'total_points': flight.total_points,
                'metadata': flight.flight_metadata
            } for flight in flights]
        }
        
    except Exception as e:
        logger.error(f"Error retrieving flights: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve flights: {str(e)}"
        )
        

@router.get("/pilot/tracks")
async def get_pilot_race_tracks(
    token: str = Query(..., description="Authentication token"),
    token_data: Dict = Depends(verify_tracking_token),
    db: Session = Depends(get_db)
):
    """
    Get all tracks for a specific pilot in a specific race.
    Uses pilot_id and race_id from the tracking token for authorization.
    Returns basic metadata for each track to help identify them.
    """
    try:
        # Get IDs from token
        pilot_id = token_data['pilot_id']
        race_id = token_data['race_id']
        
        # Query flights for this pilot and race
        flights = db.query(Flight).filter(
            Flight.pilot_id == pilot_id,
            Flight.race_id == race_id,
            Flight.source == 'upload'  # Only get uploaded tracks
        ).order_by(Flight.created_at.desc()).all()
        
        # Format track information
        tracks = []
        for flight in flights:
            metadata = flight.flight_metadata or {}
            tracks.append({
                'flight_id': flight.flight_id,
                'created_at': flight.created_at.strftime('%Y-%m-%dT%H:%M:%SZ') if flight.created_at else None,
                'type': flight.source,
                'collection': 'uploads' if flight.source == 'upload' else 'live',
                'start_time': flight.start_time.strftime('%Y-%m-%dT%H:%M:%SZ') if flight.start_time else None,
                'end_time': flight.end_time.strftime('%Y-%m-%dT%H:%M:%SZ') if flight.end_time else None,
                'duration': metadata.get('duration'),
                'distance': metadata.get('distance'),
                'avg_speed': metadata.get('avg_speed'),
                'max_speed': metadata.get('max_speed'),
                'max_altitude': metadata.get('max_altitude'),
                'total_points': flight.total_points
            })
        
        return {
            'success': True,
            'pilot_id': pilot_id,
            'race_id': race_id,
            'total_tracks': len(tracks),
            'tracks': tracks
        }
        
    except Exception as e:
        logger.error(f"Error retrieving pilot tracks: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve pilot tracks: {str(e)}"
        )
        
        
        
@router.delete("/tracks/{flight_id}")
async def delete_track(
    flight_id: str,
    token: str = Query(..., description="Authentication token"),
    token_data: Dict = Depends(verify_tracking_token),
    db: Session = Depends(get_db)
):
    """
    Delete a specific track from the database.
    Verifies that the track belongs to the pilot from the token.
    """
    try:
        # Get pilot_id and race_id from token
        pilot_id = token_data['pilot_id']
        race_id = token_data['race_id']
        
        # First verify the track belongs to this pilot and race
        flight = db.query(Flight).filter(
            Flight.flight_id == flight_id,
            Flight.pilot_id == pilot_id,
            Flight.race_id == race_id
        ).first()
        
        if not flight:
            return {
                'success': False,
                'message': 'Track not found or not authorized to delete it'
            }
        
        try:
            # Delete points from both tables
            live_points = db.query(LiveTrackPoint).filter(
                LiveTrackPoint.flight_id == flight_id
            ).delete()
            
            uploaded_points = db.query(UploadedTrackPoint).filter(
                UploadedTrackPoint.flight_id == flight_id
            ).delete()
            
            # Delete the flight records
            flight_result = db.query(Flight).filter(
                Flight.flight_id == flight_id
            ).delete()
            
            db.commit()
            
            total_points_deleted = live_points + uploaded_points
            logger.info(f"Deleted {total_points_deleted} track points from TimescaleDB for flight {flight_id}")
            
            if flight_result > 0:
                return {
                    'success': True,
                    'message': f'Track {flight_id} deleted successfully',
                    'details': {
                        'points_deleted': {
                            'total': total_points_deleted,
                            'live': live_points,
                            'uploaded': uploaded_points
                        },
                        'metadata_deleted': {
                            'total': flight_result,
                            'live': flight_result if flight.source == 'live' else 0,
                            'uploaded': flight_result if flight.source == 'upload' else 0
                        }
                    }
                }
            
            return {
                'success': False,
                'message': 'Failed to delete track metadata'
            }
            
        except SQLAlchemyError as e:
            db.rollback()
            logger.error(f"Error deleting track points from TimescaleDB: {str(e)}")
            raise
            
    except Exception as e:
        logger.error(f"Error deleting track: {str(e)}")
        return {
            'error': 'Failed to delete track',
            'details': str(e)
        }
        
        
        
@router.get("/live/points/{flight_id}")
async def get_live_points(
    flight_id: str,
    credentials: HTTPAuthorizationCredentials = Security(security),
    token_data: Dict = Depends(verify_tracking_token),
    last_fix_time: Optional[datetime] = Query(None, description="Only return points after this time"),
    db: Session = Depends(get_db)
):
    """
    Get all live tracking points for a specific flight in GeoJSON format.
    Requires JWT token in Authorization header (Bearer token).
    Returns points with 1-second sampling and optional barometric altitude.
    """
    try:
        # Get token from Authorization header
        # token = credentials.credentials  # This extracts the token from "Bearer {token}"
        # Get flight from database
        flight = db.query(Flight).filter(
            Flight.flight_id == flight_id.rstrip('\t|'),
            Flight.source == 'live'
        ).first()
            
        if not flight:
            raise HTTPException(
                status_code=404,
                detail="Flight not found in live collection"
            )

        # Verify pilot has access to this flight
        pilot_id = token_data['pilot_id']
        race_id = token_data['race_id']
        
        if flight.pilot_id != pilot_id or flight.race_id != race_id:
            raise HTTPException(
                status_code=403,
                detail="Not authorized to access this flight"
            )
        
        # Convert last_fix_time if provided
        last_fix_datetime = None
        if last_fix_time:
            last_fix_datetime = datetime.fromisoformat(last_fix_time.replace('Z', '+00:00'))
        
        # Build query for track points
        if last_fix_datetime:
            query = query.filter(LiveTrackPoint.datetime > last_fix_datetime)

        
        track_points = query.order_by(LiveTrackPoint.datetime).all()
        
        if not track_points:
            return {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": []
                },
                "properties": {
                    "uuid": str(flight.id),
                    "firstFixTime": None,
                    "lastFixTime": None
                }
            }

        coordinates = []
        last_time = None
        is_first_point = True
        
        for point in track_points:
            current_time = point.datetime
            
            # Basic coordinate array with required fields
            coordinate = [
                float(point.lon),  # x/longitude
                float(point.lat),  # y/latitude
                int(point.elevation or 0)  # z/gps altitude
            ]
            
            if is_first_point:
                # Only the very first point gets dt: 0
                extra_data = {"dt": 0}
                if hasattr(point, 'baro_altitude') and point.baro_altitude is not None:
                    extra_data["b"] = int(point.baro_altitude)
                coordinate.append(extra_data)
                is_first_point = False
            elif last_time is not None:
                # Calculate time delta for subsequent points
                dt = int((current_time - last_time).total_seconds())
                if dt != 1:  # Only add dt if not 1 second
                    extra_data = {"dt": dt}
                    if hasattr(point, 'baro_altitude') and point.baro_altitude is not None:
                        extra_data["b"] = int(point.baro_altitude)
                    coordinate.append(extra_data)
            
            coordinates.append(coordinate)
            last_time = current_time

        return {
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": coordinates
            },
            "properties": {
                "uuid": str(flight.id),
                "firstFixTime": track_points[0].datetime.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "lastFixTime": track_points[-1].datetime.strftime("%Y-%m-%dT%H:%M:%SZ")
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving flight points: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve flight points: {str(e)}"
        )
    

@router.get("/upload/points/{flight_id}")
async def get_uploaded_points(
    flight_id: str,
    credentials: HTTPAuthorizationCredentials = Security(security),
    token_data: Dict = Depends(verify_tracking_token),
    last_fix_time: Optional[str] = Query(None, description="Only return points after this time (ISO 8601 format, e.g. 2025-01-25T06:00:00Z)"),
    db: Session = Depends(get_db)
):
    """
    Get all uploaded track points for a specific flight in GeoJSON format.
    Requires JWT token in Authorization header (Bearer token).
    Returns points with 1-second sampling and optional barometric altitude.
    """
    try:
        # Convert last_fix_time if provided
        last_fix_datetime = None
        if last_fix_time:
            last_fix_datetime = datetime.fromisoformat(last_fix_time.replace('Z', '+00:00'))

        flight = db.query(Flight).filter(
            Flight.flight_id == flight_id.rstrip('\t|'),
            Flight.source == 'upload'
        ).first()
            
        if not flight:
            raise HTTPException(
                status_code=404,
                detail="Flight not found in upload collection"
            )

        # Verify pilot has access to this flight
        pilot_id = token_data['pilot_id']
        race_id = token_data['race_id']
        
        if flight.pilot_id != pilot_id or flight.race_id != race_id:
            raise HTTPException(
                status_code=403,
                detail="Not authorized to access this flight"
            )
        
        # Build query for track points
        query = db.query(UploadedTrackPoint).filter(
            UploadedTrackPoint.flight_id == flight_id
        )

        if last_fix_datetime:
            query = query.filter(UploadedTrackPoint.datetime > last_fix_datetime)

        track_points = query.order_by(UploadedTrackPoint.datetime).all()
        
        if not track_points:
            return {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": []
                },
                "properties": {
                    "uuid": str(flight.id),
                    "firstFixTime": None,
                    "lastFixTime": None
                }
            }

        coordinates = []
        last_time = None
        is_first_point = True
        
        for point in track_points:
            current_time = point.datetime
            
            coordinate = [
                float(point.lon),
                float(point.lat),
                int(point.elevation or 0)
            ]
            
            if is_first_point:
                extra_data = {"dt": 0}
                if hasattr(point, 'baro_altitude') and point.baro_altitude is not None:
                    extra_data["b"] = int(point.baro_altitude)
                coordinate.append(extra_data)
                is_first_point = False
            elif last_time is not None:
                dt = int((current_time - last_time).total_seconds())
                if dt != 1:
                    extra_data = {"dt": dt}
                    if hasattr(point, 'baro_altitude') and point.baro_altitude is not None:
                        extra_data["b"] = int(point.baro_altitude)
                    coordinate.append(extra_data)
            
            coordinates.append(coordinate)
            last_time = current_time

        return {
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": coordinates
            },
            "properties": {
                "uuid": str(flight.id),
                "firstFixTime": track_points[0].datetime.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "lastFixTime": track_points[-1].datetime.strftime("%Y-%m-%dT%H:%M:%SZ")
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving flight points: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve flight points: {str(e)}"
        )
        
        
        
def determine_if_landed(point) -> bool:
    """Determine if a pilot has landed based on track point data"""
    # Implement your landing detection logic here
    return False

def get_first_fix(db: Session, flight_id: str) -> list:
    """Get the first fix for a flight"""
    first_point = (
        db.query(LiveTrackPoint)
        .filter(LiveTrackPoint.flight_id == flight_id)
        .order_by(LiveTrackPoint.datetime.asc())
        .first()
    )
    
    if first_point:
        return [
            first_point.lon,
            first_point.lat,
            first_point.elevation or 0,
            {
                "b": first_point.elevation or 0
            }
        ]
    return []


@router.get("/live/users")
async def get_live_users(
    opentime: str = Query(..., description="Start time for tracking window (ISO 8601 format, e.g. 2025-01-25T06:00:00Z)"),
    closetime: Optional[str] = Query(None, description="End time for tracking window (ISO 8601 format, e.g. 2025-01-25T06:00:00Z)"),
    source: Optional[str] = Query(None, regex="^(live|upload)$"),
    credentials: HTTPAuthorizationCredentials = Security(security),
    db: Session = Depends(get_db)
):
    """
    Return active users and their flights within the specified time window.
    Requires JWT bearer token for authentication.
    """
    try:
        # Convert ISO string to datetime
        opentime_dt = datetime.fromisoformat(opentime.replace('Z', '+00:00'))
        
        # Set default closetime if not provided, otherwise convert from ISO
        if not closetime:
            closetime_dt = datetime.now(timezone.utc) + timedelta(hours=24)
        else:
            closetime_dt = datetime.fromisoformat(closetime.replace('Z', '+00:00'))


        # Validate JWT token
        token = credentials.credentials
        try:
            payload = jwt.decode(
                token,
                settings.SECRET_KEY,
                algorithms=["HS256"],
                audience="api.hikeandfly.app",
                issuer="hikeandfly.app"
            )
            
            if not payload.get("sub", "").startswith("contest:"):
                raise HTTPException(
                    status_code=403,
                    detail="Invalid token subject - must be contest-specific"
                )
            
            race_id = payload["sub"].split(":")[1]
            
        except jwt.ExpiredSignatureError:
            raise HTTPException(
                status_code=401,
                detail="Token has expired"
            )
        except jwt.JWTError as e:
            raise HTTPException(
                status_code=401,
                detail=f"Invalid token: {str(e)}"
            )

        # Get all active flights for this race within the time window
        flights = (
            db.query(Flight)
            .filter(
                Flight.race_id == race_id,
                Flight.created_at >= opentime_dt,
                Flight.created_at <= closetime_dt
            )
        )
        
        if source:
            flights = flights.filter(Flight.source == source)
            
        flights = flights.all()

        # Structure the response
        response = {
            "pilots": {}
        }

        for flight in flights:
            pilot_id = str(flight.pilot_id)
            
            # Add user info if not already present
            if pilot_id not in response["users"]:
                response["users"][pilot_id] = {
                    "fullname": flight.pilot_name,
                    "lastLoc": {
                        "type": "Feature",
                        "geometry": {
                            "type": "Point",
                            "coordinates": [
                                flight.last_fix['lon'],
                                flight.last_fix['lat'],
                                flight.last_fix.get('elevation', 0)
                            ]
                        },
                        "properties": {
                            "source": flight.source,
                            "landed": determine_if_landed(flight.last_fix)
                        }
                    },
                    "flights": []  # Initialize empty flights array for each user
                }

            # Add flight info under the user's flights array
            flight_info = {
                "uuid": str(flight.id),
                "firstFix": [
                    flight.first_fix['lon'],
                    flight.first_fix['lat'],
                    flight.first_fix.get('elevation', 0),
                    {"t": flight.first_fix['datetime']}
                ],
                "lastFix": [
                    flight.last_fix['lon'],
                    flight.last_fix['lat'],
                    flight.last_fix.get('elevation', 0),
                    {
                        "t": flight.last_fix['datetime'],
                        "b": flight.last_fix.get('elevation', 0)
                    }
                ],
                "source": flight.source,
                "landed": determine_if_landed(flight.last_fix),
                "clientId": "mobile",
                "simulation": False,
                "glider": "unknown"
            }
            
            response["users"][pilot_id]["flights"].append(flight_info)

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching live users: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch live users: {str(e)}"
        )