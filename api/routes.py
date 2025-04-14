from fastapi import APIRouter, Depends, HTTPException, Query, Security, WebSocket, WebSocketDisconnect, Body
from sqlalchemy.orm import Session
from database.schemas import LiveTrackingRequest, LiveTrackPointCreate, FlightResponse, TrackUploadRequest, NotificationCommand, NotificationToken, SubscriptionRequest, UnsubscriptionRequest, NotificationRequest
from database.models import UploadedTrackPoint, Flight, LiveTrackPoint, Race, NotificationTokenDB
from typing import Dict, Optional
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
from math import radians, sin, cos, sqrt, atan2
from uuid import UUID
from sqlalchemy import func  # Add this at the top with other imports
from aiohttp import ClientSession
from jwt.exceptions import PyJWTError
from fastapi.responses import HTMLResponse
from starlette.websockets import WebSocketState
import asyncio
import json
from ws_conn import manager
# Import Expo Push Notification modules
from exponent_server_sdk import (
    DeviceNotRegisteredError,
    PushClient,
    PushMessage,
    PushServerError,
)


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
                raise HTTPException(
                    status_code=500, detail="Failed to create race record")

        flight = db.query(Flight).filter(
            Flight.flight_id == data.flight_id).first()

        try:
            device_id = data.track_points[0].get('device_id', 'anonymous')
        except (IndexError, AttributeError, TypeError):
            device_id = 'anonymous'
        
        latest_point = data.track_points[-1]
        latest_datetime = datetime.fromisoformat(
            latest_point['datetime'].replace('Z', '+00:00')).astimezone(timezone.utc)

        if not flight:
            first_point = data.track_points[0]
            first_datetime = datetime.fromisoformat(
                first_point['datetime'].replace('Z', '+00:00')).astimezone(timezone.utc)

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
                total_points=len(data.track_points),
                device_id=device_id
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
            logger.info(
                f"Successfully updated flight record: {data.flight_id}")
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
                    datetime=datetime.fromisoformat(
                        point['datetime'].replace('Z', '+00:00'))
                    .astimezone(timezone.utc)
                    # Format as ISO 8601 with Z suffix
                    .strftime('%Y-%m-%dT%H:%M:%SZ'),
                    lat=point['lat'],
                    lon=point['lon'],
                    elevation=point.get('elevation'),
                    device_id=device_id
                ).model_dump()
            ) for point in data.track_points
        ]
        logger.info(data)
        logger.info(track_points)
        logger.info(
            f"Saving {len(track_points)} track points for flight {data.flight_id}")

        try:
            # Use insert().on_conflict_do_nothing() instead of bulk_save_objects
            stmt = insert(LiveTrackPoint).on_conflict_do_nothing(
                index_elements=['flight_id', 'lat', 'lon', 'datetime']
            )
            db.execute(stmt, [vars(point) for point in track_points])
            db.commit()
            logger.info(
                f"Successfully saved track points for flight {data.flight_id}")

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
                raise HTTPException(
                    status_code=500, detail="Failed to create race record")

        if not upload_data.track_points:
            logger.info(
                f"Received empty track upload from pilot {pilot_id} - discarding")
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

        logger.info(
            f"Received track upload from pilot {pilot_id} for race {race_id}")
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

            try:
                device_id = upload_data.track_points[0].get('device_id', 'anonymous')
            except (IndexError, AttributeError, TypeError):
                device_id = 'anonymous'

            # Process first and last points
            first_point = upload_data.track_points[0]
            last_point = upload_data.track_points[-1]
            first_datetime = datetime.fromisoformat(
                first_point['datetime'].replace('Z', '+00:00')).astimezone(timezone.utc)
            last_datetime = datetime.fromisoformat(
                last_point['datetime'].replace('Z', '+00:00')).astimezone(timezone.utc)

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
                total_points=len(upload_data.track_points),
                device_id=device_id
            )
            db.add(flight)

            try:
                db.commit()
            except SQLAlchemyError as e:
                db.rollback()
                logger.error(f"Failed to create flight record: {str(e)}")
                raise HTTPException(
                    status_code=500, detail="Failed to create flight record")

            # Convert and store track points
            track_points_db = [
                UploadedTrackPoint(
                    flight_id=upload_data.flight_id,
                    flight_uuid=flight.id,
                    datetime=datetime.fromisoformat(point['datetime'].replace(
                        'Z', '+00:00')).astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                    lat=point['lat'],
                    lon=point['lon'],
                    elevation=point.get('elevation'),
                    device_id=device_id
                )
                for point in upload_data.track_points
            ]

            try:
                stmt = insert(UploadedTrackPoint).on_conflict_do_nothing(
                    index_elements=['flight_id', 'lat', 'lon', 'datetime']
                )
                db.execute(stmt, [vars(point) for point in track_points_db])
                db.commit()
                logger.info(
                    f"Successfully processed upload for flight {upload_data.flight_id}")
                return flight
            except SQLAlchemyError as e:
                db.rollback()
                logger.error(f"Failed to save track points: {str(e)}")
                raise HTTPException(
                    status_code=500, detail="Failed to save track points")

        except SQLAlchemyError as e:
            db.rollback()
            logger.error(f"Database error while processing upload: {str(e)}")
            raise HTTPException(
                status_code=500, detail="Database error while processing upload")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing track upload: {str(e)}")
        raise HTTPException(
            status_code=500, detail="Failed to process track data")


@router.get("/flights")
async def get_flights(
    pilot_id: Optional[str] = Query(None, description="Filter by pilot ID"),
    race_id: Optional[str] = Query(None, description="Filter by race ID"),
    source: Optional[str] = Query(
        None, description="Filter by source ('live' or 'upload')"),
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
                'metadata': flight.flight_metadata,
                'device_id': flight.device_id
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
            # Calculate metrics from first_fix and last_fix
            first_datetime = datetime.fromisoformat(
                flight.first_fix['datetime'].replace('Z', '+00:00'))
            last_datetime = datetime.fromisoformat(
                flight.last_fix['datetime'].replace('Z', '+00:00'))

            duration_td = last_datetime - first_datetime
            hours, remainder = divmod(int(duration_td.total_seconds()), 3600)
            minutes, seconds = divmod(remainder, 60)
            duration = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

            # Get location name from Google Geocoding API
            lat = float(flight.first_fix['lat'])
            lon = float(flight.first_fix['lon'])
            location_name = None

            try:
                async with ClientSession() as session:  # Create new session for each request
                    url = f"https://maps.googleapis.com/maps/api/geocode/json?latlng={lat},{lon}&key={settings.GOOGLE_MAPS_API_KEY}"
                    async with session.get(url) as response:
                        if response.status == 200:
                            data = await response.json()
                            if data['results']:
                                # Get the most relevant result (first one)
                                address_components = data['results'][0]['address_components']
                                for component in address_components:
                                    if 'locality' in component['types']:
                                        location_name = component['long_name']
                                        break
                                    elif 'administrative_area_level_2' in component['types']:
                                        location_name = component['long_name']
                                        break
                                    elif 'administrative_area_level_1' in component['types']:
                                        location_name = component['long_name']
                                        break
            except Exception as e:
                logger.error(f"Error fetching location name: {str(e)}")

            def calculate_distance(lat1, lon1, lat2, lon2):
                R = 6371000  # Earth's radius in meters
                φ1 = radians(lat1)
                φ2 = radians(lat2)
                Δφ = radians(lat2 - lat1)
                Δλ = radians(lon2 - lon1)

                a = sin(Δφ/2) * sin(Δφ/2) + \
                    cos(φ1) * cos(φ2) * \
                    sin(Δλ/2) * sin(Δλ/2)
                c = 2 * atan2(sqrt(a), sqrt(1-a))

                return R * c  # Distance in meters

            distance = calculate_distance(
                float(flight.first_fix['lat']),
                float(flight.first_fix['lon']),
                float(flight.last_fix['lat']),
                float(flight.last_fix['lon'])
            )

            # Calculate speeds (m/s)
            avg_speed = distance / \
                duration_td.total_seconds() if duration_td.total_seconds() > 0 else 0

            tracks.append({
                'flight_id': flight.flight_id,
                'created_at': flight.created_at.strftime('%Y-%m-%dT%H:%M:%SZ') if flight.created_at else None,
                'type': flight.source,
                'collection': 'uploads' if flight.source == 'upload' else 'live',
                'start_time': first_datetime.strftime('%Y-%m-%dT%H:%M:%SZ'),
                'end_time': last_datetime.strftime('%Y-%m-%dT%H:%M:%SZ'),
                'duration': duration,
                'distance': round(distance, 2),  # Distance in meters
                'avg_speed': round(avg_speed * 3.6, 2),  # Convert to km/h
                'max_altitude': 0,
                'max_speed': 0,
                'total_points': flight.total_points,
                'location': location_name  # Add the location name to the response

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
        flights = db.query(Flight).filter(
            Flight.flight_id == flight_id,
            Flight.pilot_id == pilot_id,
            Flight.race_id == race_id
        ).all()

        if not flights:
            return {
                'success': False,
                'message': 'Track not found or not authorized to delete it'
            }

        total_points = 0
        deleted_info = {'live': 0, 'upload': 0}
        race_uuid = None

        # Delete all matching flights
        for flight in flights:
            total_points += flight.total_points
            deleted_info[flight.source] = flight.total_points
            race_uuid = flight.race_uuid
            db.delete(flight)

        # Check if this was the last flight for this race
        if race_uuid:
            remaining_flights = db.query(Flight).filter(
                Flight.race_uuid == race_uuid).count()
            if remaining_flights == 0:
                # If no more flights reference this race, delete it
                race = db.query(Race).filter(Race.id == race_uuid).first()
                if race:
                    db.delete(race)
                    logger.info(
                        f"Deleted race {race_id} as it had no more associated flights")

        db.commit()

        logger.info(
            f"Deleted {len(flights)} flights with id {flight_id} and {total_points} track points")

        return {
            'success': True,
            'message': f'Successfully deleted {len(flights)} flights with {total_points} track points',
            'deleted_points': deleted_info
        }

    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Error deleting track: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Database error while deleting track: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Error deleting track: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete track: {str(e)}"
        )


@router.delete("/tracks/fuuid/{flight_uuid}")
async def delete_track_uuid(
    flight_uuid: UUID,
    source: str = Query(..., regex="^(live|upload)$",
                        description="Track source ('live' or 'upload')"),
    credentials: HTTPAuthorizationCredentials = Security(security),
    db: Session = Depends(get_db)
):
    """
    Delete a specific track from the database.
    Verifies that the track belongs to the specified race.
    Source parameter determines whether to delete 'live' or 'upload' track.
    """
    try:
        # Get token from Authorization header and verify it
        token = credentials.credentials
        try:
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
            raise HTTPException(
                status_code=401,
                detail="Token has expired"
            )
        except PyJWTError as e:
            raise HTTPException(
                status_code=401,
                detail=f"Invalid token: {str(e)}"
            )

        # Verify the track belongs to this race and matches the specified source
        flight = db.query(Flight).filter(
            Flight.id == flight_uuid,
            Flight.race_id == race_id,
            Flight.source == source
        ).first()

        if not flight:
            return {
                'success': False,
                'message': f'Track not found or not authorized to delete it (source: {source})'
            }

        total_points = flight.total_points
        race_uuid = flight.race_uuid

        # Delete the flight
        db.delete(flight)

        # Check if this was the last flight for this race
        if race_uuid:
            remaining_flights = db.query(Flight).filter(
                Flight.race_uuid == race_uuid).count()
            if remaining_flights == 0:
                # If no more flights reference this race, delete it
                race = db.query(Race).filter(Race.id == race_uuid).first()
                if race:
                    db.delete(race)
                    logger.info(
                        f"Deleted race {race_id} as it had no more associated flights")

        db.commit()

        logger.info(
            f"Deleted {source} flight {flight_uuid} with {total_points} track points")

        return {
            'success': True,
            'message': f'Successfully deleted {source} flight with {total_points} track points',
            'deleted_points': {source: total_points}
        }

    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Error deleting track: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Database error while deleting track: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Error deleting track: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete track: {str(e)}"
        )


@router.get("/live/points/{flight_uuid}")
async def get_live_points(
    flight_uuid: UUID,
    credentials: HTTPAuthorizationCredentials = Security(security),
    last_fix_dt: Optional[str] = Query(
        None, description="Only return points after this time (ISO 8601 format, e.g. 2025-01-25T06:00:00Z)"),
    db: Session = Depends(get_db)
):
    """
    Get all live tracking points for a specific flight in GeoJSON format.
    Requires JWT token in Authorization header (Bearer token).
    Returns points with 1-second sampling and optional barometric altitude.
    """
    try:
        # Get token from Authorization header and verify it
        token = credentials.credentials
        try:
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
            raise HTTPException(
                status_code=401,
                detail="Token has expired"
            )
        except PyJWTError as e:
            raise HTTPException(
                status_code=401,
                detail=f"Invalid token: {str(e)}"
            )

        # Convert last_fix_time if provided
        last_fix_datetime = None
        if last_fix_dt:
            last_fix_datetime = datetime.fromisoformat(
                last_fix_dt.replace('Z', '+00:00'))

        # Get flight from database
        flight = db.query(Flight).filter(
            Flight.id == flight_uuid,
            Flight.source == 'live'
        ).first()

        if not flight:
            raise HTTPException(
                status_code=404,
                detail="Flight not found in live collection"
            )

        # Base query
        query = db.query(LiveTrackPoint).filter(
            LiveTrackPoint.flight_uuid == flight_uuid
        )

        # If last_fix_dt is provided, use it as filter
        # Otherwise, use the flight's first fix time
        if last_fix_dt:
            filter_time = datetime.fromisoformat(
                last_fix_dt.replace('Z', '+00:00')).astimezone(timezone.utc)
        else:
            filter_time = datetime.fromisoformat(
                flight.first_fix['datetime'].replace('Z', '+00:00')).astimezone(timezone.utc)

        # Apply the time filter and order the results
        # Remove the func.timezone() call since we're already handling UTC conversion
        query = query.filter(
            LiveTrackPoint.datetime > filter_time
        ).order_by(LiveTrackPoint.datetime)

        track_points = query.all()

        # Ensure all points have timezone information
        all_points = []
        for point in track_points:
            point_dt = point.datetime
            if point_dt.tzinfo is None:
                point_dt = point_dt.replace(tzinfo=timezone.utc)
            point.datetime = point_dt
            all_points.append(point)

        if not track_points:
            logger.warning(
                f"No track points found for flight_uuid: {flight_uuid}")
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
                "lastFixTime": track_points[-1].datetime.strftime("%Y-%m-%dT%H:%M:%SZ"),
                # Number of points in filtered result
                "totalPoints": len(track_points),
                # From flight object
                "flightFirstFix": flight.first_fix['datetime'],
                "flightTotalPoints": flight.total_points         # Total points in flight
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


@router.get("/live/points/{flight_uuid}/raw")
async def get_live_points_raw(
    flight_uuid: UUID,
    credentials: HTTPAuthorizationCredentials = Security(security),
    last_fix_dt: Optional[str] = Query(
        None, description="Only return points after this time (ISO 8601 format, e.g. 2025-01-25T06:00:00Z)"),
    db: Session = Depends(get_db)
):
    """
    Get all live tracking points for a specific flight in raw format.
    Requires JWT token in Authorization header (Bearer token).
    Returns points with datetime, lat, lon, and elevation.
    """
    try:
        # Get token from Authorization header and verify it
        token = credentials.credentials
        try:
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

        except jwt.ExpiredSignatureError:
            raise HTTPException(
                status_code=401,
                detail="Token has expired"
            )
        except PyJWTError as e:
            raise HTTPException(
                status_code=401,
                detail=f"Invalid token: {str(e)}"
            )

        # Get flight from database
        flight = db.query(Flight).filter(
            Flight.id == flight_uuid,
            Flight.source == 'live'
        ).first()

        if not flight:
            raise HTTPException(
                status_code=404,
                detail="Flight not found in live collection"
            )

        # Base query
        query = db.query(LiveTrackPoint).filter(
            LiveTrackPoint.flight_uuid == flight_uuid
        )

        # If last_fix_dt is provided, use it as filter
        if last_fix_dt:
            filter_time = datetime.fromisoformat(
                last_fix_dt.replace('Z', '+00:00')).astimezone(timezone.utc)
            query = query.filter(LiveTrackPoint.datetime > filter_time)

        # Order the results by datetime
        query = query.order_by(LiveTrackPoint.datetime)
        track_points = query.all()

        if not track_points:
            logger.warning(
                f"No track points found for flight_uuid: {flight_uuid}")
            return {
                "success": True,
                "flight_id": str(flight.flight_id),
                "total_points": 0,
                "points": []
            }

        # Format points as simple dictionaries
        points = [{
            "datetime": point.datetime.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "lat": float(point.lat),
            "lon": float(point.lon),
            "elevation": float(point.elevation) if point.elevation is not None else None
        } for point in track_points]

        return {
            "success": True,
            "flight_id": str(flight.flight_id),
            "total_points": len(points),
            "points": points
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving flight points: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve flight points: {str(e)}"
        )


@router.get("/upload/points/{flight_uuid}")
async def get_uploaded_points(
    flight_uuid: UUID,
    credentials: HTTPAuthorizationCredentials = Security(security),
    db: Session = Depends(get_db)
):
    """
    Get all uploaded track points for a specific flight in GeoJSON format.
    Requires JWT token in Authorization header (Bearer token).
    Returns points with 1-second sampling and optional barometric altitude.
    """
    try:
        # Get token from Authorization header and verify it
        token = credentials.credentials
        try:
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

        except jwt.ExpiredSignatureError:
            raise HTTPException(
                status_code=401,
                detail="Token has expired"
            )
        except PyJWTError as e:
            raise HTTPException(
                status_code=401,
                detail=f"Invalid token: {str(e)}"
            )

        # Get flight from database
        flight = db.query(Flight).filter(
            Flight.id == flight_uuid,
            Flight.source == 'upload'
        ).first()

        if not flight:
            raise HTTPException(
                status_code=404,
                detail="Flight not found in upload collection"
            )

        # Get all track points for this flight
        track_points = db.query(UploadedTrackPoint).filter(
            UploadedTrackPoint.flight_uuid == flight_uuid
        ).order_by(UploadedTrackPoint.datetime).all()

        if not track_points:
            logger.warning(
                f"No track points found for flight_id: {flight_uuid}")
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
                # if hasattr(point, 'baro_altitude') and point.baro_altitude is not None:
                #     extra_data["b"] = int(point.baro_altitude)
                # coordinate.append(extra_data)
                is_first_point = False
            elif last_time is not None:
                # Calculate time delta for subsequent points
                dt = int((current_time - last_time).total_seconds())
                if dt != 1:  # Only add dt if not 1 second
                    extra_data = {"dt": dt}
                    # if hasattr(point, 'baro_altitude') and point.baro_altitude is not None:
                    #     extra_data["b"] = int(point.baro_altitude)
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
                "lastFixTime": track_points[-1].datetime.strftime("%Y-%m-%dT%H:%M:%SZ"),
                # Number of points in filtered result
                "totalPoints": len(track_points),
                "flightTotalPoints": flight.total_points         # Total points in flight

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


@router.get("/upload/points/{flight_uuid}/raw")
async def get_uploaded_points_raw(
    flight_uuid: UUID,
    credentials: HTTPAuthorizationCredentials = Security(security),
    db: Session = Depends(get_db)
):
    """
    Get all uploaded track points for a specific flight in raw format.
    Requires JWT token in Authorization header (Bearer token).
    Returns points with datetime, lat, lon, and elevation.
    """
    try:
        # Get token from Authorization header and verify it
        token = credentials.credentials
        try:
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

        except jwt.ExpiredSignatureError:
            raise HTTPException(
                status_code=401,
                detail="Token has expired"
            )
        except PyJWTError as e:
            raise HTTPException(
                status_code=401,
                detail=f"Invalid token: {str(e)}"
            )

        # Get flight from database
        flight = db.query(Flight).filter(
            Flight.id == flight_uuid,
            Flight.source == 'upload'
        ).first()

        if not flight:
            raise HTTPException(
                status_code=404,
                detail="Flight not found in upload collection"
            )

        # Get all track points for this flight
        track_points = db.query(UploadedTrackPoint).filter(
            UploadedTrackPoint.flight_uuid == flight_uuid
        ).order_by(UploadedTrackPoint.datetime).all()

        if not track_points:
            logger.warning(
                f"No track points found for flight_uuid: {flight_uuid}")
            return {
                "success": True,
                "flight_id": str(flight.flight_id),
                "total_points": 0,
                "points": []
            }

        # Format points as simple dictionaries
        points = [{
            "datetime": point.datetime.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "lat": float(point.lat),
            "lon": float(point.lon),
            "elevation": float(point.elevation) if point.elevation is not None else None
        } for point in track_points]

        return {
            "success": True,
            "flight_id": str(flight.flight_id),
            "total_points": len(points),
            "points": points
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
    opentime: str = Query(
        ..., description="Start time for tracking window (ISO 8601 format, e.g. 2025-01-25T06:00:00Z)"),
    closetime: Optional[str] = Query(
        None, description="End time for tracking window (ISO 8601 format, e.g. 2025-01-25T06:00:00Z)"),
    source: Optional[str] = Query(None, regex="^(live|upload)$"),
    credentials: HTTPAuthorizationCredentials = Security(security),
    db: Session = Depends(get_db)
):
    """
    Return active users and their flights within the specified time window.
    Requires JWT bearer token for authentication.
    """
    try:
        # Convert ISO string to datetime and strip any whitespace
        opentime_dt = datetime.fromisoformat(
            opentime.strip().replace('Z', '+00:00'))

        # Set default closetime if not provided, otherwise convert from ISO
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
                    detail="Invalid token subject - must be contest-specific"
                )

            race_id = payload["sub"].split(":")[1]

        except jwt.ExpiredSignatureError:
            raise HTTPException(
                status_code=401,
                detail="Token has expired"
            )
        except PyJWTError as e:
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

        # Structure the response
        response = {
            "pilots": {}
        }

        # First pass: Group flights by pilot and find most recent live fix
        pilot_latest_fixes = {}  # Store the most recent live fix for each pilot

        for flight in flights:
            pilot_id = str(flight.pilot_id)
            # Only consider live flights for lastLoc
            if flight.source == 'live':
                current_fix_time = datetime.fromisoformat(
                    flight.last_fix['datetime'].replace('Z', '+00:00'))

                if pilot_id not in pilot_latest_fixes or \
                   current_fix_time > datetime.fromisoformat(pilot_latest_fixes[pilot_id]['datetime'].replace('Z', '+00:00')):
                    pilot_latest_fixes[pilot_id] = {
                        'fix': flight.last_fix,
                        'datetime': flight.last_fix['datetime'],
                        'pilot_name': flight.pilot_name
                    }

        # Second pass: Build response

        for flight in flights:
            pilot_id = str(flight.pilot_id)

            # Create flight_info dictionary
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
                        "t": flight.last_fix['datetime']
                    }
                ],
                "firstFixTime": flight.first_fix['datetime'],
                "source": flight.source,
                "landed": determine_if_landed(flight.last_fix),
                "clientId": "mobile",
                "glider": "unknown"
            }

            # Add lastLoc only for live flights
            if flight.source == 'live':
                flight_info["lastLoc"] = {
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
                        "source": "live",
                        "landed": determine_if_landed(flight.last_fix)
                    }
                }

            # Add pilot info if not already present
            if pilot_id not in response["pilots"]:
                response["pilots"][pilot_id] = {
                    "fullname": flight.pilot_name,
                    "flights": []
                }

            response["pilots"][pilot_id]["flights"].append(flight_info)

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching live users: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch live users: {str(e)}"
        )


@router.get("/debug/points")
async def get_debug_points(
    source: str = Query(..., regex="^(live|upload)$",
                        description="Track source ('live' or 'upload')"),
    limit: int = Query(1000, description="Maximum number of points to return"),
    flight_uuid: str = Query(None, description="Flight UUID"),
    db: Session = Depends(get_db)
):
    """
    Debug endpoint to get all track points from either live or uploaded flights.
    Requires JWT token in Authorization header (Bearer token).
    Returns raw points with pagination for performance.
    """
    try:

        # Select the appropriate model based on the source
        PointModel = LiveTrackPoint if source == 'live' else UploadedTrackPoint

        # Start building the query
        query = db.query(PointModel)

        # Apply filters if provided
        if flight_uuid:
            query = query.filter(PointModel.flight_id == flight_uuid)

        # Order by datetime for consistency
        query = query.order_by(PointModel.datetime.desc())

        # Apply limit for performance
        query = query.limit(limit)

        # Execute query
        points = query.all()

        # Format points as simple dictionaries
        formatted_points = [{
            "id": str(point.id),
            "flight_id": point.flight_id,
            "flight_uuid": str(point.flight_uuid) if hasattr(point, 'flight_uuid') else None,
            "datetime": point.datetime.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "lat": float(point.lat),
            "lon": float(point.lon),
            "elevation": float(point.elevation) if point.elevation is not None else None
        } for point in points]

        return {
            "success": True,
            "source": source,
            "limit": limit,
            "count": len(formatted_points),
            "points": formatted_points
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving debug points: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve debug points: {str(e)}"
        )


@router.websocket("/ws/track/{race_id}")
async def websocket_tracking_endpoint(
    websocket: WebSocket,
    race_id: str,
    client_id: str = Query(...),
    token: str = Query(...),
    db: Session = Depends(get_db)
):
    """WebSocket endpoint for real-time tracking updates"""
    try:
        # Verify token
        try:
            token_data = jwt.decode(
                token,
                settings.SECRET_KEY,
                algorithms=["HS256"],
                audience="api.hikeandfly.app",
                issuer="hikeandfly.app",
                verify=True
            )

            if not token_data.get("sub", "").startswith("contest:"):
                await websocket.close(code=1008, reason="Invalid token")
                return

            token_race_id = token_data["sub"].split(":")[1]

            # Verify race_id matches token
            if race_id != token_race_id:
                await websocket.close(code=1008, reason="Token not valid for this race")
                return

        except (PyJWTError, jwt.ExpiredSignatureError) as e:
            await websocket.close(code=1008, reason="Invalid token")
            return

        # Connect this client to the race
        await manager.connect(websocket, race_id, client_id)

        # Send initial data - get active flights for this race
        current_time = datetime.now(timezone.utc)
        opentime = current_time - timedelta(hours=24)  # Look back 24 hours

        # Query flights using existing get_live_users logic
        flights = (
            db.query(Flight)
            .filter(
                Flight.race_id == race_id,
                Flight.created_at >= opentime,
                Flight.source == 'live'
            )
            .all()
        )

        # Convert to the expected format
        flight_data = []
        for flight in flights:
            flight_info = {
                "uuid": str(flight.id),
                "pilot_id": flight.pilot_id,
                "pilot_name": flight.pilot_name,
                "firstFix": {
                    "lat": flight.first_fix['lat'],
                    "lon": flight.first_fix['lon'],
                    "elevation": flight.first_fix.get('elevation', 0),
                    "datetime": flight.first_fix['datetime']
                },
                "lastFix": {
                    "lat": flight.last_fix['lat'],
                    "lon": flight.last_fix['lon'],
                    "elevation": flight.last_fix.get('elevation', 0),
                    "datetime": flight.last_fix['datetime']
                },
                "source": flight.source,
            }
            flight_data.append(flight_info)

        # Send initial data to the client
        await websocket.send_json({
            "type": "initial_data",
            "race_id": race_id,
            "flights": flight_data,
            "active_viewers": manager.get_active_viewers(race_id)
        })

        # Keep connection alive and handle client messages
        while True:
            try:
                # Wait for messages with timeout
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30)

                # Message handling remains unchanged...
                try:
                    message = json.loads(data)
                    message_type = message.get("type")

                    if message_type == "ping":
                        await websocket.send_json({"type": "pong", "timestamp": datetime.now(timezone.utc).isoformat()})

                    elif message_type == "request_refresh":
                        # Handle refresh
                        pass

                except json.JSONDecodeError:
                    await websocket.send_json({"type": "error", "message": "Invalid message format"})

            except asyncio.TimeoutError:
                # No message received within timeout period
                # Send a heartbeat to check if connection is still alive
                try:
                    await websocket.send_json({"type": "heartbeat", "timestamp": datetime.now(timezone.utc).isoformat()})
                except Exception:
                    # Connection is likely dead
                    logger.warning(
                        f"Connection to client {client_id} timed out")
                    break

    except WebSocketDisconnect:
        # Client disconnected
        await manager.disconnect(websocket, client_id)
    except Exception as e:
        logger.error(f"WebSocket error: {str(e)}")
        try:
            await websocket.close(code=1011, reason="Server error")
        except:
            pass
        await manager.disconnect(websocket, client_id)


@router.post("/command/{race_id}")
async def send_command_notification(
    race_id: str,
    command: NotificationCommand,
    credentials: HTTPAuthorizationCredentials = Security(security),
    db: Session = Depends(get_db)
):
    """Send a command notification to all clients connected to a specific race"""
    try:
        # Verify token
        token = credentials.credentials
        try:
            token_data = jwt.decode(
                token,
                settings.SECRET_KEY,
                algorithms=["HS256"],
                audience="api.hikeandfly.app",
                issuer="hikeandfly.app",
                verify=True
            )

            # # Check for admin privileges
            # if not token_data.get("admin", False):
            #     raise HTTPException(
            #         status_code=403,
            #         detail="Insufficient privileges for sending commands"
            #     )

        except jwt.ExpiredSignatureError:
            raise HTTPException(
                status_code=401,
                detail="Token has expired"
            )
        except PyJWTError as e:
            raise HTTPException(
                status_code=401,
                detail=f"Invalid token: {str(e)}"
            )

        # Process the command - use dot notation for Pydantic models, not .get()
        command_data = {
            "priority": command.priority,  # Access directly with dot notation
            "message": command.message,    # Access directly with dot notation
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        # Send the command to all connected clients for this race
        await manager.send_command_notification(race_id, command_data)

        # Return success response
        return {
            "success": True,
            "recipients": manager.get_active_viewers(race_id),
            "command": command.type,       # Access directly with dot notation
            "timestamp": command_data["timestamp"]
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error sending command: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to send command: {str(e)}"
        )


@router.post("/notifications/subscribe")
async def subscribe_to_notifications(
    request: SubscriptionRequest,
    db: Session = Depends(get_db)
):
    """Subscribe a device to push notifications for a specific race"""
    try:
        # Check if token already exists for this race
        existing_token = db.query(NotificationTokenDB).filter(
            NotificationTokenDB.token == request.token,
            NotificationTokenDB.race_id == request.raceId
        ).first()

        if existing_token:
            # Update existing token with latest info
            existing_token.device_id = request.deviceId
            existing_token.platform = request.platform
            existing_token.created_at = datetime.now(timezone.utc)
            db.commit()
            return {"success": True, "message": "Updated existing subscription"}

        # Create new token record
        new_token = NotificationTokenDB(
            token=request.token,
            race_id=request.raceId,
            device_id=request.deviceId,
            platform=request.platform,
            created_at=datetime.now(timezone.utc)
        )
        db.add(new_token)
        db.commit()

        return {"success": True, "message": "Successfully subscribed to race notifications"}

    except SQLAlchemyError as e:
        db.rollback()
        logger.error(
            f"Database error while subscribing to notifications: {str(e)}")
        raise HTTPException(
            status_code=500, detail="Failed to subscribe to notifications")
    except Exception as e:
        logger.error(f"Error subscribing to notifications: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to subscribe: {str(e)}")


@router.post("/notifications/unsubscribe")
async def unsubscribe_from_notifications(
    request: UnsubscriptionRequest,
    db: Session = Depends(get_db)
):
    """Unsubscribe a device from push notifications for a specific race"""
    try:
        # Delete token from database
        result = db.query(NotificationTokenDB).filter(
            NotificationTokenDB.token == request.token,
            NotificationTokenDB.race_id == request.raceId
        ).delete()

        db.commit()

        return {
            "success": True,
            "message": "Unsubscribed from race notifications",
            "removed": result
        }

    except SQLAlchemyError as e:
        db.rollback()
        logger.error(
            f"Database error while unsubscribing from notifications: {str(e)}")
        raise HTTPException(
            status_code=500, detail="Failed to unsubscribe from notifications")
    except Exception as e:
        logger.error(f"Error unsubscribing from notifications: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to unsubscribe: {str(e)}")


@router.post("/notifications/send")
async def send_notification(
    request: NotificationRequest,
    credentials: HTTPAuthorizationCredentials = Security(security),
    db: Session = Depends(get_db)
):
    """Send a notification to all subscribers of a specific race"""
    try:
        # Verify token
        token = credentials.credentials
        try:
            token_data = jwt.decode(
                token,
                settings.SECRET_KEY,
                algorithms=["HS256"],
                audience="api.hikeandfly.app",
                issuer="hikeandfly.app",
                verify=True
            )
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Token has expired")
        except PyJWTError as e:
            raise HTTPException(
                status_code=401, detail=f"Invalid token: {str(e)}")

        # Find all tokens for this race
        subscription_tokens = db.query(NotificationTokenDB).filter(
            NotificationTokenDB.race_id == request.raceId
        ).all()

        if not subscription_tokens:
            return {
                "success": False,
                "message": "No subscribers found for this race",
                "sent": 0
            }

        # Send notifications
        tickets = []
        errors = []
        tokens_to_remove = []

        for token_record in subscription_tokens:
            try:
                ticket = await send_push_message(
                    token=token_record.token,
                    title=request.title,
                    message=request.body,
                    extra_data=request.data
                )
                tickets.append(ticket)
            except ValueError as e:
                if "Device not registered" in str(e):
                    # Mark token for removal
                    tokens_to_remove.append(token_record.id)
                errors.append(
                    {"token": token_record.token[:10] + "...", "error": str(e)})

        # Clean up invalid tokens
        if tokens_to_remove:
            for token_id in tokens_to_remove:
                db.query(NotificationTokenDB).filter(
                    NotificationTokenDB.id == token_id
                ).delete()
            db.commit()

        return {
            "success": len(errors) == 0,
            "sent": len(tickets),
            "errors": len(errors),
            "error_details": errors if errors else None
        }

    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Database error while sending notifications: {str(e)}")
        raise HTTPException(
            status_code=500, detail="Database error while sending notifications")
    except Exception as e:
        logger.error(f"Error sending notifications: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to send notifications: {str(e)}")

# Updated Expo Push Notification Helper Function


async def send_push_message(token: str, title: str, message: str, extra_data: dict = None):
    """Send a push notification using Expo's push notification service"""
    try:
        response = await PushClient().publish(
            PushMessage(
                to=token,
                title=title,
                body=message,
                data=extra_data or {},
            )
        )
        return response
    except DeviceNotRegisteredError:
        raise ValueError("Device not registered")
    except PushServerError as e:
        raise ValueError(f"Push server error: {e}")
    except Exception as e:
        raise ValueError(f"Error sending push notification: {e}")
