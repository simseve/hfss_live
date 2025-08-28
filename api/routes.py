from api.flight_state import determine_if_landed, detect_flight_state
from fastapi import APIRouter, Depends, HTTPException, Query, Security, WebSocket, WebSocketDisconnect, Response, UploadFile, File, Form, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session
from database.schemas import LiveTrackingRequest, LiveTrackPointCreate, FlightResponse, TrackUploadRequest, NotificationCommand, SubscriptionRequest, UnsubscriptionRequest, NotificationRequest, SentNotificationResponse
from database.models import UploadedTrackPoint, Flight, LiveTrackPoint, Race, NotificationTokenDB, SentNotification, DeviceRegistration
from typing import Dict, Optional, List
from database.db_replica import get_db, get_replica_db
import logging
from api.auth import verify_tracking_token
from sqlalchemy.exc import SQLAlchemyError
from uuid import uuid4
from sqlalchemy.dialects.postgresql import insert
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import text

from datetime import datetime, timezone, timedelta, time
import jwt
import hashlib
from config import settings
from math import radians, sin, cos, sqrt, atan2
from uuid import UUID
from sqlalchemy import func
import aiohttp
from aiohttp import ClientSession
from jwt.exceptions import PyJWTError
import asyncio
import json
import requests
from ws_conn import manager
# Import Expo Push Notification modules
from exponent_server_sdk import (
    DeviceNotRegisteredError,
    PushClient,
    PushMessage,
    PushServerError,
)
from zoneinfo import ZoneInfo
# Import XContest service
from services.xcontest_service import xcontest_service

from .send_notifications import (
    send_push_message_unified,
    send_push_messages_batch_unified,
    detect_token_type,
    TokenType
)

# Import queue system
from redis_queue_system.redis_queue import redis_queue, QUEUE_NAMES
from redis_queue_system.point_processor import point_processor


logger = logging.getLogger(__name__)

router = APIRouter()

security = HTTPBearer()

# Expo push notification configuration
EXPO_BATCH_SIZE = 100  # Maximum batch size per Expo documentation
EXPO_RATE_LIMIT_DELAY = 0.1  # Small delay between batches to avoid rate limiting


@router.post("/live", status_code=202)
async def live_tracking(
    data: LiveTrackingRequest,
    token: str = Query(..., description="Authentication token"),
    token_data: Dict = Depends(verify_tracking_token),
    db: Session = Depends(get_db)  # Use primary for writes
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

        device_id = data.device_id if hasattr(
            data, 'device_id') else 'anonymous'

        if not flight:

            # Create flight without first_fix/last_fix/total_points
            # These will be automatically updated by database triggers
            flight = Flight(
                flight_id=data.flight_id,
                race_uuid=race.id,
                race_id=race_id,
                pilot_id=pilot_id,
                pilot_name=pilot_name,
                created_at=datetime.now(timezone.utc),
                source='live',
                device_id=device_id
            )
            db.add(flight)

        elif flight.pilot_id != pilot_id:
            raise HTTPException(
                status_code=403,
                detail="Not authorized to update this flight"
            )
        else:
            # Only update pilot name if it changed
            # Triggers will handle first_fix, last_fix, and total_points
            if flight.pilot_name != pilot_name:
                flight.pilot_name = pilot_name

        try:
            db.commit()
            # Refresh the flight object to get the actual UUID from database
            db.refresh(flight)
            # Flight must be committed before we can reference it in track points
            logger.info(
                f"Successfully created/updated flight record: {data.flight_id} with UUID: {flight.id}")
        except SQLAlchemyError as e:
            db.rollback()
            logger.error(f"Failed to update flight: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail="Failed to update flight record"
            )

        # Prepare track points data for queueing (as dictionaries, not SQLAlchemy models)
        track_points_data = []
        for point in data.track_points:
            point_data = {
                "flight_id": data.flight_id,
                "flight_uuid": flight.id,
                "datetime": datetime.fromisoformat(
                    point['datetime'].replace('Z', '+00:00'))
                .astimezone(timezone.utc)
                .strftime('%Y-%m-%dT%H:%M:%SZ'),
                "lat": point['lat'],
                "lon": point['lon'],
                "elevation": point.get('elevation'),
                "barometric_altitude": point.get('barometric_altitude')
            }
            track_points_data.append(point_data)

        logger.info(data)
        logger.info(track_points_data)
        logger.info(
            f"Saving {len(track_points_data)} track points for flight {data.flight_id}")

        try:
            # Queue points for background processing instead of immediate DB insert
            queued = await redis_queue.queue_points(
                QUEUE_NAMES['live'],
                track_points_data,
                priority=1  # High priority for live tracking
            )

            if queued:
                # Flight is already committed, update state asynchronously
                asyncio.create_task(update_flight_state(flight.id, db, source='live'))
                logger.info(
                    f"Successfully queued {len(track_points_data)} track points for flight {data.flight_id}")

                return {
                    'success': True,
                    'message': f'Live tracking data queued for processing ({len(track_points_data)} points)',
                    'flight_id': data.flight_id,
                    'pilot_name': pilot_name,
                    'total_points': flight.total_points,
                    'queued': True
                }
            else:
                # Fallback to direct insertion if queueing fails
                stmt = insert(LiveTrackPoint).on_conflict_do_nothing(
                    index_elements=['flight_id', 'lat', 'lon', 'datetime']
                )
                db.execute(stmt, track_points_data)
                db.commit()
                asyncio.create_task(update_flight_state(flight.id, db, source='live'))
                logger.info(
                    f"Successfully saved track points for flight {data.flight_id} (fallback)")

                return {
                    'success': True,
                    'message': f'Live tracking data processed ({len(track_points_data)} points)',
                    'flight_id': data.flight_id,
                    'pilot_name': pilot_name,
                    'total_points': flight.total_points,
                    'queued': False
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
    db: Session = Depends(get_db),  # Use primary for writes
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
                Flight.source.contains('upload')
            ).first()

            if flight:
                raise HTTPException(
                    status_code=409,
                    detail="Flight ID with source upload already exists. Each flight must have a unique ID."
                )

            device_id = upload_data.device_id if hasattr(
                upload_data, 'device_id') else 'anonymous'

            # No need to process first/last points - triggers will handle this

            # Create new flight without first_fix/last_fix/total_points
            # These will be automatically updated by database triggers
            flight = Flight(
                flight_id=upload_data.flight_id,
                race_uuid=race.id,
                race_id=race_id,
                pilot_id=pilot_id,
                pilot_name=pilot_name,
                created_at=datetime.now(timezone.utc),
                source='upload',
                device_id=device_id
            )
            db.add(flight)

            try:
                db.commit()
                # Refresh the flight object to get the actual UUID from database
                db.refresh(flight)
            except SQLAlchemyError as e:
                db.rollback()
                logger.error(f"Failed to create flight record: {str(e)}")
                raise HTTPException(
                    status_code=500, detail="Failed to create flight record")

            # Prepare track points data for queueing (as dictionaries, not SQLAlchemy models)
            points_data = []
            for point in upload_data.track_points:
                point_data = {
                    "flight_id": upload_data.flight_id,
                    "flight_uuid": flight.id,
                    "datetime": datetime.fromisoformat(point['datetime'].replace(
                        'Z', '+00:00')).astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                    "lat": point['lat'],
                    "lon": point['lon'],
                    "elevation": point.get('elevation'),
                    "barometric_altitude": point.get('barometric_altitude')
                }
                points_data.append(point_data)

            try:
                # For large uploads, split into chunks for better processing
                # Increased chunk size since the system can handle it
                max_points_per_chunk = 1000
                if len(points_data) > max_points_per_chunk:
                    logger.info(f"Large upload detected ({len(points_data)} points), splitting into chunks")
                    chunks = [points_data[i:i+max_points_per_chunk] 
                             for i in range(0, len(points_data), max_points_per_chunk)]
                    
                    all_queued = True
                    for i, chunk in enumerate(chunks):
                        chunk_queued = await redis_queue.queue_points(
                            QUEUE_NAMES['upload'],
                            chunk,
                            priority=2  # Medium priority for uploads
                        )
                        if not chunk_queued:
                            logger.error(f"Failed to queue chunk {i+1}/{len(chunks)}")
                            all_queued = False
                            break
                        else:
                            logger.info(f"Queued chunk {i+1}/{len(chunks)} with {len(chunk)} points")
                    
                    queued = all_queued
                else:
                    # Small upload, queue as single batch
                    queued = await redis_queue.queue_points(
                        QUEUE_NAMES['upload'],
                        points_data,
                        priority=2  # Medium priority for uploads
                    )

                if queued:
                    # Commit flight record immediately
                    db.commit()
                    # Asynchronously update the flight state with 'upload' source
                    asyncio.create_task(update_flight_state(
                        flight.id, db, source='upload'))
                    logger.info(
                        f"Successfully queued upload for flight {upload_data.flight_id}")

                    # Add queue info to response
                    flight_dict = flight.__dict__.copy()
                    flight_dict['queued'] = True
                    flight_dict['queue_size'] = await redis_queue.get_queue_size(QUEUE_NAMES['upload'])
                    return flight
                else:
                    # Fallback to direct insertion if queueing fails
                    stmt = insert(UploadedTrackPoint).on_conflict_do_nothing(
                        index_elements=['flight_id', 'lat', 'lon', 'datetime']
                    )
                    db.execute(stmt, points_data)
                    db.commit()

                    # Asynchronously update the flight state with 'upload' source
                    asyncio.create_task(update_flight_state(
                        flight.id, db, source='upload'))
                    logger.info(
                        f"Successfully processed upload for flight {upload_data.flight_id} (fallback)")
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
    db: Session = Depends(get_replica_db)  # Use read replica
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
            query = query.filter(Flight.source.contains(source))

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
                'start_time': flight.first_fix.get('datetime') if flight.first_fix and 'datetime' in flight.first_fix else None,
                'end_time': flight.last_fix.get('datetime') if flight.last_fix and 'datetime' in flight.last_fix else None,
                'total_points': flight.total_points,
                'first_fix': flight.first_fix,
                'last_fix': flight.last_fix,
                'flight_state': flight.flight_state
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
            Flight.source.contains('upload')  # Get all tracks containing 'upload'
        ).order_by(Flight.created_at.desc()).all()

        # Format track information
        tracks = []
        for flight in flights:
            # Skip flights without fixes
            if not flight.first_fix or not flight.last_fix:
                continue
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
    db: Session = Depends(get_db)  # Use primary for deletes
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
    source: str = Query(..., regex="^.*(?:live|upload).*$",
                        description="Track source (must contain 'live' or 'upload')"),
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
    db: Session = Depends(get_replica_db)  # Use read replica
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
            Flight.source.contains('live')
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
        elif flight.first_fix:
            filter_time = datetime.fromisoformat(
                flight.first_fix['datetime'].replace('Z', '+00:00')).astimezone(timezone.utc)
        else:
            # No fix data available, use current time
            filter_time = datetime.now(timezone.utc)

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
                "flightFirstFix": flight.first_fix['datetime'] if flight.first_fix else None,
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
    db: Session = Depends(get_replica_db)  # Use read replica
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

        # Get flight from database
        flight = db.query(Flight).filter(
            Flight.id == flight_uuid,
            Flight.source.contains('live')
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
                "flightFirstFix": flight.first_fix['datetime'] if flight.first_fix else None,
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


def get_flight_state(flight_uuid, db, recent_points_limit=20):
    """Get the current flight state for a specific flight"""
    # Get the most recent track points for this flight
    recent_points = db.query(LiveTrackPoint).filter(
        LiveTrackPoint.flight_uuid == flight_uuid
    ).order_by(LiveTrackPoint.datetime.desc()).limit(recent_points_limit).all()

    if not recent_points:
        return 'unknown', {'confidence': 'low', 'reason': 'no_track_points'}

    # Format points for the detection function
    formatted_points = [{
        'lat': float(point.lat),
        'lon': float(point.lon),
        'elevation': float(point.elevation) if point.elevation is not None else None,
        'datetime': point.datetime
    } for point in recent_points]

    # Sort points by datetime (oldest first)
    formatted_points.sort(key=lambda p: p['datetime'])

    # Detect the flight state
    state, state_info = detect_flight_state(formatted_points)

    return state, state_info


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
    source: Optional[str] = Query(None, regex="^.*(?:live|upload).*$"),
    credentials: HTTPAuthorizationCredentials = Security(security),
    db: Session = Depends(get_replica_db)  # Use read replica
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
            if flight.source == 'live' and flight.last_fix:
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
            
            # Skip flights without any fixes yet
            if not flight.first_fix or not flight.last_fix:
                continue

            # Create flight_info dictionary
            # Get flight state
            state, state_info = get_flight_state(flight.id, db)

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
                "landed": state in ['landing', 'stationary', 'walking'],
                "flightState": {
                    "state": state,
                    "confidence": state_info.get('confidence', 'low'),
                    "avgSpeed": state_info.get('avg_speed', 0),
                    "maxSpeed": state_info.get('max_speed', 0),
                    "altitudeChange": state_info.get('altitude_change', 0)
                },
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
    source: str = Query(..., regex="^.*(?:live|upload).*$",
                        description="Track source (must contain 'live' or 'upload')"),
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
    db: Session = Depends(get_replica_db)  # Use read replica for WebSocket reads
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

        # Current server time in UTC
        current_time = datetime.now(timezone.utc)

        # Get race information including timezone
        race = db.query(Race).filter(Race.race_id == race_id).first()
        if not race or not race.timezone:
            race_timezone = timezone.utc  # Default to UTC if race timezone not found
        else:
            # Get the timezone object from the race
            # Requires Python 3.9+ with zoneinfo
            race_timezone = ZoneInfo(race.timezone)

        # Convert current time to race's local timezone
        race_local_time = current_time.astimezone(race_timezone)

        # Calculate the start and end of the current day in race's timezone
        race_day_start = datetime.combine(
            race_local_time.date(), time.min, tzinfo=race_timezone)
        race_day_end = datetime.combine(
            race_local_time.date(), time.max, tzinfo=race_timezone)

        # Convert back to UTC for database query
        utc_day_start = race_day_start.astimezone(timezone.utc)
        utc_day_end = race_day_end.astimezone(timezone.utc)

        # Get flights active today (with a small buffer before race day)
        # Allow pilots who started slightly before race day
        lookback_buffer = timedelta(hours=4)
        flights = (
            db.query(Flight)
            .filter(
                Flight.race_id == race_id,
                # Either the flight was created today
                ((Flight.created_at >= utc_day_start - lookback_buffer) &
                 (Flight.created_at <= utc_day_end)) |
                # OR the flight has a last_fix during today (for flights spanning overnight)
                (func.json_extract_path_text(Flight.last_fix, 'datetime') >=
                    utc_day_start.strftime('%Y-%m-%dT%H:%M:%SZ')) &
                (func.json_extract_path_text(Flight.last_fix, 'datetime') <=
                    utc_day_end.strftime('%Y-%m-%dT%H:%M:%SZ')),
                Flight.source.contains('live')
            )
            .order_by(Flight.created_at.desc())
            .all()
        )

        # Further filter to only pilots who have been active in the last hour
        # active_threshold = current_time - timedelta(minutes=60)
        # active_flights = []

        # for flight in flights:
        #     last_fix_time = datetime.fromisoformat(
        #         flight.last_fix['datetime'].replace('Z', '+00:00')
        #     ).astimezone(timezone.utc)

        #     if last_fix_time >= active_threshold:
        #         active_flights.append(flight)

        # Process flights as before, but only using active_flights
        pilot_latest_flights = {}

        for flight in flights:
            pilot_id = str(flight.pilot_id)
            
            # Skip flights without fixes
            if not flight.first_fix or not flight.last_fix:
                continue

            # If we haven't seen this pilot yet, this is their most recent flight
            if pilot_id not in pilot_latest_flights:
                # Get track points for this flight ONLY (using flight_uuid to ensure we only get points from this flight)
                track_points = db.query(LiveTrackPoint).filter(
                    LiveTrackPoint.flight_uuid == flight.id
                ).order_by(LiveTrackPoint.datetime).all()

                # Downsample track points if there are too many
                # Keep at most 1 point per 5 seconds to reduce data volume
                downsampled_points = []
                last_added_time = None

                for i, point in enumerate(track_points):
                    current_time = point.datetime
                    is_last_point = (i == len(track_points) - 1)
                    
                    # Include point if it's the first, meets time threshold, or is the last point
                    if last_added_time is None or (current_time - last_added_time).total_seconds() >= 3 or is_last_point:
                        downsampled_points.append({
                            "lat": float(point.lat),
                            "lon": float(point.lon),
                            "elevation": float(point.elevation) if point.elevation is not None else 0,
                            "datetime": point.datetime.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                        })
                        last_added_time = current_time

                # Store the actual last datetime from the downsampled points
                # This helps prevent overlap when incremental updates arrive
                last_sent_datetime = None
                if downsampled_points:
                    last_sent_datetime = downsampled_points[-1]['datetime']
                
                pilot_latest_flights[pilot_id] = {
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
                    "trackHistory": downsampled_points,
                    "totalPoints": len(track_points),
                    "downsampledPoints": len(downsampled_points),
                    "source": "HFSS",  # Mark as HFSS data
                    "lastFixTime": flight.last_fix['datetime'],
                    "lastSentPointTime": last_sent_datetime,  # Track the actual last point sent
                    "isActive": True,  # Mark as currently active
                    # Include flight state information
                    "flight_state": flight.flight_state.get('state', 'unknown') if flight.flight_state else 'unknown',
                    "flight_state_info": flight.flight_state if flight.flight_state else {}
                }

        # Now convert the dictionary values to a list for the response
        consolidated_flight_data = list(pilot_latest_flights.values())

        # Fetch XContest data if available
        try:
            # Get race configuration and pilots from HFSS API
            race_config = await xcontest_service.get_race_config_and_pilots(race_id, token)
            
            if race_config.get('success') and race_config.get('xc_entity') and race_config.get('xc_api_key'):
                # Store the working token for background updates
                manager.store_hfss_token(race_id, token)
                # Get XContest flights
                xc_flights = await xcontest_service.get_xcontest_flights_for_race(
                    race_config['xc_entity'],
                    race_config['xc_api_key'],
                    race_config['xcontest_map'],
                    race_timezone
                )
                
                # Merge XContest flights with HFSS flights
                # Keep track of pilots already in HFSS data
                hfss_pilot_ids = {flight['pilot_id'] for flight in consolidated_flight_data}
                
                # Add XContest flights for pilots not already tracked via HFSS
                for xc_flight in xc_flights:
                    if xc_flight['pilot_id'] not in hfss_pilot_ids:
                        consolidated_flight_data.append(xc_flight)
                        # Track this XContest flight for incremental updates
                        manager.update_xc_flight_tracking(
                            race_id, 
                            xc_flight['uuid'], 
                            xc_flight['lastFixTime'],
                            pilot_id=xc_flight.get('pilot_id'),
                            pilot_name=xc_flight.get('pilot_name')
                        )
                    else:
                        # Optionally, you could merge or compare data here
                        # For now, HFSS data takes precedence
                        logger.info(f"Pilot {xc_flight['pilot_id']} has both HFSS and XContest data, using HFSS")
                
                logger.info(f"Added {len(xc_flights)} XContest flights to tracking data")
        except Exception as e:
            logger.error(f"Error fetching XContest data: {str(e)}")
            # Continue without XContest data if there's an error

        # Send just the most recent flight per pilot
        await websocket.send_json({
            "type": "initial_data",
            "race_id": race_id,
            "flights": consolidated_flight_data,
            "active_viewers": manager.get_active_viewers(race_id)
        })
        
        # Track the last sent point time for each flight to prevent overlap with incremental updates
        for flight_data in consolidated_flight_data:
            if flight_data.get('source') == 'HFSS' and flight_data.get('lastSentPointTime'):
                # Convert the ISO string back to datetime
                last_sent_time = datetime.fromisoformat(
                    flight_data['lastSentPointTime'].replace('Z', '+00:00')
                )
                manager.add_pilot_with_sent_data(race_id, flight_data['uuid'], last_sent_time)

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
            status_code=500, detail=f"Failed to unsubscribe: {str(e)}"
        )


@router.get("/mvt/{z}/{x}/{y}")
async def get_track_tile(
    z: int,
    x: int,
    y: int,
    flight_id: str,
    source: str = Query(..., regex="^(live|upload)$"),
    gzip: bool = Query(
        False, description="Apply gzip compression to the tile data"),
    token_data: Dict = Depends(verify_tracking_token),
    db: Session = Depends(get_replica_db)  # Use read replica for MVT tiles
):
    """
    Serve vector tiles for track points in Mapbox Vector Tile (MVT) format.
    Used by MapLibre GL to render flight tracks with improved performance.

    Parameters:
    - z/x/y: Tile coordinates
    - flight_uuid: UUID of the flight to render
    - source: Either 'live' or 'upload' to specify data source
    - gzip: Set to true to compress the tile with gzip (default: false)
    """
    try:
        # Choose appropriate model based on source parameter
        PointModel = LiveTrackPoint if source == 'live' else UploadedTrackPoint

        # Calculate tile bounds
        import mercantile
        tile_bounds = mercantile.bounds(x, y, z)

        # Query points that fall within this tile's bounds
        query = db.query(PointModel).filter(
            PointModel.flight_id == flight_id,
            PointModel.lon >= tile_bounds.west,
            PointModel.lon <= tile_bounds.east,
            PointModel.lat >= tile_bounds.south,
            PointModel.lat <= tile_bounds.north
        ).order_by(PointModel.datetime)

        # Apply different sampling based on zoom level
        if z < 10:
            # Low zoom: Sample more aggressively (e.g., every 30 seconds)
            points = []
            last_ts = None
            for point in query.all():
                if last_ts is None or (point.datetime - last_ts).total_seconds() >= 30:
                    points.append(point)
                    last_ts = point.datetime
        else:
            # High zoom: Use more points
            points = query.all()

        # Generate MVT tile data
        import mapbox_vector_tile
        from mercantile import xy_bounds

        # Get the tile bounds in Web Mercator coordinates
        xy_bounds = mercantile.xy_bounds(x, y, z)
        tile_width = xy_bounds.right - xy_bounds.left
        tile_height = xy_bounds.top - xy_bounds.bottom

        features = []
        for point in points:
            # Convert WGS84 coordinates to Web Mercator coordinates
            mx, my = mercantile.xy(float(point.lon), float(point.lat))

            # Scale to tile coordinates (0-4096 range)
            px = 4096 * (mx - xy_bounds.left) / tile_width
            py = 4096 * (1 - (my - xy_bounds.bottom) /
                         tile_height)  # Y is flipped in MVT

            features.append({
                "geometry": {
                    "type": "Point",
                    "coordinates": [px, py]  # Use projected coordinates
                },
                "properties": {
                    "elevation": float(point.elevation) if point.elevation else 0,
                    "datetime": point.datetime.isoformat()
                }
            })

        # Generate MVT with the correct structure
        tile = mapbox_vector_tile.encode([
            {
                "name": "track_points",  # Layer name
                "features": features     # Features list
            }
        ])

        # Apply gzip compression if requested
        if gzip:
            import gzip as gz
            compressed_tile = gz.compress(tile)
            return Response(
                content=compressed_tile,
                media_type="application/x-protobuf",
                headers={"Content-Encoding": "gzip"}
            )
        else:
            # Return uncompressed tile
            return Response(content=tile, media_type="application/x-protobuf")

    except Exception as e:
        logger.error(f"Error generating vector tile: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to generate tile: {str(e)}")


@router.get("/postgis-mvt/{z}/{x}/{y}")
async def get_postgis_track_tile(
    z: int,
    x: int,
    y: int,
    flight_id: str = Query(..., description="UUID of the flight to render"),
    source: str = Query(..., regex="^.*(?:live|upload).*$",
                        description="Source containing 'live' or 'upload'"),
    token_data: Dict = Depends(verify_tracking_token),
    db: Session = Depends(get_db)
):
    """
    Serve vector tiles for track points using PostGIS ST_AsMVT function.
    This provides better performance as tile generation happens in the database.
    Returns both point features and a linestring connecting them.

    Parameters:
    - z/x/y: Tile coordinates
    - flight_uuid: UUID of the flight to render
    - source: Either 'live' or 'upload' to specify data source
    """
    try:
        # Determine table name based on source
        table_name = "live_track_points" if source == "live" else "uploaded_track_points"

        # SQL query using ST_AsMVT
        # This generates MVT tiles with both points and lines
        query = f"""
        WITH 
        bounds AS (
            SELECT ST_TileEnvelope({z}, {x}, {y}) AS geom
        ),
        -- Select and filter points within this tile
        filtered_points AS (
            SELECT 
                t.id,
                t.geom,
                t.elevation,
                t.datetime,
                t.lat,
                t.lon
            FROM {table_name} t
            WHERE t.flight_id = '{flight_id}'
              AND ST_Transform(t.geom, 3857) && (SELECT geom FROM bounds)
              -- Add time-based sampling for lower zoom levels
              {" AND extract(second from t.datetime)::integer % 30 = 0 " if z < 10 else ""}
            ORDER BY t.datetime
        ),
        -- Create the points layer
        point_mvt AS (
            SELECT 
                ST_AsMVTGeom(
                    ST_Transform(fp.geom, 3857), 
                    (SELECT geom FROM bounds),
                    4096,    -- Resolution: standard is 4096 for MVT
                    256,     -- Buffer: to avoid clipping at tile edges
                    true     -- Clip geometries
                ) AS geom,
                fp.elevation::float as elevation,
                fp.datetime::text as datetime,
                fp.lat::float as lat,
                fp.lon::float as lon,
                fp.id::text as point_id
            FROM filtered_points fp
        ),
        -- Create the line layer from the same points
        line_data AS (
            SELECT ST_AsMVTGeom(
                ST_Transform(
                    ST_MakeLine(fp.geom ORDER BY fp.datetime),
                    3857
                ),
                (SELECT geom FROM bounds),
                4096,
                256,
                true
            ) AS geom,
            '{flight_id}' as flight_id,
            count(fp.id) as point_count
            FROM filtered_points fp
            GROUP BY flight_id
        ),
        -- Generate the MVT for points
        points_mvt AS (
            SELECT ST_AsMVT(point_mvt.*, 'track_points') AS mvt
            FROM point_mvt
        ),
        -- Generate the MVT for lines
        lines_mvt AS (
            SELECT ST_AsMVT(line_data.*, 'track_lines') AS mvt
            FROM line_data
        )
        -- Combine both MVTs into one response
        SELECT 
            CASE 
                WHEN EXISTS (SELECT 1 FROM line_data) AND EXISTS (SELECT 1 FROM point_mvt)
                THEN ST_AsMVT(line_data.*, 'track_lines') || ST_AsMVT(point_mvt.*, 'track_points')
                WHEN EXISTS (SELECT 1 FROM line_data) 
                THEN ST_AsMVT(line_data.*, 'track_lines') 
                WHEN EXISTS (SELECT 1 FROM point_mvt)
                THEN ST_AsMVT(point_mvt.*, 'track_points')
                ELSE NULL
            END AS mvt
        FROM line_data, point_mvt
        """

        # Execute the query and get the tile
        result = db.execute(text(query)).fetchone()

        if result and result[0]:
            # Return the MVT tile as binary data
            return Response(content=result[0], media_type="application/x-protobuf")
        else:
            # Return an empty tile
            return Response(content=b"", media_type="application/x-protobuf")

    except Exception as e:
        logger.error(f"Error generating PostGIS vector tile: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to generate tile: {str(e)}")


@router.get("/postgis-mvt/daily/{z}/{x}/{y}")
async def get_daily_tracks_tile(
    z: int,
    x: int,
    y: int,
    race_id: str = Query(..., description="Race ID to filter tracks"),
    source: str = Query("live", regex="^.*(?:live|upload).*$",
                        description="Source containing 'live' or 'upload'"),
    date: Optional[str] = Query(
        None, description="Date in YYYY-MM-DD format. If not provided, uses today"),
    pilot_id: Optional[str] = Query(
        None, description="Optional pilot ID to filter tracks"),
    token_data: Dict = Depends(verify_tracking_token),
    db: Session = Depends(get_replica_db)  # Use read replica for heavy PostGIS queries
):
    """
    Serve vector tiles for all tracks from today for a specific race.
    Returns track points and lines with different colors per pilot.

    Parameters:
    - z/x/y: Tile coordinates
    - race_id: Race ID to filter tracks
    - source: Either 'live' or 'upload' to specify data source
    - date: Optional date parameter (YYYY-MM-DD). If not provided, uses today
    """
    try:
        # Determine table name based on source
        table_name = "live_track_points" if source == "live" else "uploaded_track_points"

        # Get current date in the server's timezone or use provided date
        if date:
            # Parse provided date
            try:
                target_date = datetime.strptime(date, '%Y-%m-%d').date()
            except ValueError:
                raise HTTPException(
                    status_code=400, detail=f"Invalid date format. Use YYYY-MM-DD"
                )
        else:
            # Use today's date
            target_date = datetime.now(timezone.utc).date()

        # Calculate start and end of the specified date in UTC
        start_of_day = datetime.combine(
            target_date, time.min, tzinfo=timezone.utc)
        end_of_day = datetime.combine(
            target_date, time.max, tzinfo=timezone.utc)

        # First, find all flights from today for this race
        all_flights_today = db.query(Flight).filter(
            Flight.race_id == race_id,
            Flight.source == source,
            # Filter by pilot_id if it's provided
            *([] if pilot_id is None else [Flight.pilot_id == pilot_id]),
            # Either the flight was created today
            ((Flight.created_at >= start_of_day) &
             (Flight.created_at <= end_of_day)) |
            # OR the flight has a last_fix during today
            (func.json_extract_path_text(Flight.last_fix, 'datetime') >=
                start_of_day.strftime('%Y-%m-%dT%H:%M:%SZ')) &
            (func.json_extract_path_text(Flight.last_fix, 'datetime') <=
                end_of_day.strftime('%Y-%m-%dT%H:%M:%SZ'))
        ).all()

        # Group flights by pilot_id and select only the newest one for each pilot
        pilot_newest_flights = {}
        for flight in all_flights_today:
            pilot_id = flight.pilot_id
            last_fix_time = datetime.fromisoformat(
                flight.last_fix['datetime'].replace('Z', '+00:00')
            ).astimezone(timezone.utc)

            if pilot_id not in pilot_newest_flights or last_fix_time > pilot_newest_flights[pilot_id]['last_fix_time']:
                pilot_newest_flights[pilot_id] = {
                    'flight': flight,
                    'last_fix_time': last_fix_time
                }

        # Extract the flight UUIDs from the selected flights
        flight_uuids = [str(flight_data['flight'].id)
                        for flight_data in pilot_newest_flights.values()]

        if not flight_uuids:
            # No flights found, return empty tile
            return Response(content=b"", media_type="application/x-protobuf")

        # Format UUIDs as a string list for the SQL query
        flight_uuids_str = "', '".join(flight_uuids)
        if flight_uuids_str:
            flight_uuids_str = f"('{flight_uuids_str}')"
        else:
            # Use NULL to ensure valid SQL when list is empty
            flight_uuids_str = "(NULL)"

        # Calculate tile bounds with margin for better rendering at boundaries
        # Use 64 pixel buffer at 4096 resolution which is standard for MVT
        buffer_size = 256
        # Convert to ratio for ST_TileEnvelope margin parameter
        margin_size = buffer_size / 4096.0

        # Define simplification tolerances based on zoom level
        # These values represent meters at different zoom levels
        # simplify_tolerance = 0
        # min_distance = 0

        # if z <= 3:
        #     simplify_tolerance = 1000  # ~1km at global zoom
        #     min_distance = 200         # 200m min distance between points
        # elif z <= 5:
        #     simplify_tolerance = 500   # ~500m at continent zoom
        #     min_distance = 100         # 100m min distance
        # elif z <= 8:
        #     simplify_tolerance = 200   # ~200m at regional zoom
        #     min_distance = 50          # 50m min distance
        # elif z <= 10:
        #     simplify_tolerance = 50    # ~50m at local zoom
        #     min_distance = 20          # 20m min distance
        # elif z <= 13:
        #     simplify_tolerance = 20    # ~20m at city zoom
        #     min_distance = 10          # 10m min distance
        # elif z <= 15:
        #     simplify_tolerance = 10    # ~10m at neighborhood zoom
        #     min_distance = 5           # 5m min distance
        # elif z <= 17:
        #     simplify_tolerance = 5     # ~5m at street level
        #     min_distance = 2           # 2m min distance

        # # We'll use ST_Simplify for lower zoom levels (faster) and ST_SimplifyPreserveTopology
        # # for higher zoom levels (safer for detailed views)
        # use_preserve_topology = z >= 8
        # simplify_func = "ST_SimplifyPreserveTopology" if use_preserve_topology else "ST_Simplify"

        simplify_tolerance = 0
        min_distance = 0

        # if z <= 3:
        #     simplify_tolerance = 100  # Drastically reduced from 1000
        #     min_distance = 30        # Drastically reduced from 200
        # elif z <= 5:
        #     simplify_tolerance = 50   # Drastically reduced from 500
        #     min_distance = 15        # Drastically reduced from 100
        # elif z <= 8:
        #     simplify_tolerance = 25   # Drastically reduced from 200
        #     min_distance = 8         # Drastically reduced from 50
        # elif z <= 10:
        #     simplify_tolerance = 10   # Drastically reduced from 50
        #     min_distance = 4         # Drastically reduced from 20
        # elif z <= 13:
        #     simplify_tolerance = 5    # Drastically reduced from 20
        #     min_distance = 2         # Drastically reduced from 10
        # elif z <= 15:
        #     simplify_tolerance = 2    # Drastically reduced from 10
        #     min_distance = 1         # Drastically reduced from 5
        # elif z <= 17:
        #     simplify_tolerance = 1    # Drastically reduced from 5
        #     min_distance = 0.5       # Drastically reduced from 2
        # else:  # z >= 18
        #     simplify_tolerance = 0    # No simplification at highest zoom
        #     min_distance = 0         # No distance filtering at highest zoom

        # Always use the preserve topology function for all zoom levels
        use_preserve_topology = True  # Changed from z >= 8
        simplify_func = "ST_SimplifyPreserveTopology"

        # SQL query using ST_AsMVT with improved simplification
        # This generates MVT tiles with both points and lines for all flights
        query = f"""
        WITH 
        bounds AS (
            SELECT ST_TileEnvelope({z}, {x}, {y}) AS geom
        ),
        bounds_with_margin AS (
            SELECT ST_TileEnvelope({z}, {x}, {y}, margin => {margin_size}) AS geom
        ),
        -- Get flight metadata to assign colors
        flights AS (
            SELECT 
                id, 
                flight_id,
                pilot_name,
                pilot_id,
                row_number() OVER (ORDER BY created_at) AS color_index
            FROM flights 
            WHERE id::text IN {flight_uuids_str}
        ),
        -- Get all points with row numbers for sampling
        numbered_points AS (
            SELECT 
                ROW_NUMBER() OVER (PARTITION BY t.flight_uuid ORDER BY t.datetime) as point_num,
                t.*,
                f.pilot_name,
                f.pilot_id,
                f.color_index % 10 as color_index,
                -- Calculate the distance from previous point (for minimum distance filtering)
                CASE 
                    WHEN LAG(t.geom) OVER (PARTITION BY t.flight_uuid ORDER BY t.datetime) IS NULL THEN 999999
                    ELSE ST_Distance(
                        t.geom::geography, 
                        LAG(t.geom) OVER (PARTITION BY t.flight_uuid ORDER BY t.datetime)::geography
                    ) 
                END as dist_from_prev
            FROM {table_name} t
            JOIN flights f ON t.flight_uuid = f.id
            WHERE t.flight_uuid::text IN {flight_uuids_str}
            -- Apply basic coordinate validation
            AND t.lat BETWEEN -90 AND 90 
            AND t.lon BETWEEN -180 AND 180
        ),
        -- For each flight, find the first and last point to always include
        special_points AS (
            -- First points
            (SELECT DISTINCT ON (flight_uuid) *
             FROM numbered_points
             ORDER BY flight_uuid, datetime)
            UNION
            -- Last points 
            (SELECT DISTINCT ON (flight_uuid) *
             FROM numbered_points
             ORDER BY flight_uuid, datetime DESC)
        ),
        -- First apply minimum distance filtering (to eliminate stationary noise)
        filtered_by_distance AS (
            SELECT *
            FROM numbered_points
            WHERE 
                -- Always include first point for each track
                point_num = 1
                -- Include points that meet the minimum distance
                OR dist_from_prev >= {min_distance}
                -- Always include special points (first/last)
                OR EXISTS (
                    SELECT 1 FROM special_points sp 
                    WHERE sp.id = numbered_points.id
                )
        ),
        -- Get all points by pilot (for creating full track lines)
        all_pilot_points AS (
            SELECT 
                fp.id,
                fp.geom,
                fp.elevation,
                fp.datetime,
                fp.pilot_id,
                fp.pilot_name,
                fp.color_index
            FROM filtered_by_distance fp
        ),
        -- Create complete linestrings per pilot (across ALL tiles)
        pilot_full_tracks AS (
            SELECT
                adp.pilot_id,
                adp.pilot_name,
                adp.color_index,
                -- Apply simplification to the track - resolves the issue with tiny stationary variations
                {simplify_func}(
                    ST_MakeLine(adp.geom ORDER BY adp.datetime), 
                    {simplify_tolerance}
                ) AS full_track_geom
            FROM all_pilot_points adp
            GROUP BY adp.pilot_id, adp.pilot_name, adp.color_index
        ),
        -- Filter just the points within this tile for the point layer
        -- with a second tier of sampling based on zoom level
        filtered_points AS (
            SELECT 
                t.id,
                t.geom,
                t.elevation,
                t.datetime,
                t.flight_uuid,
                t.pilot_name,
                t.pilot_id,
                t.color_index,
                t.point_num
            FROM filtered_by_distance t
            WHERE ST_Transform(t.geom, 3857) && (SELECT geom FROM bounds_with_margin)
            -- Apply additional time-based sampling for lower zoom levels
            AND (
                1=1
                -- Always include special points
                -- OR EXISTS (
                --     SELECT 1 FROM special_points sp 
                --     WHERE sp.id = t.id
                -- )
            )
            ORDER BY t.pilot_id, t.datetime
        ),
        -- Create the points layer
        point_mvt AS (
            SELECT 
                ST_AsMVTGeom(
                    ST_Transform(fp.geom, 3857), 
                    (SELECT geom FROM bounds),
                    4096,    -- Resolution: standard is 4096 for MVT
                    {buffer_size},   -- Buffer: to avoid clipping at tile edges
                    true     -- Clip geometries
                ) AS geom,
                fp.elevation::float as elevation,
                fp.datetime::text as datetime,
                fp.flight_uuid::text as flight_uuid,
                fp.pilot_name,
                fp.pilot_id,
                fp.color_index as color_index,
                fp.point_num as point_num
            FROM filtered_points fp
        ),
        -- Create the line layer by clipping the FULL track to the current tile
        line_data AS (
            SELECT 
                ST_AsMVTGeom(
                    ST_Transform(pft.full_track_geom, 3857),
                    (SELECT geom FROM bounds),
                    4096,    -- Resolution
                    {buffer_size},   -- Buffer
                    true     -- Clip geometries
                ) AS geom,
                pft.pilot_id,
                pft.pilot_name,
                pft.color_index,
                ROW_NUMBER() OVER () as feature_id  -- Add a numeric feature ID
            FROM pilot_full_tracks pft
            WHERE ST_Transform(pft.full_track_geom, 3857) && (SELECT geom FROM bounds_with_margin)
        )
        -- Generate and combine both MVTs
        SELECT 
            CASE 
                WHEN EXISTS (SELECT 1 FROM line_data) AND EXISTS (SELECT 1 FROM point_mvt)
                THEN ST_AsMVT(line_data.*, 'track_lines', 4096, 'geom', 'feature_id') || 
                     ST_AsMVT(point_mvt.*, 'track_points', 4096, 'geom')
                WHEN EXISTS (SELECT 1 FROM line_data) 
                THEN ST_AsMVT(line_data.*, 'track_lines', 4096, 'geom', 'feature_id')
                WHEN EXISTS (SELECT 1 FROM point_mvt)
                THEN ST_AsMVT(point_mvt.*, 'track_points', 4096, 'geom')
                ELSE NULL
            END AS mvt
        FROM line_data, point_mvt
        """

        # Execute the query and get the tile
        result = db.execute(text(query)).fetchone()

        if result and result[0]:
            # Return the MVT tile as binary data
            return Response(content=result[0], media_type="application/x-protobuf")
        else:
            # Return an empty tile
            return Response(content=b"", media_type="application/x-protobuf")

    except Exception as e:
        logger.error(f"Error generating daily tracks vector tile: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to generate daily tracks tile: {str(e)}"
        )


@router.get("/track-preview/{flight_uuid}")
async def get_track_preview(
    flight_uuid: UUID,
    width: int = Query(
        600, description="Width of the preview image in pixels"),
    height: int = Query(
        400, description="Height of the preview image in pixels"),
    color: str = Query(
        "0x0000ff", description="Color of the track path in hex format"),
    weight: int = Query(5, description="Weight/thickness of the track path"),
    max_points: int = Query(
        1000, description="Maximum number of points to use in the polyline"),
    credentials: HTTPAuthorizationCredentials = Security(security),
    db: Session = Depends(get_db)
):
    """
    Generate a Google Static Maps preview URL for a flight track using the encoded polyline.
    Also returns track statistics including distance, duration, speeds, and elevation data.
    Includes location information for the start point of the flight.

    Parameters:
    - flight_uuid: UUID of the flight
    - width: Width of the preview image (default: 600)
    - height: Height of the preview image (default: 400)
    - color: Color of the track path in hex format (default: 0x0000ff - blue)
    - weight: Weight/thickness of the track path (default: 5)
    - max_points: Maximum number of points to use (default: 1000, reduces URL length)
    """
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

            if not token_data.get("sub", "").startswith("contest:"):
                raise HTTPException(
                    status_code=403,
                    detail="Invalid token subject - must be contest-specific"
                )

        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Token expired")
        except PyJWTError as e:
            raise HTTPException(
                status_code=401, detail=f"Invalid token: {str(e)}")

        # Get flight from database
        flight = db.query(Flight).filter(
            Flight.id == flight_uuid
        ).first()

        if not flight:
            raise HTTPException(
                status_code=404,
                detail=f"Flight not found with UUID {flight_uuid}"
            )

        # Get the encoded polyline for the flight with simplification
        if flight.source == 'live':
            func_name = 'generate_live_track_linestring'
            table_name = 'live_track_points'
        else:  # source == 'upload'
            func_name = 'generate_uploaded_track_linestring'
            table_name = 'uploaded_track_points'

        # First get track statistics using PostGIS - fixed query to handle elevation gain/loss
        stats_query = f"""
        WITH track AS (
            SELECT 
                tp.datetime,
                tp.elevation,
                tp.geom
            FROM {table_name} tp
            WHERE tp.flight_uuid = '{flight_uuid}'
            ORDER BY tp.datetime
        ),
        track_stats AS (
            SELECT
                -- Distance in meters
                ST_Length(ST_MakeLine(geom)::geography) as distance,
                -- Time values
                MIN(datetime) as start_time,
                MAX(datetime) as end_time,
                -- Elevation values
                MIN(elevation) as min_elevation,
                MAX(elevation) as max_elevation,
                MAX(elevation) - MIN(elevation) as elevation_range
            FROM track
        ),
        -- Handle elevation gain/loss without using window functions inside aggregates
        track_with_prev AS (
            SELECT
                datetime,
                elevation,
                LAG(elevation) OVER (ORDER BY datetime) as prev_elevation
            FROM track
        ),
        elevation_changes AS (
            SELECT
                SUM(CASE WHEN (elevation - prev_elevation) > 1 THEN (elevation - prev_elevation) ELSE 0 END) as elevation_gain,
                SUM(CASE WHEN (elevation - prev_elevation) < -1 THEN ABS(elevation - prev_elevation) ELSE 0 END) as elevation_loss
            FROM track_with_prev
            WHERE prev_elevation IS NOT NULL
        )
        SELECT
            ts.distance,
            ts.start_time,
            ts.end_time,
            EXTRACT(EPOCH FROM (ts.end_time - ts.start_time)) as duration_seconds,
            ts.min_elevation,
            ts.max_elevation,
            ts.elevation_range,
            ec.elevation_gain,
            ec.elevation_loss,
            -- Speed calculations
            CASE
                WHEN EXTRACT(EPOCH FROM (ts.end_time - ts.start_time)) > 0
                THEN ts.distance / EXTRACT(EPOCH FROM (ts.end_time - ts.start_time))
                ELSE 0
            END as avg_speed_m_s,
            COUNT(*) as total_points
        FROM track_stats ts, elevation_changes ec, track
        GROUP BY 
            ts.distance, ts.start_time, ts.end_time, ts.min_elevation, 
            ts.max_elevation, ts.elevation_range, ec.elevation_gain, ec.elevation_loss;
        """

        stats_result = db.execute(text(stats_query)).fetchone()

        # Get the track geometry and simplify it for preview in a single query
        # This approach uses Douglas-Peucker algorithm with a dynamic tolerance
        # that adapts based on the track length and point count
        query = f"""
        WITH original AS (
            SELECT 
                {func_name}('{flight_uuid}'::uuid) AS geom,
                ST_NPoints({func_name}('{flight_uuid}'::uuid)) AS point_count,
                ST_Length({func_name}('{flight_uuid}'::uuid)::geography) AS track_length
        )
        SELECT 
            point_count as original_points,
            CASE 
                -- For tracks with fewer points than max_points, use as is
                WHEN point_count <= {max_points} THEN
                    ST_AsEncodedPolyline(geom)
                
                -- For tracks with more points, simplify with adaptive tolerance
                ELSE
                    ST_AsEncodedPolyline(
                        ST_SimplifyPreserveTopology(
                            geom, 
                            -- Calculate tolerance dynamically based on track length
                            -- Longer tracks get more aggressive simplification
                            0.00001 * (track_length / point_count) * SQRT(point_count / {max_points})
                        )
                    )
            END as encoded_polyline,
            -- Also get the number of points after simplification
            CASE 
                WHEN point_count <= {max_points} THEN
                    point_count
                ELSE
                    ST_NPoints(
                        ST_SimplifyPreserveTopology(
                            geom, 
                            0.00001 * (track_length / point_count) * SQRT(point_count / {max_points})
                        )
                    )
            END as simplified_points,
            -- Calculate bbox in single query for potential fallback
            ST_XMin(ST_Envelope(geom)) as min_lon,
            ST_YMin(ST_Envelope(geom)) as min_lat, 
            ST_XMax(ST_Envelope(geom)) as max_lon,
            ST_YMax(ST_Envelope(geom)) as max_lat,
            ST_X(ST_Centroid(geom)) as center_lon,
            ST_Y(ST_Centroid(geom)) as center_lat
        FROM original;
        """

        result = db.execute(text(query)).fetchone()

        if not result or not result[1]:
            return {
                "status": "error",
                "detail": "No track data available for this flight"
            }

        encoded_polyline = result[1]
        original_points = result[0]
        simplified_points = result[2]

        # Get bounding box values for potential fallback
        min_lon, min_lat = result[3], result[4]
        max_lon, max_lat = result[5], result[6]
        center_lon, center_lat = result[7], result[8]

        # If encoded polyline is still too large (> 8000 chars), use a more aggressive simplification
        if len(encoded_polyline) > 8000:
            # Try one more level of simplification with Douglas-Peucker but more aggressive
            query = f"""
            WITH track AS (
                SELECT {func_name}('{flight_uuid}'::uuid) AS geom
            )
            SELECT ST_AsEncodedPolyline(
                ST_SimplifyPreserveTopology(
                    geom,
                    -- More aggressive simplification for very long tracks
                    0.0001 * ST_Length(geom::geography) / {max_points // 4}
                )
            ) as encoded_polyline
            FROM track;
            """

            result = db.execute(text(query)).fetchone()
            if result and result[0]:
                encoded_polyline = result[0]

            # If still too large, fall back to center point marker
            if len(encoded_polyline) > 8000:
                # Create a static map with the center point and appropriate zoom
                # Determine appropriate zoom based on bounding box size
                lon_diff = abs(max_lon - min_lon)
                lat_diff = abs(max_lat - min_lat)

                # Dynamic zoom calculation based on bbox size
                zoom = max(
                    8, min(14, int(360 / (max(lon_diff, lat_diff * 2) * 111))))

                google_maps_preview_url = (
                    f"https://maps.googleapis.com/maps/api/staticmap?"
                    f"size={width}x{height}&center={center_lat},{center_lon}"
                    f"&zoom={zoom}"
                    f"&markers=color:red|{center_lat},{center_lon}"
                    f"&sensor=false"
                    f"&key={settings.GOOGLE_MAPS_API_KEY}"
                )

                return {
                    "flight_id": flight.flight_id,
                    "flight_uuid": str(flight.id),
                    "preview_url": google_maps_preview_url,
                    "source": flight.source,
                    "original_points": original_points,
                    "simplified_points": 1,
                    "note": "Track was too complex for detailed preview, showing center point with adjusted zoom"
                }

        # Create Google Static Maps URL with the encoded polyline
        google_maps_preview_url = (
            f"https://maps.googleapis.com/maps/api/staticmap?"
            f"size={width}x{height}&path=color:{color}|weight:{weight}|enc:{encoded_polyline}"
            f"&sensor=false"
            f"&key={settings.GOOGLE_MAPS_API_KEY}"
        )

        # Get start location information using Google Geocoding API
        start_location = {
            "lat": float(flight.first_fix['lat']) if flight.first_fix else 0,
            "lon": float(flight.first_fix['lon']) if flight.first_fix else 0,
            "formatted_address": None,
            "locality": None,
            "administrative_area": None,
            "country": None
        }

        try:
            async with ClientSession() as session:
                url = f"https://maps.googleapis.com/maps/api/geocode/json?latlng={start_location['lat']},{start_location['lon']}&key={settings.GOOGLE_MAPS_API_KEY}"
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data['results']:
                            # Get the most relevant result (first one)
                            result = data['results'][0]
                            start_location["formatted_address"] = result['formatted_address']

                            # Extract specific address components
                            for component in result['address_components']:
                                if 'locality' in component['types']:
                                    start_location["locality"] = component['long_name']
                                elif 'administrative_area_level_1' in component['types']:
                                    start_location["administrative_area"] = component['long_name']
                                elif 'country' in component['types']:
                                    start_location["country"] = component['long_name']
        except Exception as e:
            logger.error(f"Error getting location data: {str(e)}")
            # Continue even if geocoding fails

        # Format flight statistics
        stats = {}
        if stats_result:
            hours, remainder = divmod(int(stats_result.duration_seconds), 3600)
            minutes, seconds = divmod(remainder, 60)

            # Convert meters to kilometers
            distance_km = float(stats_result.distance) / \
                1000 if stats_result.distance else 0

            # Convert m/s to km/h
            avg_speed_kmh = float(stats_result.avg_speed_m_s) * \
                3.6 if stats_result.avg_speed_m_s else 0

            stats = {
                "distance": {
                    "meters": round(float(stats_result.distance), 2) if stats_result.distance else 0,
                    "kilometers": round(distance_km, 2)
                },
                "duration": {
                    "seconds": int(stats_result.duration_seconds) if stats_result.duration_seconds else 0,
                    "formatted": f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                },
                "speed": {
                    "avg_m_s": round(float(stats_result.avg_speed_m_s), 2) if stats_result.avg_speed_m_s else 0,
                    "avg_km_h": round(avg_speed_kmh, 2)
                },
                "elevation": {
                    "min": round(float(stats_result.min_elevation), 1) if stats_result.min_elevation is not None else None,
                    "max": round(float(stats_result.max_elevation), 1) if stats_result.max_elevation is not None else None,
                    "range": round(float(stats_result.elevation_range), 1) if stats_result.elevation_range is not None else None,
                    "gain": round(float(stats_result.elevation_gain), 1) if stats_result.elevation_gain is not None else None,
                    "loss": round(float(stats_result.elevation_loss), 1) if stats_result.elevation_loss is not None else None
                },
                "points": {
                    "total": stats_result.total_points if hasattr(stats_result, 'total_points') else 0
                },
                "timestamps": {
                    "start": stats_result.start_time.isoformat() if stats_result.start_time else None,
                    "end": stats_result.end_time.isoformat() if stats_result.end_time else None
                }
            }

        return {
            "flight_id": flight.flight_id,
            "flight_uuid": str(flight.id),
            "preview_url": google_maps_preview_url,
            "source": flight.source,
            "original_points": original_points,
            "simplified_points": simplified_points,
            "url_length": len(google_maps_preview_url),
            "start_location": start_location,  # Added start location information
            "stats": stats
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating track preview: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate track preview: {str(e)}"
        )


@router.get("/track-preview/{flight_id}")
async def get_track_preview_id(
    flight_id: str,
    width: int = Query(
        600, description="Width of the preview image in pixels"),
    height: int = Query(
        400, description="Height of the preview image in pixels"),
    color: str = Query(
        "0x0000ff", description="Color of the track path in hex format"),
    weight: int = Query(5, description="Weight/thickness of the track path"),
    max_points: int = Query(
        1000, description="Maximum number of points to use in the polyline"),
    token_data: Dict = Depends(verify_tracking_token),
    source: str = Query(..., regex="^.*(?:live|upload).*$",
                        description="Source containing 'live' or 'upload'"),
    db: Session = Depends(get_db)
):
    """
    Generate a Google Static Maps preview URL for a flight track using the encoded polyline.

    Parameters:
    - flight_uuid: UUID of the flight
    - width: Width of the preview image (default: 600)
    - height: Height of the preview image (default: 400)
    - color: Color of the track path in hex format (default: 0x0000ff - blue)
    - weight: Weight/thickness of the track path (default: 5)
    - max_points: Maximum number of points to use (default: 1000, reduces URL length)
    """
    try:

        # Get flight from database
        flight = db.query(Flight).filter(
            Flight.flight_id == flight_id,
            Flight.source == source
        ).first()

        flight_uuid = str(flight.id) if flight else None
        if not flight:
            raise HTTPException(
                status_code=404,
                detail=f"Flight not found with ID {flight_id}"
            )

        # Get the encoded polyline for the flight with simplification
        if flight.source == 'live':
            func_name = 'generate_live_track_linestring'
        else:  # source == 'upload'
            func_name = 'generate_uploaded_track_linestring'

        # Get the track geometry and simplify it for preview in a single query
        # This approach uses Douglas-Peucker algorithm with a dynamic tolerance
        # that adapts based on the track length and point count
        query = f"""
        WITH original AS (
            SELECT 
                {func_name}('{flight_uuid}'::uuid) AS geom,
                ST_NPoints({func_name}('{flight_uuid}'::uuid)) AS point_count,
                ST_Length({func_name}('{flight_uuid}'::uuid)::geography) AS track_length
        )
        SELECT 
            point_count as original_points,
            CASE 
                -- For tracks with fewer points than max_points, use as is
                WHEN point_count <= {max_points} THEN
                    ST_AsEncodedPolyline(geom)
                
                -- For tracks with more points, simplify with adaptive tolerance
                ELSE
                    ST_AsEncodedPolyline(
                        ST_SimplifyPreserveTopology(
                            geom, 
                            -- Calculate tolerance dynamically based on track length
                            -- Longer tracks get more aggressive simplification
                            0.00001 * (track_length / point_count) * SQRT(point_count / {max_points})
                        )
                    )
            END as encoded_polyline,
            -- Also get the number of points after simplification
            CASE 
                WHEN point_count <= {max_points} THEN
                    point_count
                ELSE
                    ST_NPoints(
                        ST_SimplifyPreserveTopology(
                            geom, 
                            0.00001 * (track_length / point_count) * SQRT(point_count / {max_points})
                        )
                    )
            END as simplified_points,
            -- Calculate bbox in single query for potential fallback
            ST_XMin(ST_Envelope(geom)) as min_lon,
            ST_YMin(ST_Envelope(geom)) as min_lat, 
            ST_XMax(ST_Envelope(geom)) as max_lon,
            ST_YMax(ST_Envelope(geom)) as max_lat,
            ST_X(ST_Centroid(geom)) as center_lon,
            ST_Y(ST_Centroid(geom)) as center_lat
        FROM original;
        """

        result = db.execute(text(query)).fetchone()

        if not result or not result[1]:
            return {
                "status": "error",
                "detail": "No track data available for this flight"
            }

        encoded_polyline = result[1]
        original_points = result[0]
        simplified_points = result[2]

        # Get bounding box values for potential fallback
        min_lon, min_lat = result[3], result[4]
        max_lon, max_lat = result[5], result[6]
        center_lon, center_lat = result[7], result[8]

        # If encoded polyline is still too large (> 8000 chars), use a more aggressive simplification
        if len(encoded_polyline) > 8000:
            # Try one more level of simplification with Douglas-Peucker but more aggressive
            query = f"""
            WITH track AS (
                SELECT {func_name}('{flight_uuid}'::uuid) AS geom
            )
            SELECT ST_AsEncodedPolyline(
                ST_SimplifyPreserveTopology(
                    geom,
                    -- More aggressive simplification for very long tracks
                    0.0001 * ST_Length(geom::geography) / {max_points // 4}
                )
            ) as encoded_polyline
            FROM track;
            """

            result = db.execute(text(query)).fetchone()
            if result and result[0]:
                encoded_polyline = result[0]

            # If still too large, fall back to center point marker
            if len(encoded_polyline) > 8000:
                # Create a static map with the center point and appropriate zoom
                # Determine appropriate zoom based on bounding box size
                lon_diff = abs(max_lon - min_lon)
                lat_diff = abs(max_lat - min_lat)

                # Dynamic zoom calculation based on bbox size
                zoom = max(
                    8, min(14, int(360 / (max(lon_diff, lat_diff * 2) * 111))))

                google_maps_preview_url = (
                    f"https://maps.googleapis.com/maps/api/staticmap?"
                    f"size={width}x{height}&center={center_lat},{center_lon}"
                    f"&zoom={zoom}"
                    f"&markers=color:red|{center_lat},{center_lon}"
                    f"&sensor=false"
                    f"&key={settings.GOOGLE_MAPS_API_KEY}"
                )

                return {
                    "flight_id": flight.flight_id,
                    "flight_uuid": str(flight.id),
                    "preview_url": google_maps_preview_url,
                    "source": flight.source,
                    "original_points": original_points,
                    "simplified_points": 1,
                    "note": "Track was too complex for detailed preview, showing center point with adjusted zoom"
                }

        # Create Google Static Maps URL with the encoded polyline
        google_maps_preview_url = (
            f"https://maps.googleapis.com/maps/api/staticmap?"
            f"size={width}x{height}&path=color:{color}|weight:{weight}|enc:{encoded_polyline}"
            f"&sensor=false"
            f"&key={settings.GOOGLE_MAPS_API_KEY}"
        )

        return {
            "flight_id": flight.flight_id,
            "flight_uuid": str(flight.id),
            "preview_url": google_maps_preview_url,
            "source": flight.source,
            "original_points": original_points,
            "simplified_points": simplified_points,
            "url_length": len(google_maps_preview_url)
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating track preview: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate track preview: {str(e)}"
        )


@router.get("/track-line/{flight_id}")
async def get_track_linestring(
    flight_id: str,
    source: str = Query(..., regex="^.*(?:live|upload).*$",
                        description="Source containing 'live' or 'upload'"),
    simplify: bool = Query(
        False, description="Whether to simplify the track geometry. If true, provides sampled coordinates for better performance."),
    credentials: HTTPAuthorizationCredentials = Security(security),
    db: Session = Depends(get_db)
):
    """
    Return the complete flight track as a GeoJSON LineString.
    Uses the PostGIS functions to generate the geometry.

    Parameters:
    - flight_uuid: UUID of the flight
    - source: Either 'live' or 'upload' to specify which track to retrieve
    - simplify: Optional parameter to simplify the line geometry (useful for large tracks)
    """
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

            if not token_data.get("sub", "").startswith("contest:"):
                raise HTTPException(
                    status_code=403,
                    detail="Invalid token subject - must be contest-specific"
                )

        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Token expired")
        except PyJWTError as e:
            raise HTTPException(
                status_code=401, detail=f"Invalid token: {str(e)}"
            )

        # Check if flight exists
        flight = db.query(Flight).filter(
            Flight.flight_id == flight_id,
            Flight.source == source
        ).first()

        if not flight:
            raise HTTPException(
                status_code=404,
                detail=f"Flight not found with ID {flight_id}"
            )

        flight_uuid = str(flight.id)

        # Build query to get LineString
        if flight.source == 'live':
            func_name = 'generate_live_track_linestring'
        else:  # source == 'upload'
            func_name = 'generate_uploaded_track_linestring'

        # Handle simplification - treat simplify as a boolean flag
        if simplify:
            # Use a default moderate value for simplification
            simplify_value = 0.0001

            # Use a simpler, more reliable approach with ST_SimplifyPreserveTopology
            query = f"""
            WITH original AS (
                SELECT {func_name}('{flight_uuid}'::uuid) AS geom
            )
            SELECT 
                CASE 
                    -- Check if the simplified geometry has enough points to be useful
                    WHEN ST_NPoints(ST_SimplifyPreserveTopology(geom, {simplify_value})) >= 10 
                        THEN ST_AsGeoJSON(ST_SimplifyPreserveTopology(geom, {simplify_value}))
                    -- Otherwise return the original geometry
                    ELSE ST_AsGeoJSON(geom) 
                END as geojson,
                CASE 
                    WHEN ST_NPoints(ST_SimplifyPreserveTopology(geom, {simplify_value})) >= 10 
                        THEN ST_AsEncodedPolyline(ST_SimplifyPreserveTopology(geom, {simplify_value}))
                    ELSE ST_AsEncodedPolyline(geom) 
                END as encoded_polyline
            FROM original;
            """
        else:
            # No simplification, return all points
            query = f"""
            SELECT 
                ST_AsGeoJSON({func_name}('{flight_uuid}'::uuid)) as geojson,
                ST_AsEncodedPolyline({func_name}('{flight_uuid}'::uuid)) as encoded_polyline;
            """

        # Execute query
        result = db.execute(text(query)).fetchone()

        if not result or not result[0]:
            # If no tracking points, return empty LineString
            return {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": []
                },
                "properties": {
                    "flight_id": flight.flight_id,
                    "flight_uuid": str(flight.id),
                    "pilot_name": flight.pilot_name,
                    "source": flight.source,
                    "total_points": flight.total_points,
                    "empty": True,
                    "encoded_polyline": ""
                }
            }

        # Build GeoJSON response
        linestring_geojson = result[0]
        encoded_polyline = result[1] if result[1] else ""

        # Parse the GeoJSON
        geometry = json.loads(linestring_geojson)

        # Handle sampling of coordinates for response when simplify=true
        sampled_coords = []
        if geometry and geometry.get('coordinates') and len(geometry['coordinates']) > 0:
            coords = geometry['coordinates']

            # Sample coordinates if needed for response
            if len(coords) > 50 and simplify:
                # Always include first and last points
                first_point = coords[0]
                last_point = coords[-1]

                # Sample middle points - take about 48 points evenly distributed
                sample_step = len(coords) // 48
                sampled_coords = [coords[i]
                                  for i in range(0, len(coords), sample_step)]

                # Ensure we include the last point if it wasn't included in sampling
                if sampled_coords[-1] != last_point:
                    sampled_coords.append(last_point)
            else:
                sampled_coords = coords

        # Use sampled coordinates for the response geometry if simplify=true
        response_geometry = None
        if simplify and len(sampled_coords) > 0:
            response_geometry = {
                "type": "LineString",
                "coordinates": sampled_coords
            }
        else:
            response_geometry = json.loads(linestring_geojson)

        # Return formatted response
        return {
            "type": "Feature",
            "geometry": response_geometry,
            "properties": {
                "flight_id": flight.flight_id,
                "flight_uuid": str(flight.id),
                "pilot_name": flight.pilot_name,
                "pilot_id": flight.pilot_id,
                "source": flight.source,
                "total_points": flight.total_points,
                "first_fix": flight.first_fix,
                "last_fix": flight.last_fix,
                "simplified": simplify,
                "sampled": simplify and len(sampled_coords) > 0,
                "encoded_polyline": encoded_polyline
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating track linestring: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate track linestring: {str(e)}"
        )


@router.get("/flight-state/{flight_uuid}", response_model=Dict)
async def get_flight_state_endpoint(
    flight_uuid: str,
    history: bool = Query(
        False, description="Include state history in response"),
    history_points: int = Query(
        10, description="Number of history points to include if history=True"),
    credentials: HTTPAuthorizationCredentials = Security(security),
    source: str = Query(..., regex="^.*(?:live|upload).*$"),
    db: Session = Depends(get_db)
):
    """
    Get the current state of a flight (flying, walking, stationary, etc.)
    Requires JWT token in Authorization header (Bearer token).
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

        # Get flight from database
        flight = db.query(Flight).filter(Flight.flight_id ==
                                         flight_uuid and Flight.source == source).first()

        if not flight:
            raise HTTPException(
                status_code=404,
                detail="Flight not found"
            )

        # Format the response
        response = {
            "flight_uuid": str(flight_uuid),
            "pilot_id": flight.pilot_id,
            "pilot_name": flight.pilot_name,
            "state": flight.flight_state.get('state', 'unknown') if flight.flight_state else 'unknown',
            "state_info": flight.flight_state,
            "last_updated": flight.flight_state.get('last_updated', None),
            "source": flight.source
        }

        # If history is requested, include state changes over time
        if history:
            # Get more track points to analyze state changes
            track_points = db.query(LiveTrackPoint).filter(
                LiveTrackPoint.flight_uuid == flight_uuid
            ).order_by(LiveTrackPoint.datetime.desc()).limit(history_points * 5).all()

            if track_points:
                # Format points for processing
                formatted_points = [{
                    'lat': float(point.lat),
                    'lon': float(point.lon),
                    'elevation': float(point.elevation) if point.elevation is not None else None,
                    'datetime': point.datetime
                } for point in track_points]

                # Calculate state history
                history_data = []
                window_size = min(5, len(formatted_points))

                for i in range(0, len(formatted_points), window_size):
                    window = formatted_points[i:i + window_size]
                    if window:
                        window_state, window_info = detect_flight_state(window)
                        history_data.append({
                            "datetime": window[-1]['datetime'].isoformat(),
                            "state": window_state,
                            "avg_speed": window_info.get('avg_speed'),
                            "altitude_change": window_info.get('altitude_change')
                        })

                response["state_history"] = history_data

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting flight state: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get flight state: {str(e)}"
        )


async def update_flight_state(flight_uuid, db, source=None):
    """
    Update the flight state for a specific flight and broadcast it to WebSocket clients
    This is designed to be called as an async background task

    Args:
        flight_uuid: UUID of the flight
        db: Database session
        source: Source of the flight data ('live' or 'upload') - if None, will be determined from the flight record
    """
    try:
        # Import here to avoid circular imports
        from api.flight_state import update_flight_state_in_db

        # Use proper context manager for session handling
        from database.db_replica import primary_db_context
        
        with primary_db_context() as db_session:
            # If source wasn't provided, determine it from the flight record
            if source is None:
                flight_info = db_session.query(Flight).filter(
                    Flight.id == flight_uuid).first()
                if flight_info:
                    source = flight_info.source

            # Update the flight state with the appropriate source
            state, state_info = update_flight_state_in_db(
                flight_uuid, db_session, source=source)

            # No need to broadcast separately as flight state will be included in regular track updates
    except Exception as e:
        # Log but don't raise - this is a background task
        logger.error(f"Error updating flight state: {str(e)}")


@router.get("/flight/bounds/{flight_uuid}")
async def get_flight_bounds(
    flight_uuid: UUID,
    credentials: HTTPAuthorizationCredentials = Security(security),
    db: Session = Depends(get_db)
):
    """
    Calculate the bounding box for a flight track.
    Returns the min/max coordinates that contain the entire flight path.

    Parameters:
    - flight_uuid: UUID of the flight
    """
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

            if not token_data.get("sub", "").startswith("contest:"):
                raise HTTPException(
                    status_code=403,
                    detail="Invalid token subject - must be contest-specific"
                )

        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Token expired")
        except PyJWTError as e:
            raise HTTPException(
                status_code=401, detail=f"Invalid token: {str(e)}"
            )

        # Check if flight exists
        flight = db.query(Flight).filter(
            Flight.id == flight_uuid
        ).first()

        if not flight:
            raise HTTPException(
                status_code=404,
                detail=f"Flight not found with UUID {flight_uuid}"
            )

        # Determine which function to use based on flight source
        if flight.source == 'live':
            func_name = 'generate_live_track_linestring'
        else:  # source == 'upload'
            func_name = 'generate_uploaded_track_linestring'

        # Query to get the bounding box
        query = f"""
        SELECT 
            ST_XMin(ST_Envelope(geom)) as min_lon,
            ST_YMin(ST_Envelope(geom)) as min_lat,
            ST_XMax(ST_Envelope(geom)) as max_lon,
            ST_YMax(ST_Envelope(geom)) as max_lat,
            ST_X(ST_Centroid(geom)) as center_lon,
            ST_Y(ST_Centroid(geom)) as center_lat
        FROM (SELECT {func_name}('{flight_uuid}'::uuid) AS geom) AS track;
        """

        result = db.execute(text(query)).fetchone()

        if not result:
            return {
                "flight_id": flight.flight_id,
                "flight_uuid": str(flight.id),
                "bounds": None,
                "error": "No track data available"
            }

        # Extract results
        min_lon, min_lat, max_lon, max_lat, center_lon, center_lat = result

        # Calculate recommended padding (5% of dimensions)
        lon_span = max_lon - min_lon
        lat_span = max_lat - min_lat

        lon_padding = lon_span * 0.05
        lat_padding = lat_span * 0.05

        return {
            "flight_id": flight.flight_id,
            "flight_uuid": str(flight.id),
            "pilot_name": flight.pilot_name,
            "source": flight.source,
            "bounds": {
                "min_lon": float(min_lon),
                "min_lat": float(min_lat),
                "max_lon": float(max_lon),
                "max_lat": float(max_lat)
            },
            "bounds_padded": {
                "min_lon": float(min_lon - lon_padding),
                "min_lat": float(min_lat - lat_padding),
                "max_lon": float(max_lon + lon_padding),
                "max_lat": float(max_lat + lat_padding)
            },
            "center": {
                "lon": float(center_lon),
                "lat": float(center_lat)
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error calculating flight bounds: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to calculate flight bounds: {str(e)}"
        )


@router.get("/flight/bounds/flightid/{flight_id}")
async def get_flight_bounds_by_id(
    flight_id: str,
    source: str = Query(..., regex="^.*(?:live|upload).*$",
                        description="Source containing 'live' or 'upload'"),
    token_data: Dict = Depends(verify_tracking_token),
    db: Session = Depends(get_replica_db)  # Use read replica for reads
):
    """
    Calculate the bounding box for a flight track using flight ID.
    Returns the min/max coordinates that contain the entire flight path.

    Parameters:
    - flight_id: ID of the flight
    - source: Either 'live' or 'upload' to specify which track to retrieve
    """
    try:
        # Check if flight exists
        flight = db.query(Flight).filter(
            Flight.flight_id == flight_id,
            Flight.source == source
        ).first()

        if not flight:
            raise HTTPException(
                status_code=404,
                detail=f"Flight not found with ID {flight_id} and source {source}"
            )

        flight_uuid = str(flight.id)

        # Determine which function to use based on flight source
        if flight.source == 'live':
            func_name = 'generate_live_track_linestring'
        else:  # source == 'upload'
            func_name = 'generate_uploaded_track_linestring'

        # Query to get the bounding box
        query = f"""
        SELECT 
            ST_XMin(ST_Envelope(geom)) as min_lon,
            ST_YMin(ST_Envelope(geom)) as min_lat,
            ST_XMax(ST_Envelope(geom)) as max_lon,
            ST_YMax(ST_Envelope(geom)) as max_lat,
            ST_X(ST_Centroid(geom)) as center_lon,
            ST_Y(ST_Centroid(geom)) as center_lat
        FROM (SELECT {func_name}('{flight_uuid}'::uuid) AS geom) AS track;
        """

        result = db.execute(text(query)).fetchone()

        if not result:
            return {
                "flight_id": flight.flight_id,
                "flight_uuid": str(flight.id),
                "bounds": None,
                "error": "No track data available"
            }

        # Extract results
        min_lon, min_lat, max_lon, max_lat, center_lon, center_lat = result

        # Calculate recommended padding (5% of dimensions)
        lon_span = max_lon - min_lon
        lat_span = max_lat - min_lat

        lon_padding = lon_span * 0.05
        lat_padding = lat_span * 0.05

        return {
            "flight_id": flight.flight_id,
            "flight_uuid": str(flight.id),
            "pilot_name": flight.pilot_name,
            "source": flight.source,
            "bounds": {
                "min_lon": float(min_lon),
                "min_lat": float(min_lat),
                "max_lon": float(max_lon),
                "max_lat": float(max_lat)
            },
            "bounds_padded": {
                "min_lon": float(min_lon - lon_padding),
                "min_lat": float(min_lat - lat_padding),
                "max_lon": float(max_lon + lon_padding),
                "max_lat": float(max_lat + lat_padding)
            },
            "center": {
                "lon": float(center_lon),
                "lat": float(center_lat)
            }
        }

    except Exception as e:
        logger.error(f"Error calculating flight bounds: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to calculate flight bounds: {str(e)}"
        )


@router.post("/notifications/send")
async def send_notification(
    request: NotificationRequest,
    credentials: HTTPAuthorizationCredentials = Security(security),
    db: Session = Depends(get_db)
):
    """Send a notification to all subscribers of a specific race (supports both Expo and FCM)"""
    try:
        # Existing auth logic remains the same
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
                status_code=401, detail=f"Invalid token: {str(e)}"
            )

        # Find all tokens for this race (existing logic)
        subscription_tokens = db.query(NotificationTokenDB).filter(
            NotificationTokenDB.race_id == request.raceId
        ).all()

        if not subscription_tokens:
            return {
                "success": False,
                "message": "No subscribers found for this race",
                "sent": 0,
                "recipients_count": 0,
                "total": 0,
                "errors": 0
            }

        # Analyze token distribution for logging
        expo_count = sum(1 for token in subscription_tokens
                         if detect_token_type(token.token) == TokenType.EXPO)
        fcm_count = len(subscription_tokens) - expo_count

        logger.info(
            f"Token distribution: {expo_count} Expo, {fcm_count} FCM tokens")

        # Send notifications using unified batch processing
        tickets = []
        errors = []
        tokens_to_remove = []
        total_tokens = len(subscription_tokens)

        # For FCM, batch size can be up to 500, but we'll keep it consistent
        batch_size = min(EXPO_BATCH_SIZE, 100)  # Use smaller of the two limits
        logger.info(
            f"Starting unified batch notification send for {total_tokens} recipients in batches of {batch_size}")

        for i in range(0, len(subscription_tokens), batch_size):
            batch_tokens = subscription_tokens[i:i + batch_size]
            batch_num = (i // batch_size) + 1
            total_batches = (len(subscription_tokens) +
                             batch_size - 1) // batch_size

            logger.debug(
                f"Processing batch {batch_num}/{total_batches} with {len(batch_tokens)} tokens")

            try:
                # Use unified batch sending that handles both Expo and FCM
                # Don't include title/body in extra_data - they're passed separately
                batch_tickets, batch_errors, batch_tokens_to_remove = await send_push_messages_batch_unified(
                    tokens=[token_record.token for token_record in batch_tokens],
                    token_records=batch_tokens,
                    title=request.title,
                    message=request.body,
                    extra_data=request.data  # Only pass custom data, not title/body
                )

                tickets.extend(batch_tickets)
                errors.extend(batch_errors)
                tokens_to_remove.extend(batch_tokens_to_remove)

                logger.debug(
                    f"Batch {batch_num} completed: {len(batch_tickets)} sent, {len(batch_errors)} errors")

                # Add small delay between batches to respect rate limits
                if i + batch_size < len(subscription_tokens):
                    await asyncio.sleep(EXPO_RATE_LIMIT_DELAY)

            except Exception as e:
                # If batch fails, fall back to individual sending for this batch
                logger.warning(
                    f"Batch {batch_num} send failed, falling back to individual sends: {str(e)}")

                for token_record in batch_tokens:
                    try:
                        # Prepare notification data with title and body included
                        notification_data = {
                            "title": request.title,
                            "body": request.body,
                            **(request.data or {})  # Merge with existing data
                        }

                        # Use unified individual sending
                        ticket = await send_push_message_unified(
                            token=token_record.token,
                            title=request.title,
                            message=request.body,
                            extra_data=notification_data
                        )
                        tickets.append(ticket)
                    except ValueError as e:
                        if "Device not registered" in str(e) or "not registered" in str(e).lower():
                            tokens_to_remove.append(token_record.id)
                        errors.append({
                            "token": token_record.token[:10] + "...",
                            "error": str(e)
                        })

        # Clean up invalid tokens (existing logic)
        if tokens_to_remove:
            for token_id in tokens_to_remove:
                db.query(NotificationTokenDB).filter(
                    NotificationTokenDB.id == token_id
                ).delete()
            db.commit()
            logger.info(f"Removed {len(tokens_to_remove)} invalid tokens")

        # Calculate success based on whether we sent at least one notification
        successful_sends = len(tickets)
        total_errors = len(errors)
        is_successful = successful_sends > 0

        # Save notification record to database
        try:
            # Extract the sender's token subject for audit trail
            sender_subject = token_data.get("sub", "unknown")

            sent_notification = SentNotification(
                race_id=request.raceId,
                title=request.title,
                body=request.body,
                data=request.data,
                total_recipients=total_tokens,
                successful_sends=successful_sends,
                failed_sends=total_errors,
                expo_recipients=expo_count,
                fcm_recipients=fcm_count,
                sender_token_subject=sender_subject,
                error_details=errors if errors else None,
                batch_processing=True
            )

            db.add(sent_notification)
            db.commit()

            logger.info(
                f"Saved notification record to database with ID: {sent_notification.id}")

        except Exception as e:
            # Log the error but don't fail the entire request
            logger.error(
                f"Failed to save notification record to database: {str(e)}")
            # Rollback only the notification record, not the token cleanup
            db.rollback()
            try:
                # Re-apply token cleanup if it was successful
                if tokens_to_remove:
                    for token_id in tokens_to_remove:
                        db.query(NotificationTokenDB).filter(
                            NotificationTokenDB.id == token_id
                        ).delete()
                    db.commit()
            except Exception as cleanup_error:
                logger.error(
                    f"Failed to re-apply token cleanup: {str(cleanup_error)}")

        # Enhanced logging with token type breakdown
        logger.info(
            f"Unified notification results: {successful_sends}/{total_tokens} sent successfully, "
            f"{total_errors} errors, {len(tokens_to_remove)} tokens removed. "
            f"Token types: {expo_count} Expo, {fcm_count} FCM"
        )

        return {
            "success": is_successful,
            "message": f"Sent {successful_sends} of {total_tokens} notifications" if is_successful else "Failed to send any notifications",
            "sent": successful_sends,
            "recipients_count": successful_sends,
            "total": total_tokens,
            "errors": total_errors,
            "error_details": errors if errors else None,
            "batch_processing": True,
            "token_distribution": {
                "expo": expo_count,
                "fcm": fcm_count
            }
        }

    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Database error while sending notifications: {str(e)}")
        raise HTTPException(
            status_code=500, detail="Database error while sending notifications")
    except Exception as e:
        logger.error(f"Error sending notifications: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to send notifications: {str(e)}"
        )


@router.get("/notifications/sent", response_model=List[SentNotificationResponse])
async def get_sent_notifications(
    race_id: Optional[str] = Query(None, description="Filter by race ID"),
    limit: int = Query(100, ge=1, le=500,
                       description="Maximum number of results"),
    offset: int = Query(0, ge=0, description="Number of results to skip"),
    credentials: HTTPAuthorizationCredentials = Security(security),
    db: Session = Depends(get_db)
):
    """
    Retrieve sent notifications with optional filtering by race.

    - **race_id**: Optional filter to get notifications for a specific race
    - **limit**: Maximum number of results to return (1-500, default: 100)
    - **offset**: Number of results to skip for pagination (default: 0)

    Returns a list of sent notifications sorted by sent_at timestamp (newest first).
    """
    try:
        # Verify JWT token
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
                status_code=401, detail=f"Invalid token: {str(e)}"
            )

        # Extract user info from token
        token_subject = token_data.get("sub", "")

        # Build query
        query = db.query(SentNotification)

        # Apply race filter if provided
        if race_id:
            # Verify user has access to this race
            if not token_subject.startswith("admin:") and f"contest:{race_id}" != token_subject:
                # Check if user has access to this specific race
                race = db.query(Race).filter(Race.race_id == race_id).first()
                if not race:
                    raise HTTPException(
                        status_code=404, detail="Race not found")
                # For now, allow access if race exists - you may want to add more specific authorization

            query = query.filter(SentNotification.race_id == race_id)

        # Apply sorting (newest first)
        query = query.order_by(SentNotification.sent_at.desc())

        # Apply pagination
        notifications = query.offset(offset).limit(limit).all()

        # Convert to response models
        response_notifications = []
        for notification in notifications:
            response_notifications.append(SentNotificationResponse(
                id=str(notification.id),
                race_id=notification.race_id,
                title=notification.title,
                body=notification.body,
                data=notification.data,
                total_recipients=notification.total_recipients,
                successful_sends=notification.successful_sends,
                failed_sends=notification.failed_sends,
                expo_recipients=notification.expo_recipients,
                fcm_recipients=notification.fcm_recipients,
                sent_at=notification.sent_at.isoformat(),
                sender_token_subject=notification.sender_token_subject,
                batch_processing=notification.batch_processing
            ))

        return response_notifications

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving sent notifications: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve notifications: {str(e)}"
        )


@router.get("/notifications/sent/count")
async def get_sent_notifications_count(
    race_id: Optional[str] = Query(None, description="Filter by race ID"),
    credentials: HTTPAuthorizationCredentials = Security(security),
    db: Session = Depends(get_db)
):
    """
    Get the total count of sent notifications with optional filtering by race.

    - **race_id**: Optional filter to count notifications for a specific race

    Returns the total count of notifications matching the criteria.
    """
    try:
        # Verify JWT token
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
                status_code=401, detail=f"Invalid token: {str(e)}"
            )

        # Build query
        query = db.query(func.count(SentNotification.id))

        # Apply race filter if provided
        if race_id:
            query = query.filter(SentNotification.race_id == race_id)

        # Get count
        total_count = query.scalar()

        return {
            "total_count": total_count,
            "race_id": race_id
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error counting sent notifications: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to count notifications: {str(e)}"
        )


# @router.post("/flymaster/upload/file")
# async def upload_flymaster_file(
#     request: Request,
#     file: UploadFile = File(None),
#     db: Session = Depends(get_db)
# ):
#     """
#     Upload Flymaster tracking data supporting multiple formats:
#     1. File upload (multipart/form-data)
#     2. Raw data (text/plain content from PHP curl with post_as_file=1)

#     Format:
#     device_serial, sha256key
#     list of points with uploaded_at, date_time (unix timestamp), lat, lon, gps_alt, speed, heading
#     EOF
#     """
#     try:
#         # Determine content source
#         content_str = None
#         source_type = "unknown"

#         # Priority 1: File upload (multipart/form-data)
#         if file and hasattr(file, 'read'):
#             try:
#                 content = await file.read()
#                 content_str = content.decode('utf-8')
#                 source_type = "file_upload"
#             except Exception as e:
#                 logger.warning(f"Failed to read uploaded file: {e}")

#         # Priority 2: Raw body (text/plain from PHP curl)
#         if not content_str:
#             try:
#                 body = await request.body()
#                 if body:
#                     content_str = body.decode('utf-8')
#                     source_type = "raw_body"
#             except Exception as e:
#                 logger.warning(f"Failed to read request body: {e}")

#         # Validate we got some content
#         if not content_str or not content_str.strip():
#             raise HTTPException(
#                 status_code=400,
#                 detail="No data received. Send as file upload or text/plain body"
#             )

#         logger.info(f"Flymaster upload received via: {source_type}")
#         lines = content_str.strip().split('\n')

#         if len(lines) < 3:
#             raise HTTPException(status_code=400, detail="Invalid file format")

#         # Parse header line (format: device_serial, sha256key)
#         header_parts = lines[0].split(',')
#         if len(header_parts) != 2:
#             raise HTTPException(
#                 status_code=400, detail="Invalid header format: expected 'device_serial, sha256key'")

#         device_serial = header_parts[0].strip()
#         sha256key = header_parts[1].strip()

#         # Convert device_serial directly to integer (it's already a numeric device ID)
#         try:
#             device_id = int(device_serial)
#         except ValueError:
#             raise HTTPException(
#                 status_code=400,
#                 detail=f"Invalid device_serial format: expected integer, got '{device_serial}'"
#             )

#         # Validate SHA256 key - it should be SHA256(device_id + secret)
#         import hashlib
#         combined = str(device_id) + settings.FLYMASTER_SECRET
#         expected_sha256 = hashlib.sha256(combined.encode()).hexdigest()

#         if sha256key != expected_sha256:
#             raise HTTPException(
#                 status_code=401,
#                 detail="Invalid SHA256 key - authentication failed"
#             )

#         # Find EOF
#         eof_index = -1
#         for i, line in enumerate(lines):
#             if line.strip() == "EOF":
#                 eof_index = i
#                 break

#         if eof_index == -1:
#             raise HTTPException(status_code=400, detail="EOF marker not found")

#         # Parse data points (between header and EOF)
#         data_lines = lines[1:eof_index]
#         points = []

#         for line in data_lines:
#             line = line.strip()
#             if not line:
#                 continue

#             try:
#                 # Expected format: uploaded_at, date_time (unix timestamp), lat, lon, gps_alt, speed, heading
#                 parts = [part.strip() for part in line.split(',')]
#                 if len(parts) != 7:
#                     logger.warning(f"Skipping malformed line: {line}")
#                     continue

#                 # Convert unix timestamps to datetime
#                 uploaded_at_unix = int(parts[0])
#                 unix_timestamp = int(parts[1])
#                 uploaded_at_dt = datetime.fromtimestamp(
#                     uploaded_at_unix, tz=timezone.utc)
#                 date_time = datetime.fromtimestamp(
#                     unix_timestamp, tz=timezone.utc)

#                 point = {
#                     "device_id": device_id,
#                     "date_time": date_time,
#                     "lat": float(parts[2]),
#                     "lon": float(parts[3]),
#                     "gps_alt": float(parts[4]),
#                     "heading": float(parts[6]),  # heading/bearing
#                     "speed": float(parts[5]),
#                     "uploaded_at": uploaded_at_dt
#                 }
#                 points.append(point)

#             except (ValueError, IndexError) as e:
#                 logger.warning(
#                     f"Skipping invalid line: {line}, error: {str(e)}")
#                 continue

#         # Create the batch request
#         flymaster_points = [FlymasterPointCreate(**point) for point in points]

#         batch_request = FlymasterBatchCreate(
#             device_serial=device_serial,
#             sha256key=sha256key,
#             points=flymaster_points
#         )

#         # Use fast batch insert without duplicate checking
#         points_added = 0
#         points_skipped = 0

#         logger.info(
#             f"Processing Flymaster file upload for device {device_id} with {len(flymaster_points)} points")

#         if flymaster_points:
#             try:
#                 # Prepare points for queueing
#                 points_for_queue = []
#                 for point in flymaster_points:
#                     point_dict = {
#                         "device_id": point.device_id,
#                         "date_time": point.date_time,
#                         "lat": point.lat,
#                         "lon": point.lon,
#                         "gps_alt": point.gps_alt,
#                         "heading": point.heading,
#                         "speed": point.speed,
#                         "uploaded_at": point.uploaded_at or datetime.now(timezone.utc)
#                     }
#                     points_for_queue.append(point_dict)

#                 # Queue for background processing
#                 queued = await redis_queue.queue_points(
#                     QUEUE_NAMES['flymaster'],
#                     points_for_queue,
#                     priority=1
#                 )

#                 if queued:
#                     points_added = len(flymaster_points)
#                     logger.info(
#                         f"Successfully queued {points_added} Flymaster points for background processing")
#                 else:
#                     # Fallback to direct insertion if queueing fails
#                     flymaster_objects = []

#                     for point in flymaster_points:
#                         point_data = {
#                             "device_id": point.device_id,
#                             "date_time": point.date_time,
#                             "lat": point.lat,
#                             "lon": point.lon,
#                             "gps_alt": point.gps_alt,
#                             "heading": point.heading,
#                             "speed": point.speed,
#                             "uploaded_at": point.uploaded_at or datetime.now(timezone.utc),
#                         }
#                         flymaster_objects.append(point_data)

#                     # Use insert().on_conflict_do_nothing() for handling duplicates gracefully
#                     stmt = insert(Flymaster).on_conflict_do_nothing(
#                         index_elements=['device_id', 'date_time', 'lat', 'lon']
#                     )
#                     db.execute(stmt, flymaster_objects)
#                     db.commit()
#                     points_added = len(flymaster_objects)

#                     logger.info(
#                         f"Successfully inserted {points_added} Flymaster points via batch insert (fallback)")

#             except Exception as e:
#                 db.rollback()
#                 logger.error(f"Error processing Flymaster points: {str(e)}")
#                 raise HTTPException(
#                     status_code=500,
#                     detail=f"Failed to process points: {str(e)}"
#                 )

#         logger.info(
#             f"Flymaster file upload completed: {points_added} added, {points_skipped} skipped")

#         # return FlymasterBatchResponse(
#         #     device_serial=device_serial,
#         #     points_added=points_added,
#         #     points_skipped=points_skipped,
#         #     message=f"Successfully processed {points_added} points from file, skipped {points_skipped} duplicates"
#         # )
#         return PlainTextResponse("OK", status_code=200)

#     except HTTPException:
#         raise
#     except SQLAlchemyError as e:
#         db.rollback()
#         logger.error(f"Database error during Flymaster file upload: {str(e)}")
#         raise HTTPException(
#             status_code=500,
#             detail="Database error during file upload"
#         )
#     except Exception as e:
#         db.rollback()
#         logger.error(f"Error during Flymaster file upload: {str(e)}")
#         raise HTTPException(
#             status_code=500,
#             detail=f"Failed to upload Flymaster file: {str(e)}"
#         )


@router.post("/flymaster/upload/file")
async def upload_flymaster_file(
    request: Request,
    file: UploadFile = File(None),
    db: Session = Depends(get_db)
):
    """
    Upload Flymaster tracking data supporting multiple formats:
    1. File upload (multipart/form-data)
    2. Raw data (text/plain content from PHP curl with post_as_file=1)

    Format:
    device_serial, sha256key
    list of points with uploaded_at, date_time (unix timestamp), lat, lon, gps_alt, speed, heading
    EOF
    """
    try:
        # Determine content source
        content_str = None
        source_type = "unknown"

        # Priority 1: File upload (multipart/form-data)
        if file and hasattr(file, 'read'):
            try:
                content = await file.read()
                content_str = content.decode('utf-8')
                source_type = "file_upload"
            except Exception as e:
                logger.warning(f"Failed to read uploaded file: {e}")

        # Priority 2: Raw body (text/plain from PHP curl)
        if not content_str:
            try:
                body = await request.body()
                if body:
                    content_str = body.decode('utf-8')
                    source_type = "raw_body"
            except Exception as e:
                logger.warning(f"Failed to read request body: {e}")

        # Validate we got some content
        if not content_str or not content_str.strip():
            logger.warning("No data received in Flymaster upload")
            return PlainTextResponse("NOK", status_code=400)

        logger.info(f"Flymaster upload received via: {source_type}")
        lines = content_str.strip().split('\n')

        if len(lines) < 3:
            logger.warning("Invalid Flymaster file format - less than 3 lines")
            return PlainTextResponse("NOK", status_code=400)

        # Parse header line (format: device_serial, sha256key)
        header_parts = lines[0].split(',')
        if len(header_parts) != 2:
            logger.warning("Invalid Flymaster header format")
            return PlainTextResponse("NOK", status_code=400)

        device_serial = header_parts[0].strip()
        sha256key = header_parts[1].strip()

        # Convert device_serial directly to integer (it's already a numeric device ID)
        try:
            device_id = int(device_serial)
        except ValueError:
            logger.warning(f"Invalid device_serial format: {device_serial}")
            return PlainTextResponse("NOK", status_code=400)

        # Validate SHA256 key - it should be SHA256(device_id + secret)
        combined = str(device_id) + settings.FLYMASTER_SECRET
        expected_sha256 = hashlib.sha256(combined.encode()).hexdigest()
        
        logger.info(f"SHA256 validation - device: {device_serial}, received: {sha256key}, expected: {expected_sha256}")

        if sha256key != expected_sha256:
            logger.warning(f"Invalid SHA256 key for device {device_serial} - received: {sha256key}, expected: {expected_sha256}")
            return PlainTextResponse("NOK", status_code=401)
        
        # Check if device is registered and active
        logger.info(f"Checking registration for device {device_serial}")
        registration = db.query(DeviceRegistration).filter(
            DeviceRegistration.serial_number == device_serial,
            DeviceRegistration.device_type == 'flymaster',
            DeviceRegistration.is_active == True
        ).first()
        
        if not registration:
            logger.warning(f"Device {device_serial} not registered or inactive - rejecting points")
            return PlainTextResponse("NOK", status_code=403)
        else:
            logger.info(f"Found registration for device {device_serial}: pilot={registration.pilot_name}, race={registration.race_id}")
        
        # Validate the stored token
        try:
            token_data = jwt.decode(
                registration.pilot_token,
                settings.SECRET_KEY,
                algorithms=["HS256"],
                options={"verify_aud": False, "verify_iss": False}  # Don't verify audience and issuer for tracking tokens
            )
            
            # Extract race and pilot info from token
            race_id = token_data['race_id']
            pilot_id = token_data['pilot_id']
            pilot_name = token_data['pilot_name']
            
            logger.info(f"Device {device_serial} validated for pilot {pilot_name} in race {race_id}")
            
        except jwt.ExpiredSignatureError:
            # Token expired - deactivate registration
            registration.is_active = False
            registration.updated_at = datetime.now(timezone.utc)
            db.commit()
            logger.warning(f"Token expired for device {device_serial} - deactivated registration")
            return PlainTextResponse("NOK", status_code=401)
        except PyJWTError as e:
            logger.error(f"Invalid token for device {device_serial}: {str(e)}")
            return PlainTextResponse("NOK", status_code=401)

        # Find EOF
        eof_index = -1
        for i, line in enumerate(lines):
            if line.strip() == "EOF":
                eof_index = i
                break

        if eof_index == -1:
            logger.warning("EOF marker not found in Flymaster file")
            return PlainTextResponse("NOK", status_code=400)

        # Parse data points (between header and EOF)
        data_lines = lines[1:eof_index]
        points = []

        for line in data_lines:
            line = line.strip()
            if not line:
                continue

            try:
                # Expected format: uploaded_at, date_time (unix timestamp), lat, lon, gps_alt, speed, heading
                parts = [part.strip() for part in line.split(',')]
                if len(parts) != 7:
                    logger.warning(f"Skipping malformed line: {line}")
                    continue

                # Convert unix timestamps to datetime
                uploaded_at_unix = int(parts[0])
                unix_timestamp = int(parts[1])
                uploaded_at_dt = datetime.fromtimestamp(
                    uploaded_at_unix, tz=timezone.utc)
                date_time = datetime.fromtimestamp(
                    unix_timestamp, tz=timezone.utc)

                point = {
                    "device_id": device_id,
                    "date_time": date_time,
                    "lat": float(parts[2]),
                    "lon": float(parts[3]),
                    "gps_alt": float(parts[4]),
                    "heading": float(parts[6]),  # heading/bearing
                    "speed": float(parts[5]),
                    "uploaded_at": uploaded_at_dt
                }
                points.append(point)

            except (ValueError, IndexError) as e:
                logger.warning(
                    f"Skipping invalid line: {line}, error: {str(e)}")
                continue

        # Note: Flight creation is now handled by the Redis queue processor
        # The processor will:
        # 1. Check for existing flights within 2-hour window
        # 2. Create new flights when gaps > 2 hours detected
        # 3. Convert points to live_track_points format

        # Queue points for background processing
        points_added = 0
        points_skipped = 0
        
        logger.info(
            f"Processing Flymaster file upload for device {device_id} with {len(points)} points")

        if points:
            try:
                # Add race and pilot information to each point for the queue processor
                for point in points:
                    point['race_id'] = race_id
                    point['pilot_id'] = pilot_id
                    point['pilot_name'] = pilot_name
                    point['race_uuid'] = str(registration.race_uuid)
                
                # Queue for background processing
                # The queue processor will handle flight creation/updates
                queued = await redis_queue.queue_points(
                    QUEUE_NAMES['flymaster'],
                    points,  # Send the raw points dictionary with race/pilot info
                    priority=1
                )

                if queued:
                    points_added = len(points)
                    logger.info(
                        f"Successfully queued {points_added} Flymaster points for conversion to live tracking")
                else:
                    logger.error("Failed to queue Flymaster points")
                    return PlainTextResponse("NOK", status_code=500)

            except Exception as e:
                logger.error(f"Error queueing Flymaster points: {str(e)}")
                return PlainTextResponse("NOK", status_code=500)

        logger.info(
            f"Flymaster file upload completed: {points_added} queued")

        # Return plain text "OK" as expected by Flymaster devices
        return PlainTextResponse("OK", status_code=200)

    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Database error during Flymaster file upload: {str(e)}")
        return PlainTextResponse("NOK", status_code=500)
    except Exception as e:
        db.rollback()
        logger.error(f"Error during Flymaster file upload: {str(e)}")
        return PlainTextResponse("NOK", status_code=500)


@router.get("/flymaster/points/{serial_id}/raw")
async def flymaster_points(
    serial_id: int,
    credentials: HTTPAuthorizationCredentials = Security(security),
    start_date: Optional[str] = Query(
        None, description="Start date filter (ISO 8601 format, e.g. 2025-06-08T09:31:22+03:00)"),
    end_date: Optional[str] = Query(
        None, description="End date filter (ISO 8601 format, e.g. 2025-06-08T18:31:22+03:00)"),
    db: Session = Depends(get_db)
):
    """
    Get all track points for a specific flymaster serial id.
    Requires JWT token in Authorization header (Bearer token).
    Returns points with datetime, lat, lon, and elevation.
    Optional date filtering with start_date and end_date parameters.
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

        # Get all track points for this Flymaster device
        # First find flights for this device_id
        flights = db.query(Flight).filter(
            Flight.device_id == str(serial_id),
            Flight.source.in_(['flymaster_live', 'flymaster_upload'])
        ).all()
        
        if not flights:
            return {
                "device_id": serial_id,
                "points": []
            }
        
        # Get track points for these flights
        flight_uuids = [f.id for f in flights]
        query = db.query(LiveTrackPoint).filter(
            LiveTrackPoint.flight_uuid.in_(flight_uuids)
        )

        # Apply date filters if provided
        if start_date:
            try:
                start_datetime = datetime.fromisoformat(
                    start_date.replace('Z', '+00:00'))
                query = query.filter(LiveTrackPoint.datetime >= start_datetime)
            except ValueError as e:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid start_date format: {str(e)}. Use ISO 8601 format (e.g., 2025-06-08T09:31:22+03:00)"
                )

        if end_date:
            try:
                end_datetime = datetime.fromisoformat(
                    end_date.replace('Z', '+00:00'))
                query = query.filter(LiveTrackPoint.datetime <= end_datetime)
            except ValueError as e:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid end_date format: {str(e)}. Use ISO 8601 format (e.g., 2025-06-08T18:31:22+03:00)"
                )

        track_points = query.order_by(LiveTrackPoint.datetime).all()

        if not track_points:
            logger.warning(
                f"No track points found for serial_id: {serial_id} with filters start_date: {start_date}, end_date: {end_date}")
            return {
                "success": True,
                "serial_id": serial_id,
                "total_points": 0,
                "date_filters": {
                    "start_date": start_date,
                    "end_date": end_date
                },
                "points": []
            }

        # Format points as simple dictionaries
        points = [{
            "datetime": point.date_time.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "lat": float(point.lat),
            "lon": float(point.lon),
            "gps_alt": float(point.gps_alt) if point.gps_alt is not None else None
        } for point in track_points]

        return {
            "success": True,
            "serial_id": serial_id,
            "total_points": len(points),
            "date_filters": {
                "start_date": start_date,
                "end_date": end_date
            },
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


@router.get("/tasks", status_code=200)
async def get_tasks(
    token: str = Query(..., description="Authentication token"),
    token_data: Dict = Depends(verify_tracking_token),
    db: Session = Depends(get_replica_db)  # Use read replica for mobile task fetching
):
    """
    Get tasks from HFSS server for the specified race.
    Returns task information including scoring and competition details.

    Parameters:
    - token: Authentication token (automatically validated via dependency)

    Returns:
    - Task data from HFSS server
    """
    try:
        race_id = token_data['race_id']

        # Validate race_id format and existence
        if not race_id:
            logger.warning("Empty race_id in token_data")
            raise HTTPException(
                status_code=400,
                detail="Invalid race_id in authentication token"
            )

        # Check if race exists in local database
        # race = db.query(Race).filter(Race.race_id == race_id).first()
        # if not race:
        #     logger.warning(f"Race not found in database: {race_id}")
        #     raise HTTPException(
        #         status_code=404,
        #         detail=f"Race {race_id} not found"
        #     )

        # Construct HFSS server URL
        hfss_url = f"{settings.HFSS_SERVER.rstrip('/')}/tasks/{race_id}"

        logger.info(f"Fetching tasks from HFSS server: {hfss_url}")

        # Use aiohttp for async HTTP requests (more suitable for FastAPI)
        timeout = aiohttp.ClientTimeout(total=10)  # 10 second timeout

        async with ClientSession(timeout=timeout) as session:
            try:
                async with session.get(hfss_url) as response:
                    if response.status == 200:
                        tasks_data = await response.json()

                        logger.info(
                            f"Successfully retrieved tasks for race {race_id}")

                        # Add metadata to response
                        return {
                            "success": True,
                            "race_id": race_id,
                            # "race_name": race.name,
                            "retrieved_at": datetime.now(timezone.utc).isoformat(),
                            "source": "hfss_server",
                            "tasks": tasks_data
                        }

                    elif response.status == 404:
                        logger.warning(
                            f"Tasks not found on HFSS server for race {race_id}")
                        raise HTTPException(
                            status_code=404,
                            detail=f"Tasks not found for race {race_id} on HFSS server"
                        )

                    elif response.status == 403:
                        logger.error(
                            f"Access forbidden for race {race_id} on HFSS server")
                        raise HTTPException(
                            status_code=403,
                            detail="Access forbidden to HFSS server"
                        )

                    else:
                        error_text = await response.text()
                        logger.error(
                            f"HFSS server returned status {response.status}: {error_text}")
                        raise HTTPException(
                            status_code=response.status,
                            detail=f"HFSS server error: {response.status}"
                        )

            except asyncio.TimeoutError:
                logger.error(
                    f"Timeout connecting to HFSS server for race {race_id}")
                raise HTTPException(
                    status_code=504,
                    detail="Timeout connecting to HFSS server"
                )

            except aiohttp.ClientError as e:
                logger.error(
                    f"Client error connecting to HFSS server: {str(e)}")
                raise HTTPException(
                    status_code=502,
                    detail="Error connecting to HFSS server"
                )

    except HTTPException:
        # Re-raise HTTP exceptions (they're already properly formatted)
        raise

    except Exception as e:
        logger.error(f"Unexpected error in get_tasks endpoint: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Internal server error while retrieving tasks"
        )


@router.delete("/admin/delete-all-live-flights")
async def delete_all_live_flights(
    token: str = Query(..., description="Admin auth token"),
    db: Session = Depends(get_db)
):
    """
    Delete all live flights and their associated track points.
    Points are automatically deleted due to CASCADE constraints.
    Requires admin authentication token.
    """
    # Simple token check for admin access
    if token != settings.SECRET_KEY:
        raise HTTPException(status_code=403, detail="Invalid admin token")
    
    try:
        # Count flights before deletion for response
        live_flight_count = db.query(Flight).filter(
            Flight.source.contains('live')
        ).count()
        
        # Delete all live flights (CASCADE will delete points automatically)
        db.query(Flight).filter(
            Flight.source.contains('live')
        ).delete(synchronize_session=False)
        
        db.commit()
        
        logger.warning(f"Admin deleted all live flights. Count: {live_flight_count}")
        
        return {
            "success": True,
            "message": f"Deleted {live_flight_count} live flights and all associated points",
            "deleted_flights": live_flight_count
        }
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting live flights: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete live flights: {str(e)}"
        )


@router.delete("/admin/delete-all-upload-flights")
async def delete_all_upload_flights(
    token: str = Query(..., description="Admin auth token"),
    db: Session = Depends(get_db)
):
    """
    Delete all uploaded flights and their associated track points.
    Points are automatically deleted due to CASCADE constraints.
    Requires admin authentication token.
    """
    # Simple token check for admin access
    if token != settings.SECRET_KEY:
        raise HTTPException(status_code=403, detail="Invalid admin token")
    
    try:
        # Count flights before deletion for response
        upload_flight_count = db.query(Flight).filter(
            Flight.source == 'upload'
        ).count()
        
        # Delete all upload flights (CASCADE will delete points automatically)
        db.query(Flight).filter(
            Flight.source == 'upload'
        ).delete(synchronize_session=False)
        
        db.commit()
        
        logger.warning(f"Admin deleted all upload flights. Count: {upload_flight_count}")
        
        return {
            "success": True,
            "message": f"Deleted {upload_flight_count} upload flights and all associated points",
            "deleted_flights": upload_flight_count
        }
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting upload flights: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete upload flights: {str(e)}"
        )


@router.post("/admin/persist-flymaster-flights")
async def persist_flymaster_flights(
    credentials: HTTPAuthorizationCredentials = Security(security),
    db: Session = Depends(get_db)
):
    """
    Convert Flymaster live tracking points to upload points for permanent storage.
    Creates a duplicate flight record with source='flymaster_upload' to distinguish from live data.
    This prevents Flymaster data from being deleted after 2 days by the hypertable retention policy.
    The original live flight and points are preserved.
    """
    # Verify JWT token
    try:
        token_data = jwt.decode(
            credentials.credentials,
            settings.SECRET_KEY,
            algorithms=["HS256"],
            audience="api.hikeandfly.app",
            issuer="hikeandfly.app",
            verify=True
        )
    except (PyJWTError, jwt.ExpiredSignatureError) as e:
        raise HTTPException(status_code=403, detail="Invalid or expired token")
    
    try:
        # Get all Flymaster flights that are still in live (not yet persisted)
        flymaster_flights = db.query(Flight).filter(
            Flight.source == 'flymaster_live'
        ).all()
        
        if not flymaster_flights:
            return {
                "success": True,
                "message": "No Flymaster flights found to persist",
                "flights_processed": 0,
                "points_copied": 0
            }
        
        total_points_copied = 0
        flights_processed = 0
        flight_details = []
        
        for flight in flymaster_flights:
            # Check if we already have a corresponding upload flight
            upload_flight_id = f"{flight.flight_id}-upload"
            existing_upload_flight = db.query(Flight).filter(
                Flight.flight_id == upload_flight_id,
                Flight.source == 'flymaster_upload'
            ).first()
            
            if not existing_upload_flight:
                # Create a new flight record for the upload version
                upload_flight = Flight(
                    flight_id=upload_flight_id,
                    race_uuid=flight.race_uuid,
                    race_id=flight.race_id,
                    pilot_id=flight.pilot_id,
                    pilot_name=flight.pilot_name,
                    created_at=flight.created_at,
                    source='flymaster_upload',  # Mark as upload version
                    device_id=flight.device_id,
                    first_fix=flight.first_fix,
                    last_fix=flight.last_fix,
                    total_points=flight.total_points
                )
                db.add(upload_flight)
                db.commit()
                db.refresh(upload_flight)
                logger.info(f"Created upload flight {upload_flight_id} with UUID {upload_flight.id}")
            else:
                upload_flight = existing_upload_flight
                logger.info(f"Using existing upload flight {upload_flight_id}")
            
            # Get all live points for this flight
            live_points = db.query(LiveTrackPoint).filter(
                LiveTrackPoint.flight_uuid == flight.id
            ).all()
            
            if not live_points:
                continue
            
            # Delete any existing upload points for this flight to ensure 100% sync
            db.query(UploadedTrackPoint).filter(
                UploadedTrackPoint.flight_uuid == upload_flight.id
            ).delete(synchronize_session=False)
            db.commit()
            logger.info(f"Cleared existing upload points for flight {upload_flight.flight_id}")
            
            # Convert live points to upload points format with the upload flight UUID
            upload_points = []
            for point in live_points:
                upload_point = {
                    'flight_id': upload_flight.flight_id,  # Use upload flight ID
                    'flight_uuid': str(upload_flight.id),   # Use upload flight UUID
                    'datetime': point.datetime.isoformat() if hasattr(point.datetime, 'isoformat') else str(point.datetime),
                    'lat': point.lat,
                    'lon': point.lon,
                    'elevation': point.elevation,
                    'barometric_altitude': point.barometric_altitude
                }
                upload_points.append(upload_point)
            
            # Queue upload points using Redis queue for batch processing
            if upload_points:
                from redis_queue_system.redis_queue import redis_queue
                
                # Split into chunks if needed (queue in batches of 100)
                chunk_size = 100
                for i in range(0, len(upload_points), chunk_size):
                    chunk = upload_points[i:i + chunk_size]
                    await redis_queue.queue_points(QUEUE_NAMES['upload'], chunk)
                
                points_added = len(upload_points)
                total_points_copied += points_added
                flights_processed += 1
                
                flight_details.append({
                    "original_flight_id": flight.flight_id,
                    "upload_flight_id": upload_flight.flight_id,
                    "pilot": flight.pilot_name,
                    "device": flight.device_id,
                    "points_queued": points_added,
                    "total_live_points": len(live_points)
                })
                
                logger.info(f"Queued {points_added} points for persistence from Flymaster flight {flight.flight_id}")
        
        db.commit()
        
        logger.warning(f"Admin persisted Flymaster flights. Flights: {flights_processed}, Points: {total_points_copied}")
        
        return {
            "success": True,
            "message": f"Successfully queued {flights_processed} Flymaster flights for persistence",
            "flights_processed": flights_processed,
            "points_queued": total_points_copied,
            "note": "Points are processed asynchronously via Redis queue. Duplicates are skipped automatically.",
            "flight_details": flight_details
        }
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error persisting Flymaster flights: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to persist Flymaster flights: {str(e)}"
        )


# ============== Device Registration Endpoints ==============

@router.post("/api/devices/register")
async def register_device(
    serial_number: str,
    pilot_token: str = Query(..., description="Pilot tracking token to associate with device"),
    device_type: str = "flymaster",
    credentials: HTTPAuthorizationCredentials = Security(security),
    db: Session = Depends(get_db)
):
    """
    Register a tracking device (Flymaster, Skytraxx, etc.) with a pilot token.
    Requires admin JWT authentication.
    Automatically deactivates any existing active registration for this serial number.
    """
    # Verify admin JWT token (same as other management endpoints)
    try:
        admin_token_data = jwt.decode(
            credentials.credentials,
            settings.SECRET_KEY,
            algorithms=["HS256"],
            audience="api.hikeandfly.app",
            issuer="hikeandfly.app",
            verify=True
        )
    except (PyJWTError, jwt.ExpiredSignatureError) as e:
        raise HTTPException(status_code=403, detail="Invalid or expired admin token")
    
    try:
        # Validate the pilot token (same as live/upload)
        token_data = await verify_tracking_token(pilot_token)
        race_id = token_data['race_id']
        pilot_id = token_data['pilot_id']
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
            db.commit()
            db.refresh(race)
        
        # Deactivate any existing active registration for this serial
        existing = db.query(DeviceRegistration).filter(
            DeviceRegistration.serial_number == serial_number,
            DeviceRegistration.is_active == True
        ).first()
        
        if existing:
            existing.is_active = False
            existing.updated_at = datetime.now(timezone.utc)
            logger.info(f"Deactivated existing registration for serial {serial_number}")
        
        # Create new registration
        registration = DeviceRegistration(
            serial_number=serial_number,
            device_type=device_type.lower(),
            pilot_token=pilot_token,  # Store the pilot token, not admin token
            race_uuid=race.id,
            race_id=race_id,
            pilot_id=pilot_id,
            pilot_name=pilot_name,
            is_active=True
        )
        
        db.add(registration)
        db.commit()
        db.refresh(registration)
        
        logger.info(f"Registered device {serial_number} ({device_type}) for pilot {pilot_name} in race {race_id}")
        
        return {
            "success": True,
            "message": f"Device {serial_number} registered successfully",
            "registration": {
                "id": str(registration.id),
                "serial_number": registration.serial_number,
                "device_type": registration.device_type,
                "race_id": registration.race_id,
                "pilot_id": registration.pilot_id,
                "pilot_name": registration.pilot_name,
                "is_active": registration.is_active,
                "created_at": registration.created_at.isoformat()
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error registering device: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to register device: {str(e)}"
        )


@router.get("/api/devices")
async def list_all_devices(
    active_only: bool = Query(False, description="Show only active devices"),
    device_type: Optional[str] = Query(None, description="Filter by device type"),
    credentials: HTTPAuthorizationCredentials = Security(security),
    db: Session = Depends(get_replica_db)
):
    """
    List all registered devices (admin endpoint).
    Requires admin JWT authentication.
    """
    # Verify admin JWT token (same as persist endpoint)
    try:
        token_data = jwt.decode(
            credentials.credentials,
            settings.SECRET_KEY,
            algorithms=["HS256"],
            audience="api.hikeandfly.app",
            issuer="hikeandfly.app",
            verify=True
        )
    except (PyJWTError, jwt.ExpiredSignatureError) as e:
        raise HTTPException(status_code=403, detail="Invalid or expired token")
    
    try:
        
        query = db.query(DeviceRegistration)
        
        if active_only:
            query = query.filter(DeviceRegistration.is_active == True)
        
        if device_type:
            query = query.filter(DeviceRegistration.device_type == device_type.lower())
        
        devices = query.order_by(DeviceRegistration.created_at.desc()).all()
        
        return {
            "success": True,
            "total": len(devices),
            "devices": [{
                "id": str(device.id),
                "serial_number": device.serial_number,
                "device_type": device.device_type,
                "race_id": device.race_id,
                "pilot_id": device.pilot_id,
                "pilot_name": device.pilot_name,
                "is_active": device.is_active,
                "created_at": device.created_at.isoformat(),
                "updated_at": device.updated_at.isoformat()
            } for device in devices]
        }
        
    except Exception as e:
        logger.error(f"Error listing devices: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list devices: {str(e)}"
        )


@router.get("/api/devices/race/{race_id}")
async def list_race_devices(
    race_id: str,
    active_only: bool = Query(True, description="Show only active devices"),
    credentials: HTTPAuthorizationCredentials = Security(security),
    db: Session = Depends(get_replica_db)
):
    """
    List all devices registered for a specific race.
    Requires admin JWT authentication.
    """
    # Verify admin JWT token (same as persist endpoint)
    try:
        token_data = jwt.decode(
            credentials.credentials,
            settings.SECRET_KEY,
            algorithms=["HS256"],
            audience="api.hikeandfly.app",
            issuer="hikeandfly.app",
            verify=True
        )
    except (PyJWTError, jwt.ExpiredSignatureError) as e:
        raise HTTPException(status_code=403, detail="Invalid or expired token")
    
    try:
        
        query = db.query(DeviceRegistration).filter(
            DeviceRegistration.race_id == race_id
        )
        
        if active_only:
            query = query.filter(DeviceRegistration.is_active == True)
        
        devices = query.order_by(DeviceRegistration.pilot_name).all()
        
        return {
            "success": True,
            "race_id": race_id,
            "total": len(devices),
            "devices": [{
                "id": str(device.id),
                "serial_number": device.serial_number,
                "device_type": device.device_type,
                "pilot_id": device.pilot_id,
                "pilot_name": device.pilot_name,
                "is_active": device.is_active,
                "created_at": device.created_at.isoformat(),
                "updated_at": device.updated_at.isoformat()
            } for device in devices]
        }
        
    except Exception as e:
        logger.error(f"Error listing race devices: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list race devices: {str(e)}"
        )


@router.patch("/api/devices/{serial_number}/activate")
async def activate_device(
    serial_number: str,
    race_id: str,
    credentials: HTTPAuthorizationCredentials = Security(security),
    db: Session = Depends(get_db)
):
    """
    Activate a device for a specific race.
    Automatically deactivates it from other races.
    Requires admin JWT authentication.
    """
    # Verify admin JWT token (same as persist endpoint)
    try:
        token_data = jwt.decode(
            credentials.credentials,
            settings.SECRET_KEY,
            algorithms=["HS256"],
            audience="api.hikeandfly.app",
            issuer="hikeandfly.app",
            verify=True
        )
    except (PyJWTError, jwt.ExpiredSignatureError) as e:
        raise HTTPException(status_code=403, detail="Invalid or expired token")
    
    try:
        
        # Find the registration for this serial and race
        registration = db.query(DeviceRegistration).filter(
            DeviceRegistration.serial_number == serial_number,
            DeviceRegistration.race_id == race_id
        ).first()
        
        if not registration:
            raise HTTPException(
                status_code=404,
                detail=f"Device {serial_number} not registered for race {race_id}"
            )
        
        # Deactivate any other active registrations for this serial
        db.query(DeviceRegistration).filter(
            DeviceRegistration.serial_number == serial_number,
            DeviceRegistration.id != registration.id,
            DeviceRegistration.is_active == True
        ).update({"is_active": False, "updated_at": datetime.now(timezone.utc)})
        
        # Activate this registration
        registration.is_active = True
        registration.updated_at = datetime.now(timezone.utc)
        
        db.commit()
        
        logger.info(f"Activated device {serial_number} for race {race_id}")
        
        return {
            "success": True,
            "message": f"Device {serial_number} activated for race {race_id}",
            "registration": {
                "id": str(registration.id),
                "serial_number": registration.serial_number,
                "device_type": registration.device_type,
                "race_id": registration.race_id,
                "pilot_id": registration.pilot_id,
                "pilot_name": registration.pilot_name,
                "is_active": registration.is_active,
                "updated_at": registration.updated_at.isoformat()
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error activating device: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to activate device: {str(e)}"
        )


@router.patch("/api/devices/{serial_number}/deactivate")
async def deactivate_device(
    serial_number: str,
    credentials: HTTPAuthorizationCredentials = Security(security),
    db: Session = Depends(get_db)
):
    """
    Deactivate a device.
    Requires admin JWT authentication.
    """
    # Verify admin JWT token (same as persist endpoint)
    try:
        token_data = jwt.decode(
            credentials.credentials,
            settings.SECRET_KEY,
            algorithms=["HS256"],
            audience="api.hikeandfly.app",
            issuer="hikeandfly.app",
            verify=True
        )
    except (PyJWTError, jwt.ExpiredSignatureError) as e:
        raise HTTPException(status_code=403, detail="Invalid or expired token")
    
    try:
        
        # Find active registration for this serial
        registration = db.query(DeviceRegistration).filter(
            DeviceRegistration.serial_number == serial_number,
            DeviceRegistration.is_active == True
        ).first()
        
        if not registration:
            raise HTTPException(
                status_code=404,
                detail=f"No active registration found for device {serial_number}"
            )
        
        # Deactivate the registration
        registration.is_active = False
        registration.updated_at = datetime.now(timezone.utc)
        
        db.commit()
        
        logger.info(f"Deactivated device {serial_number}")
        
        return {
            "success": True,
            "message": f"Device {serial_number} deactivated",
            "registration": {
                "id": str(registration.id),
                "serial_number": registration.serial_number,
                "device_type": registration.device_type,
                "race_id": registration.race_id,
                "pilot_id": registration.pilot_id,
                "pilot_name": registration.pilot_name,
                "is_active": registration.is_active,
                "updated_at": registration.updated_at.isoformat()
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error deactivating device: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to deactivate device: {str(e)}"
        )


@router.patch("/tracking/api/devices/{device_uuid}/activate")
async def activate_device_by_uuid(
    device_uuid: UUID,
    credentials: HTTPAuthorizationCredentials = Security(security),
    db: Session = Depends(get_db)
):
    """
    Activate a device by UUID.
    Automatically deactivates any other registrations with the same serial number.
    Requires admin JWT authentication.
    """
    # Verify admin JWT token (same as persist endpoint)
    try:
        token_data = jwt.decode(
            credentials.credentials,
            settings.SECRET_KEY,
            algorithms=["HS256"],
            audience="api.hikeandfly.app",
            issuer="hikeandfly.app",
            verify=True
        )
    except (PyJWTError, jwt.ExpiredSignatureError) as e:
        raise HTTPException(status_code=403, detail="Invalid or expired token")
    
    try:
        
        # Find the registration by UUID
        registration = db.query(DeviceRegistration).filter(
            DeviceRegistration.id == device_uuid
        ).first()
        
        if not registration:
            raise HTTPException(
                status_code=404,
                detail=f"Device registration not found for UUID {device_uuid}"
            )
        
        # Deactivate any other active registrations for this serial number
        db.query(DeviceRegistration).filter(
            DeviceRegistration.serial_number == registration.serial_number,
            DeviceRegistration.id != registration.id,
            DeviceRegistration.is_active == True
        ).update({"is_active": False, "updated_at": datetime.now(timezone.utc)})
        
        # Activate this registration
        registration.is_active = True
        registration.updated_at = datetime.now(timezone.utc)
        
        db.commit()
        
        logger.info(f"Activated device {device_uuid} (serial: {registration.serial_number}) for race {registration.race_id}")
        
        return {
            "success": True,
            "message": f"Device {device_uuid} activated for race {registration.race_id}",
            "registration": {
                "id": str(registration.id),
                "serial_number": registration.serial_number,
                "device_type": registration.device_type,
                "race_id": registration.race_id,
                "pilot_id": registration.pilot_id,
                "pilot_name": registration.pilot_name,
                "is_active": registration.is_active,
                "updated_at": registration.updated_at.isoformat()
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error activating device by UUID: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to activate device: {str(e)}"
        )


@router.patch("/tracking/api/devices/{device_uuid}/deactivate")
async def deactivate_device_by_uuid(
    device_uuid: UUID,
    credentials: HTTPAuthorizationCredentials = Security(security),
    db: Session = Depends(get_db)
):
    """
    Deactivate a device by UUID.
    Requires admin JWT authentication.
    """
    # Verify admin JWT token (same as persist endpoint)
    try:
        token_data = jwt.decode(
            credentials.credentials,
            settings.SECRET_KEY,
            algorithms=["HS256"],
            audience="api.hikeandfly.app",
            issuer="hikeandfly.app",
            verify=True
        )
    except (PyJWTError, jwt.ExpiredSignatureError) as e:
        raise HTTPException(status_code=403, detail="Invalid or expired token")
    
    try:
        
        # Find registration by UUID
        registration = db.query(DeviceRegistration).filter(
            DeviceRegistration.id == device_uuid
        ).first()
        
        if not registration:
            raise HTTPException(
                status_code=404,
                detail=f"Registration not found for device {device_uuid}"
            )
        
        if not registration.is_active:
            raise HTTPException(
                status_code=400,
                detail=f"Device {device_uuid} is already inactive"
            )
        
        # Deactivate the registration
        registration.is_active = False
        registration.updated_at = datetime.now(timezone.utc)
        
        db.commit()
        
        logger.info(f"Deactivated device {device_uuid} (serial: {registration.serial_number})")
        
        return {
            "success": True,
            "message": f"Device {device_uuid} deactivated",
            "registration": {
                "id": str(registration.id),
                "serial_number": registration.serial_number,
                "device_type": registration.device_type,
                "race_id": registration.race_id,
                "pilot_id": registration.pilot_id,
                "pilot_name": registration.pilot_name,
                "is_active": registration.is_active,
                "updated_at": registration.updated_at.isoformat()
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error deactivating device by UUID: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to deactivate device: {str(e)}"
        )


@router.patch("/tracking/api/races/{race_id}/devices/activate-all")
async def activate_all_devices_for_race(
    race_id: str,
    credentials: HTTPAuthorizationCredentials = Security(security),
    db: Session = Depends(get_db)
):
    """
    Activate all devices registered for a specific race.
    This will deactivate these devices from any other races to maintain unique activation.
    Requires admin JWT authentication.
    """
    # Verify admin JWT token
    try:
        token_data = jwt.decode(
            credentials.credentials,
            settings.SECRET_KEY,
            algorithms=["HS256"],
            audience="api.hikeandfly.app",
            issuer="hikeandfly.app",
            verify=True
        )
    except (PyJWTError, jwt.ExpiredSignatureError) as e:
        raise HTTPException(status_code=403, detail="Invalid or expired token")
    
    try:
        # Find all device registrations for this race
        registrations = db.query(DeviceRegistration).filter(
            DeviceRegistration.race_id == race_id
        ).all()
        
        if not registrations:
            raise HTTPException(
                status_code=404,
                detail=f"No devices found for race {race_id}"
            )
        
        activated_count = 0
        already_active_count = 0
        
        for registration in registrations:
            if registration.is_active:
                already_active_count += 1
                continue
            
            # Deactivate any other active registrations for this serial number (maintaining unique activation)
            db.query(DeviceRegistration).filter(
                DeviceRegistration.serial_number == registration.serial_number,
                DeviceRegistration.id != registration.id,
                DeviceRegistration.is_active == True
            ).update({"is_active": False, "updated_at": datetime.now(timezone.utc)})
            
            # Activate this registration
            registration.is_active = True
            registration.updated_at = datetime.now(timezone.utc)
            activated_count += 1
        
        db.commit()
        
        logger.info(f"Activated {activated_count} devices for race {race_id} ({already_active_count} were already active)")
        
        return {
            "success": True,
            "message": f"Activated all devices for race {race_id}",
            "race_id": race_id,
            "total_devices": len(registrations),
            "activated": activated_count,
            "already_active": already_active_count,
            "device_ids": [str(reg.id) for reg in registrations]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error activating all devices for race: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to activate devices: {str(e)}"
        )


@router.patch("/tracking/api/races/{race_id}/devices/deactivate-all")
async def deactivate_all_devices_for_race(
    race_id: str,
    credentials: HTTPAuthorizationCredentials = Security(security),
    db: Session = Depends(get_db)
):
    """
    Deactivate all devices registered for a specific race.
    Requires admin JWT authentication.
    """
    # Verify admin JWT token
    try:
        token_data = jwt.decode(
            credentials.credentials,
            settings.SECRET_KEY,
            algorithms=["HS256"],
            audience="api.hikeandfly.app",
            issuer="hikeandfly.app",
            verify=True
        )
    except (PyJWTError, jwt.ExpiredSignatureError) as e:
        raise HTTPException(status_code=403, detail="Invalid or expired token")
    
    try:
        # Find all active device registrations for this race
        registrations = db.query(DeviceRegistration).filter(
            DeviceRegistration.race_id == race_id,
            DeviceRegistration.is_active == True
        ).all()
        
        if not registrations:
            # Check if there are any devices at all for this race
            total_devices = db.query(DeviceRegistration).filter(
                DeviceRegistration.race_id == race_id
            ).count()
            
            if total_devices == 0:
                raise HTTPException(
                    status_code=404,
                    detail=f"No devices found for race {race_id}"
                )
            else:
                return {
                    "success": True,
                    "message": f"No active devices to deactivate for race {race_id}",
                    "race_id": race_id,
                    "total_devices": total_devices,
                    "deactivated": 0,
                    "already_inactive": total_devices
                }
        
        deactivated_count = len(registrations)
        
        # Deactivate all active registrations
        for registration in registrations:
            registration.is_active = False
            registration.updated_at = datetime.now(timezone.utc)
        
        db.commit()
        
        # Get total device count for this race
        total_devices = db.query(DeviceRegistration).filter(
            DeviceRegistration.race_id == race_id
        ).count()
        
        logger.info(f"Deactivated {deactivated_count} devices for race {race_id}")
        
        return {
            "success": True,
            "message": f"Deactivated all devices for race {race_id}",
            "race_id": race_id,
            "total_devices": total_devices,
            "deactivated": deactivated_count,
            "already_inactive": total_devices - deactivated_count,
            "device_ids": [str(reg.id) for reg in registrations]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error deactivating all devices for race: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to deactivate devices: {str(e)}"
        )
