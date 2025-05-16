from fastapi import APIRouter, Depends, HTTPException, Query, Security, Response
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
from uuid import UUID
from database.models import ScoringTracks, Flight
from database.db_conf import get_db
from database.schemas import ScoringTrackBase, ScoringTrackCreate, ScoringTrackResponse, ScoringTrackUpdate, FlightTrackResponse
from sqlalchemy.exc import SQLAlchemyError
import logging
from api.auth import verify_tracking_token
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from datetime import datetime, timezone
from geoalchemy2.functions import ST_MakePoint, ST_AsGeoJSON
from geoalchemy2 import Geometry
from sqlalchemy import func, text
import jwt
from config import settings
from jwt.exceptions import PyJWTError

logger = logging.getLogger(__name__)
router = APIRouter()
security = HTTPBearer()


@router.post("/", status_code=201, response_model=ScoringTrackResponse)
async def create_scoring_track(
    track: ScoringTrackCreate,
    db: Session = Depends(get_db)
):
    """Insert a new scoring track point"""
    try:
        # Verify flight_uuid exists
        flight = db.query(Flight).filter(
            Flight.id == track.flight_uuid).first()
        if not flight:
            raise HTTPException(
                status_code=404, detail=f"Flight with UUID {track.flight_uuid} not found"
            )

        # Create point geometry
        point_geom = func.ST_SetSRID(
            func.ST_MakePoint(track.lon, track.lat), 4326)

        db_track = ScoringTracks(
            **track.model_dump(exclude={"geom"}),
            geom=point_geom
        )

        db.add(db_track)

        # Update the flight's total points count
        flight.total_points = (flight.total_points or 0) + 1

        db.commit()
        db.refresh(db_track)

        return db_track

    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Database error while creating scoring track: {str(e)}")
        raise HTTPException(
            status_code=500, detail="Failed to create scoring track")

    except Exception as e:
        logger.error(f"Error creating scoring track: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to create scoring track: {str(e)}")



@router.get("/", response_model=List[ScoringTrackResponse])
async def get_scoring_tracks(
    flight_uuid: Optional[UUID] = Query(
        None, description="Filter by flight UUID"),
    limit: int = Query(100, description="Maximum number of tracks to return"),
    offset: int = Query(0, description="Pagination offset"),
    order_by: str = Query("datetime", description="Field to order results by"),
    order_dir: str = Query("asc", description="Order direction (asc or desc)"),
    db: Session = Depends(get_db)
):
    """Get all scoring track points with optional filtering"""
    try:
        query = db.query(ScoringTracks)

        if flight_uuid:
            query = query.filter(ScoringTracks.flight_uuid == flight_uuid)

        # Handle ordering
        if order_dir.lower() == "desc":
            query = query.order_by(getattr(ScoringTracks, order_by).desc())
        else:
            query = query.order_by(getattr(ScoringTracks, order_by).asc())

        tracks = query.offset(offset).limit(limit).all()

        return tracks

    except Exception as e:
        logger.error(f"Error retrieving scoring tracks: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to retrieve scoring tracks")

# Get a single scoring track by ID


@router.get("/{track_id}", response_model=ScoringTrackResponse)
async def get_scoring_track(
    track_id: UUID,
    token_data: Dict = Depends(verify_tracking_token),
    db: Session = Depends(get_db)
):
    """Get a specific scoring track point by ID"""
    track = db.query(ScoringTracks).filter(
        ScoringTracks.id == track_id).first()

    if not track:
        raise HTTPException(status_code=404, detail="Scoring track not found")

    return track

# Update a scoring track


@router.put("/{track_id}", response_model=ScoringTrackResponse)
async def update_scoring_track(
    track_id: UUID,
    track_update: ScoringTrackUpdate,
    token_data: Dict = Depends(verify_tracking_token),
    db: Session = Depends(get_db)
):
    """Update a scoring track point"""
    try:
        db_track = db.query(ScoringTracks).filter(
            ScoringTracks.id == track_id).first()

        if not db_track:
            raise HTTPException(
                status_code=404, detail="Scoring track not found")

        update_data = track_update.model_dump(exclude_unset=True)

        # Handle spatial data separately if lat/lon are being updated
        if 'lat' in update_data or 'lon' in update_data:
            lat = update_data.get('lat', db_track.lat)
            lon = update_data.get('lon', db_track.lon)
            db_track.geom = ST_MakePoint(lon, lat)

            # Update the individual lat/lon columns
            if 'lat' in update_data:
                db_track.lat = lat
            if 'lon' in update_data:
                db_track.lon = lon

            # Remove lat/lon from update_data as we've handled them separately
            if 'lat' in update_data:
                del update_data['lat']
            if 'lon' in update_data:
                del update_data['lon']

        # Update remaining fields
        for key, value in update_data.items():
            setattr(db_track, key, value)

        db.commit()
        db.refresh(db_track)
        return db_track

    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Database error while updating scoring track: {str(e)}")
        raise HTTPException(
            status_code=500, detail="Failed to update scoring track")

    except Exception as e:
        logger.error(f"Error updating scoring track: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to update scoring track: {str(e)}")

# Delete a scoring track


@router.delete("/{track_id}", status_code=204)
async def delete_scoring_track(
    track_id: UUID,
    token_data: Dict = Depends(verify_tracking_token),
    db: Session = Depends(get_db)
):
    """Delete a scoring track point"""
    try:
        db_track = db.query(ScoringTracks).filter(
            ScoringTracks.id == track_id).first()

        if not db_track:
            raise HTTPException(
                status_code=404, detail="Scoring track not found")

        db.delete(db_track)
        db.commit()

        return Response(status_code=204)

    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Database error while deleting scoring track: {str(e)}")
        raise HTTPException(
            status_code=500, detail="Failed to delete scoring track")

    except Exception as e:
        logger.error(f"Error deleting scoring track: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to delete scoring track: {str(e)}")

# Batch create scoring tracks


@router.post("/batch", status_code=201, response_model=FlightTrackResponse)
async def create_scoring_tracks_batch(
    tracks: List[ScoringTrackCreate],
    token_data: Dict = Depends(verify_tracking_token),
    db: Session = Depends(get_db)
):
    """Insert multiple scoring track points at once"""
    try:
        if not tracks:
            raise HTTPException(
                status_code=400, detail="No tracks provided"
            )

        # All tracks must have the same flight_uuid
        flight_uuid = tracks[0].flight_uuid
        if not all(track.flight_uuid == flight_uuid for track in tracks):
            raise HTTPException(
                status_code=400, detail="All tracks must belong to the same flight"
            )

        # Verify flight_uuid exists
        flight = db.query(Flight).filter(Flight.id == flight_uuid).first()
        if not flight:
            raise HTTPException(
                status_code=404, detail=f"Flight with UUID {flight_uuid} not found"
            )

        db_tracks = []

        for track in tracks:
            # Create point geometry
            point_geom = func.ST_SetSRID(
                func.ST_MakePoint(track.lon, track.lat), 4326)

            db_track = ScoringTracks(
                **track.model_dump(exclude={"geom"}),
                geom=point_geom
            )
            db_tracks.append(db_track)

        db.add_all(db_tracks)

        # Update the flight's total points
        flight.total_points = (flight.total_points or 0) + len(db_tracks)

        # Track first and last point times
        date_times = sorted([track.date_time for track in tracks])
        if date_times:
            if not flight.start_time or date_times[0] < flight.start_time:
                flight.start_time = date_times[0]
            if not flight.end_time or date_times[-1] > flight.end_time:
                flight.end_time = date_times[-1]

        db.commit()

        # Create response model
        response = FlightTrackResponse(
            flight_uuid=flight.id,
            flight_id=flight.flight_id,
            pilot_id=flight.pilot_id,
            pilot_name=flight.pilot_name,
            total_points=flight.total_points or len(db_tracks),
            first_point_time=flight.start_time,
            last_point_time=flight.end_time,
            tracks=db_tracks
        )

        return response

    except SQLAlchemyError as e:
        db.rollback()
        logger.error(
            f"Database error while batch creating scoring tracks: {str(e)}")
        raise HTTPException(
            status_code=500, detail="Failed to create scoring tracks")

    except Exception as e:
        logger.error(f"Error batch creating scoring tracks: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to create scoring tracks: {str(e)}")

# Get scoring tracks by flight ID


@router.get("/flight/{flight_id}")
async def get_scoring_tracks_by_flight(
    flight_id: str,
    limit: int = Query(1000, description="Maximum number of tracks to return"),
    offset: int = Query(0, description="Pagination offset"),
    token_data: Dict = Depends(verify_tracking_token),
    db: Session = Depends(get_db)
):
    """Get scoring track points for a specific flight ID"""
    try:
        # First find the flight UUID from flight_id
        flight = db.query(Flight).filter(Flight.flight_id == flight_id).first()

        if not flight:
            raise HTTPException(
                status_code=404, detail=f"Flight with ID {flight_id} not found")

        # Get scoring tracks for this flight
        query = db.query(ScoringTracks).filter(
            ScoringTracks.flight_uuid == flight.id
        ).order_by(ScoringTracks.datetime)

        total_count = query.count()

        # Apply pagination
        tracks = query.offset(offset).limit(limit).all()

        # Format the response
        result = []
        for track in tracks:
            # Get GeoJSON representation of the point
            geom_query = db.query(func.ST_AsGeoJSON(track.geom)).scalar()
            geojson = None
            if geom_query:
                import json
                geojson = json.loads(geom_query)

            track_data = {
                "id": str(track.id),
                "datetime": track.datetime.isoformat(),
                "lat": float(track.lat),
                "lon": float(track.lon),
                "gps_alt": float(track.gps_alt),
                "time": track.time,
                "validity": track.validity,
                "pressure_alt": float(track.pressure_alt) if track.pressure_alt else None,
                "LAD": track.LAD,
                "LOD": track.LOD,
                "speed": float(track.speed) if track.speed else None,
                "elevation": float(track.elevation) if track.elevation else None,
                "altitude_diff": float(track.altitude_diff) if track.altitude_diff else None,
                "altitude_diff_smooth": float(track.altitude_diff_smooth) if track.altitude_diff_smooth else None,
                "speed_smooth": float(track.speed_smooth) if track.speed_smooth else None,
                "takeoff_condition": track.takeoff_condition,
                "in_flight": track.in_flight,
                "geometry": geojson
            }
            result.append(track_data)

        return {
            "flight_id": flight_id,
            "flight_uuid": str(flight.id),
            "total_points": total_count,
            "returned_points": len(tracks),
            "tracks": result
        }

    except HTTPException:
        raise

    except Exception as e:
        logger.error(f"Error retrieving scoring tracks by flight ID: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to retrieve scoring tracks: {str(e)}")
