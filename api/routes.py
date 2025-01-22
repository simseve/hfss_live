from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy.orm import Session
from database.schemas import LiveTrackingRequest, LiveTrackPointCreate, FlightResponse, TrackUploadRequest
from pydantic import ValidationError
from database.models import UploadedTrackPoint, Flight, LiveTrackPoint
from typing import List, Dict, Any, Optional
from database.db_conf import get_db
import logging
from datetime import datetime, timezone
from api.auth import verify_tracking_token
from datetime import datetime
from sqlalchemy.exc import SQLAlchemyError  
from uuid import uuid4  

logger = logging.getLogger(__name__)

router = APIRouter()

@router.post("/live", status_code=202)
async def live_tracking(
    data: LiveTrackingRequest,
    token: str = Query(..., description="Authentication token"),
    token_data: Dict = Depends(verify_tracking_token),
    db: Session = Depends(get_db)
):
    """Handle live tracking data updates from mobile devices"""
    try:
        pilot_id = token_data['pilot_id']
        race_id = token_data['race_id']
        
        logger.info(f"Processing live tracking data for flight_id: {data.flight_id}")
        
        # Check if flight exists
        try:
            flight = db.query(Flight).filter(Flight.flight_id == data.flight_id).first()
            
            if not flight:
                logger.info(f"Creating new flight record for flight_id: {data.flight_id}")
                flight = Flight(
                    flight_id=data.flight_id,
                    pilot_id=pilot_id,
                    race_id=race_id,
                    created_at=datetime.now(timezone.utc),
                    source='live',
                )
                db.add(flight)
                try:
                    db.commit()
                    logger.info(f"Successfully created new flight record: {data.flight_id}")
                except Exception as e:
                    db.rollback()
                    logger.error(f"Failed to commit new flight: {str(e)}")
                    raise HTTPException(
                        status_code=500,
                        detail="Failed to create flight record"
                    )
            elif flight.pilot_id != pilot_id:
                raise HTTPException(
                    status_code=403,
                    detail="Not authorized to update this flight"
                )

            # Convert track points using Pydantic model
            track_points = [
                LiveTrackPoint(
                    **LiveTrackPointCreate(
                        flight_id=data.flight_id,
                        flight_uuid=flight.id,
                        datetime=point['datetime'],
                        lat=point['lat'],
                        lon=point['lon'],
                        elevation=point.get('elevation'),
                        speed=point.get('speed')
                    ).model_dump()
                ) for point in data.track_points
            ]

            logger.info(f"Saving {len(track_points)} track points for flight {data.flight_id}")
            
            try:
                db.bulk_save_objects(track_points)
                db.commit()
                logger.info(f"Successfully saved track points for flight {data.flight_id}")
            except Exception as e:
                db.rollback()
                logger.error(f"Failed to save track points: {str(e)}")
                raise HTTPException(
                    status_code=500,
                    detail="Failed to save track points"
                )

            return {
                'success': True,
                'message': f'Live tracking data processed ({len(track_points)} points)',
                'flight_id': data.flight_id
            }

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
        # Get pilot and race IDs from token
        pilot_id = token_data['pilot_id']
        race_id = token_data['race_id']

        if not upload_data.track_points:
            logger.info(f"Received empty track upload from pilot {pilot_id} - discarding")
            return Flight(
                id=uuid4(),  # Generate a new UUID
                flight_id=upload_data.flight_id,
                pilot_id=pilot_id,
                race_id=race_id,
                source='upload',
                created_at=datetime.now(timezone.utc),
                flight_metadata=upload_data.metadata.model_dump(exclude_none=True)
            )

        logger.info(f"Received track upload from pilot {pilot_id} for race {race_id}")
        logger.info(f"Total points: {len(upload_data.track_points)}")



        try:
            # Create flight record
            flight = db.query(Flight).filter(
                Flight.flight_id == upload_data.flight_id,
                Flight.source == 'upload'
            ).first()            
            
            # Convert metadata to dict and handle datetime serialization
            metadata_dict = upload_data.metadata.model_dump(exclude_none=True)
            if 'start_time' in metadata_dict:
                metadata_dict['start_time'] = metadata_dict['start_time'].isoformat()

            if flight:
                  raise HTTPException(
                    status_code=409,  # Conflict status code
                    detail="Flight ID with source upload already exists. Each flight must have a unique ID."
                )
                  
            else:
                # Create new flight
                flight = Flight(
                    flight_id=upload_data.flight_id,
                    race_id=race_id,
                    pilot_id=pilot_id,
                    created_at=datetime.now(timezone.utc),
                    source='upload',
                    flight_metadata=metadata_dict,
                    start_time=datetime.fromisoformat(upload_data.track_points[0]['datetime'].replace('Z', '+00:00')),
                    end_time=datetime.fromisoformat(upload_data.track_points[-1]['datetime'].replace('Z', '+00:00')),
                    total_points=len(upload_data.track_points)
                )
                db.add(flight)
                try:
                    db.commit()  # Commit to get the flight.id
                except SQLAlchemyError as e:
                    db.rollback()
                    logger.error(f"Failed to create flight record: {str(e)}")
                    raise HTTPException(
                        status_code=500,
                        detail="Failed to create flight record"
                    )

                # Convert and store track points
                track_points_db = [
                    UploadedTrackPoint(
                        flight_id=upload_data.flight_id,
                        flight_uuid=flight.id,
                        datetime=datetime.fromisoformat(point['datetime'].replace('Z', '+00:00')),
                        lat=point['lat'],
                        lon=point['lon'],
                        elevation=point.get('elevation'),
                        speed=point.get('speed')
                    )
                    for point in upload_data.track_points
                ]
                
                try:
                    db.bulk_save_objects(track_points_db)
                    db.commit()
                    logger.info(f"Successfully processed upload for flight {upload_data.flight_id}")
                    return flight
                except SQLAlchemyError as e:
                    db.rollback()
                    logger.error(f"Failed to save track points: {str(e)}")
                    raise HTTPException(
                        status_code=500,
                        detail="Failed to save track points"
                    )


        except SQLAlchemyError as e:
            db.rollback()
            logger.error(f"Database error while processing upload: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail="Database error while processing upload"
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing track upload: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to process track data")
        
        

@router.get("/check_assignment", status_code=200)
async def check_assignment(
    token: str = Query(..., description="Authentication token"),
    token_data: Dict = Depends(verify_tracking_token),
    db: Session = Depends(get_db)
):
    """Check if pilot has an active assignment"""
    try:
        pilot_id = token_data['pilot_id']
        race_id = token_data['race_id']
        
 
        return {
            'success': True,
            'assignment_id': 'fake'
        }

            
    except Exception as e:
        logger.error(f"Error checking assignment: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Failed to check assignment"
        )
        

@router.get("/points/{flight_id}")
async def get_flight_points(
    flight_id: str,
    collection_type: str = Query('upload', description="Type of tracking ('upload' or 'live')"),
    db: Session = Depends(get_db)
):
    """
    Get all tracking points for a specific flight up to the current moment.
    For admin/testing use only.
    """
    try:
        # Get flight from database
        flight = db.query(Flight).filter(
            Flight.flight_id == flight_id.rstrip('\t|'),
            Flight.source == collection_type
        ).first()
            
        if not flight:
            raise HTTPException(
                status_code=404,
                detail=f"Flight not found in {collection_type} collection"
            )

        # Choose the correct table model based on collection type
        TrackModel = UploadedTrackPoint if collection_type == 'upload' else LiveTrackPoint
        
        # Get track points
        track_points = db.query(TrackModel).filter(
            TrackModel.flight_id == flight_id
        ).order_by(TrackModel.datetime).all()
        
        # Convert track points to dictionary format
        points = [{
            'datetime': point.datetime.isoformat(),
            'lat': point.lat,
            'lon': point.lon,
            'elevation': point.elevation,
            'speed': point.speed
        } for point in track_points]
        
        return {
            'success': True,
            'flight_id': flight_id,
            'pilot_id': flight.pilot_id,
            'race_id': flight.race_id,
            'type': flight.source,  # 'live' or 'upload'
            'metadata': flight.flight_metadata or {},
            'created_at': flight.created_at.isoformat() if flight.created_at else None,
            'track_points': points,
            'total_points': len(points),
            'storage_type': 'timescaledb',
            'collection': collection_type
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving flight points: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve flight points: {str(e)}"
        )

        
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
                'created_at': flight.created_at.isoformat() if flight.created_at else None,
                'type': flight.source,
                'collection': 'uploads' if flight.source == 'upload' else 'live',
                'start_time': flight.start_time.isoformat() if flight.start_time else None,
                'end_time': flight.end_time.isoformat() if flight.end_time else None,
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