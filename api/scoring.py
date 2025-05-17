from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session
import uuid
from database.models import ScoringTracks
from database.db_conf import get_db
from database.schemas import (
    ScoringTrackBatchCreate,
    ScoringTrackBatchResponse,
    FlightDeleteResponse,
    MVTRequest,
)
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.dialects.postgresql import insert
import logging
from aiohttp import ClientSession
from config import settings
from uuid import UUID
from sqlalchemy import text
import json
from typing import Optional, List

from datetime import datetime, time, timezone

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/batch", status_code=201, response_model=ScoringTrackBatchResponse)
async def create_scoring_track_batch(
    track_batch: ScoringTrackBatchCreate,
    db: Session = Depends(get_db)
):
    """Insert a batch of scoring track points efficiently and create a new flight with generated UUID"""
    try:
        # Validate that we have track points to process
        if not track_batch.tracks:
            raise HTTPException(
                status_code=400, detail="No track points provided in the batch"
            )

        # Log batch size for monitoring
        logger.info(
            # Generate a new flight UUID
            f"Processing batch with {len(track_batch.tracks)} track points")
        flight_uuid = uuid.uuid4()

        logger.info(
            f"Created new flight UUID {flight_uuid} for scoring tracks")

        # Create track objects for bulk insertion with optimized geometry handling
        track_objects = []
        points_to_add = len(track_batch.tracks)

        # Process all tracks in the batch
        for track in track_batch.tracks:
            # Set the flight_uuid to our new generated UUID for all tracks
            track.flight_uuid = flight_uuid

            # Create track object as a dictionary for SQLAlchemy Core insert
            track_data = track.model_dump(exclude={"geom"})
            track_objects.append(track_data)

        # Bulk insert all track objects if we have any, ignoring conflicts
        if track_objects:
            # Use insert().on_conflict_do_nothing() for more efficient handling of duplicates
            stmt = insert(ScoringTracks).on_conflict_do_nothing(
                index_elements=['flight_uuid', 'date_time', 'lat', 'lon']
            )
            db.execute(stmt, track_objects)

            # Commit once after all operations
            db.commit()

            return ScoringTrackBatchResponse(
                flight_uuid=flight_uuid,
                points_added=points_to_add
            )
        else:
            # Still commit the flight even if no track points
            db.commit()

            return ScoringTrackBatchResponse(
                flight_uuid=flight_uuid,
                points_added=0
            )

    except SQLAlchemyError as e:
        db.rollback()
        # Log the error with more details
        logger.error(
            f"Database error while creating scoring track batch: {str(e)}")
        # Return a more specific error message based on the exception type
        if "duplicate key" in str(e).lower() or "unique constraint" in str(e).lower():
            raise HTTPException(
                status_code=409,
                detail="Duplicate track points detected in the batch. Points with the same flight_uuid, datetime, latitude and longitude already exist."
            )
        elif "foreign key" in str(e).lower():
            raise HTTPException(
                status_code=400,
                detail=f"Foreign key constraint failed. Flight UUID {flight_uuid} may not exist"
            )
        else:
            raise HTTPException(
                status_code=500,
                detail="Database error while creating scoring track batch"
            )

    except HTTPException:
        # Re-raise HTTP exceptions as they already have proper status codes and details
        raise

    except Exception as e:
        # Handle any other exceptions
        logger.error(
            f"Unexpected error creating scoring track batch: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred while processing track batch"
        )


@router.delete("/flight/{flight_uuid}", status_code=200, response_model=FlightDeleteResponse)
async def delete_flight_tracks(
    flight_uuid: uuid.UUID,
    db: Session = Depends(get_db)
):
    """Delete all scoring tracks associated with a specific flight UUID"""
    try:
        # Log the deletion attempt
        logger.info(
            f"Attempting to delete tracks for flight UUID: {flight_uuid}")

        # First count the number of records to be deleted for the response
        count = db.query(ScoringTracks).filter(
            ScoringTracks.flight_uuid == flight_uuid
        ).count()

        # If no records were found, return a 404
        if count == 0:
            raise HTTPException(
                status_code=404,
                detail=f"No tracks found for flight UUID: {flight_uuid}"
            )

        # Query to delete all tracks with the specified flight_uuid
        result = db.query(ScoringTracks).filter(
            ScoringTracks.flight_uuid == flight_uuid
        ).delete(synchronize_session=False)

        # Commit the transaction
        db.commit()

        # Log successful deletion
        logger.info(
            f"Successfully deleted {result} tracks for flight UUID: {flight_uuid}")

        # Return success response
        return FlightDeleteResponse(flight_uuid=str(flight_uuid), points_deleted=result)

    except SQLAlchemyError as e:
        # Roll back the transaction on database error
        db.rollback()

        # Log the error
        logger.error(f"Database error while deleting flight tracks: {str(e)}")

        # Return appropriate error response
        raise HTTPException(
            status_code=500,
            detail=f"Database error while deleting flight tracks: {str(e)}"
        )

    except HTTPException:
        # Re-raise HTTP exceptions as they already have proper status codes and details
        raise

    except Exception as e:
        # Handle any other exceptions
        logger.error(
            f"Unexpected error deleting flight tracks: {str(e)}", exc_info=True)

        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred while deleting flight tracks"
        )


@router.put("/flight/{flight_uuid}", status_code=200, response_model=ScoringTrackBatchResponse)
async def update_flight_tracks(
    flight_uuid: uuid.UUID,
    track_batch: ScoringTrackBatchCreate,
    db: Session = Depends(get_db)
):
    """
    Update all scoring tracks for a specific flight UUID.
    First deletes all existing track points, then adds new ones while preserving the flight UUID.

    Parameters:
    - flight_uuid: UUID of the flight to update
    - track_batch: New batch of track points to add
    """
    try:
        # Log the update attempt
        logger.info(
            f"Attempting to update tracks for flight UUID: {flight_uuid}")

        # Validate that we have track points to process
        if not track_batch.tracks:
            raise HTTPException(
                status_code=400, detail="No track points provided for update"
            )

        # Begin transaction
        try:
            # Step 1: Check if flight exists
            count = db.query(ScoringTracks).filter(
                ScoringTracks.flight_uuid == flight_uuid
            ).count()

            # If no records were found, return a 404
            if count == 0:
                raise HTTPException(
                    status_code=404,
                    detail=f"No tracks found for flight UUID: {flight_uuid}"
                )

            # Step 2: Delete all existing track points for this flight
            result = db.query(ScoringTracks).filter(
                ScoringTracks.flight_uuid == flight_uuid
            ).delete(synchronize_session=False)

            logger.info(
                f"Deleted {result} existing track points for flight UUID: {flight_uuid}")

            # Step 3: Insert new track points while preserving the flight UUID
            track_objects = []
            points_to_add = len(track_batch.tracks)

            # Process all tracks in the batch
            for track in track_batch.tracks:
                # Set the flight_uuid to the existing UUID for all tracks
                track.flight_uuid = flight_uuid

                # Create track object as a dictionary for SQLAlchemy Core insert
                track_data = track.model_dump(exclude={"geom"})
                track_objects.append(track_data)

            # Bulk insert all track objects if we have any
            if track_objects:
                # Use insert().on_conflict_do_nothing() for more efficient handling of duplicates
                stmt = insert(ScoringTracks).on_conflict_do_nothing(
                    index_elements=['flight_uuid', 'date_time', 'lat', 'lon']
                )
                db.execute(stmt, track_objects)

            # Commit the transaction
            db.commit()

            # Log successful update
            logger.info(
                f"Successfully updated flight {flight_uuid}: deleted {result} old points, added {points_to_add} new points")

            # Return success response
            return ScoringTrackBatchResponse(
                flight_uuid=flight_uuid,
                points_added=points_to_add
            )

        except SQLAlchemyError as e:
            # Rollback in case of error
            db.rollback()
            raise e

    except SQLAlchemyError as e:
        # Log the error with more details
        logger.error(
            f"Database error while updating flight tracks: {str(e)}")
        # Return a more specific error message based on the exception type
        if "duplicate key" in str(e).lower() or "unique constraint" in str(e).lower():
            raise HTTPException(
                status_code=409,
                detail="Duplicate track points detected in the batch. Points with the same flight_uuid, datetime, latitude and longitude already exist."
            )
        elif "foreign key" in str(e).lower():
            raise HTTPException(
                status_code=400,
                detail=f"Foreign key constraint failed. Flight UUID {flight_uuid} may not exist"
            )
        else:
            raise HTTPException(
                status_code=500,
                detail=f"Database error while updating flight tracks: {str(e)}"
            )

    except HTTPException:
        # Re-raise HTTP exceptions as they already have proper status codes and details
        raise

    except Exception as e:
        # Handle any other exceptions
        logger.error(
            f"Unexpected error updating flight tracks: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred while updating flight tracks"
        )


@router.get("/track-line/{flight_uuid}")
async def get_track_linestring_uuid(
    flight_uuid: UUID,
    simplify: bool = Query(
        False, description="Whether to simplify the track geometry. If true, provides sampled coordinates for better performance."),
    db: Session = Depends(get_db)
):
    """
    Return the complete flight track as a GeoJSON LineString.
    Uses the PostGIS functions to generate the geometry.

    Parameters:
    - flight_uuid: UUID of the flight
    - simplify: Optional parameter to simplify the line geometry (useful for large tracks)
    """
    try:
        func_name = 'generate_scoring_track_linestring'

        # Handle simplification
        if simplify:
            # Use a default moderate value for simplification
            simplify_value = 0.0001

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
                    "flight_uuid": str(flight_uuid)
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
                "flight_uuid": str(flight_uuid),
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

        func_name = 'generate_scoring_track_linestring'
        table_name = 'scoring_tracks'

        # First get track statistics using PostGIS - fixed query to handle elevation gain/loss
        stats_query = f"""
        WITH track AS (
            SELECT 
                tp.date_time,
                tp.elevation,
                tp.geom
            FROM {table_name} tp
            WHERE tp.flight_uuid = '{flight_uuid}'
            ORDER BY tp.date_time
        ),
        track_stats AS (
            SELECT
                -- Distance in meters
                ST_Length(ST_MakeLine(geom)::geography) as distance,
                -- Time values
                MIN(date_time) as start_time,
                MAX(date_time) as end_time,
                -- Elevation values
                MIN(elevation) as min_elevation,
                MAX(elevation) as max_elevation,
                MAX(elevation) - MIN(elevation) as elevation_range
            FROM track
        ),
        -- Handle elevation gain/loss without using window functions inside aggregates
        track_with_prev AS (
            SELECT
                date_time,
                elevation,
                LAG(elevation) OVER (ORDER BY date_time) as prev_elevation
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

        # Use ST_SimplifyPreserveTopology to reduce the number of points
        # This keeps the general shape but reduces the point count
        query = f"""
        WITH original AS (
            SELECT {func_name}('{flight_uuid}'::uuid) AS geom
        )
        SELECT 
            ST_NPoints(geom) as original_points,
            CASE 
                -- If original has too many points, simplify to reduce size
                WHEN ST_NPoints(geom) > {max_points}
                THEN ST_AsEncodedPolyline(ST_SimplifyPreserveTopology(
                    geom, 
                    ST_Length(geom::geography) / (5000 * SQRT({max_points}))
                ))
                -- Otherwise use the original
                ELSE ST_AsEncodedPolyline(geom) 
            END as encoded_polyline,
            CASE 
                -- If original has too many points, get count after simplification
                WHEN ST_NPoints(geom) > {max_points}
                THEN ST_NPoints(ST_SimplifyPreserveTopology(
                    geom, 
                    ST_Length(geom::geography) / (5000 * SQRT({max_points}))
                ))
                -- Otherwise use original count
                ELSE ST_NPoints(geom) 
            END as simplified_points
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

        # Check if the encoded polyline is still too large (> 6000 chars to be safe)
        # If so, further simplify by sampling points
        if len(encoded_polyline) > 6000:
            # More aggressive simplification for very long tracks
            simplify_factor = len(encoded_polyline) / 6000
            query = f"""
            WITH original AS (
                SELECT {func_name}('{flight_uuid}'::uuid) AS geom
            )
            SELECT 
                ST_AsEncodedPolyline(ST_SimplifyPreserveTopology(
                    geom, 
                    ST_Length(geom::geography) / (2000 * SQRT({max_points // 2}))
                )) as encoded_polyline
            FROM original;
            """
            result = db.execute(text(query)).fetchone()
            if result and result[0]:
                encoded_polyline = result[0]

            # If still too large, create a bounding box preview instead
            if len(encoded_polyline) > 6000:
                # Get bounding box and center point
                bbox_query = f"""
                SELECT 
                    ST_XMin(ST_Envelope(geom)) as min_lon,
                    ST_YMin(ST_Envelope(geom)) as min_lat,
                    ST_XMax(ST_Envelope(geom)) as max_lon,
                    ST_YMax(ST_Envelope(geom)) as max_lat,
                    ST_X(ST_Centroid(geom)) as center_lon,
                    ST_Y(ST_Centroid(geom)) as center_lat
                FROM (SELECT {func_name}('{flight_uuid}'::uuid) AS geom) AS track;
                """
                bbox_result = db.execute(text(bbox_query)).fetchone()

                if bbox_result:
                    # Create a static map with the center point and appropriate zoom
                    center_lat = bbox_result[4]
                    center_lon = bbox_result[5]

                    # Create Google Static Maps URL with center point and appropriate zoom
                    google_maps_preview_url = (
                        f"https://maps.googleapis.com/maps/api/staticmap?"
                        f"size={width}x{height}&center={center_lat},{center_lon}"
                        f"&zoom=11"  # Default zoom level that shows reasonable area
                        f"&markers=color:red|{center_lat},{center_lon}"
                        f"&sensor=false"
                        f"&key={settings.GOOGLE_MAPS_API_KEY}"
                    )

                    return {
                        "flight_uuid": str(flight_uuid),
                        "preview_url": google_maps_preview_url,
                        "note": "Track was too complex for detailed preview, showing center point only"
                    }

        # Create Google Static Maps URL with the encoded polyline
        google_maps_preview_url = (
            f"https://maps.googleapis.com/maps/api/staticmap?"
            f"size={width}x{height}&path=color:{color}|weight:{weight}|enc:{encoded_polyline}"
            f"&sensor=false"
            f"&key={settings.GOOGLE_MAPS_API_KEY}"
        )

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
            "flight_uuid": str(flight_uuid),
            "preview_url": google_maps_preview_url,
            "original_points": original_points,
            "simplified_points": simplified_points,
            "url_length": len(google_maps_preview_url),
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


@router.get("/flight/{flight_uuid}/points", status_code=200)
async def get_flight_points(
    flight_uuid: UUID,
    format: str = Query(
        "default", description="Response format: 'default' or 'geojson'"),
    db: Session = Depends(get_db)
):
    """
    Retrieve all tracking points for a specific flight UUID.

    Parameters:
    - flight_uuid: UUID of the flight
    - format: Response format (default or geojson)

    Returns:
    - All flight track points in either default or GeoJSON format
    """
    try:
        # Log the request
        logger.info(f"Fetching points for flight UUID: {flight_uuid}")

        # Query to get all track points for the flight
        track_points = db.query(ScoringTracks).filter(
            ScoringTracks.flight_uuid == flight_uuid
        ).order_by(ScoringTracks.date_time).all()

        # If no points were found, return a 404
        if len(track_points) == 0:
            raise HTTPException(
                status_code=404,
                detail=f"No track points found for flight UUID: {flight_uuid}"
            )

        points_count = len(track_points)
        logger.info(
            f"Found {points_count} track points for flight UUID: {flight_uuid}")

        # Check if GeoJSON format is requested
        if format.lower() == "geojson":
            # Create GeoJSON FeatureCollection with individual point features
            features = []

            # Track metadata for properties
            start_time = track_points[0].date_time if track_points else None
            end_time = track_points[-1].date_time if track_points else None

            for point in track_points:
                # Use shorter 'dt' property for timestamp to optimize size
                dt = point.date_time.isoformat() if point.date_time else None

                # Create GeoJSON Feature for each point
                feature = {
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [point.lon, point.lat, point.gps_alt]
                    },
                    "properties": {
                        "dt": dt,  # Shorter key for date_time
                        "speed": point.speed,
                        "elevation": point.elevation,
                        "altitude_diff": point.altitude_diff,
                        "pressure_alt": point.pressure_alt,
                        "speed_smooth": point.speed_smooth,
                        "altitude_diff_smooth": point.altitude_diff_smooth,
                        "takeoff_condition": point.takeoff_condition,
                        "in_flight": point.in_flight
                    }
                }
                features.append(feature)

            # Create the GeoJSON response with all point features and metadata at the top level
            geojson_response = {
                "type": "FeatureCollection",
                "features": features,
                "properties": {
                    "flight_uuid": str(flight_uuid),
                    "points_count": points_count,
                    "start_time": start_time.isoformat() if start_time else None,
                    "end_time": end_time.isoformat() if end_time else None
                }
            }

            return geojson_response
        else:
            # Return in default format
            from database.schemas import FlightPointsResponse, GeoJSONTrackPoint

            # Convert SQLAlchemy objects to Pydantic models
            track_points_data = []
            for point in track_points:
                track_point = GeoJSONTrackPoint(
                    date_time=point.date_time,
                    lat=point.lat,
                    lon=point.lon,
                    gps_alt=point.gps_alt,
                    time=point.time,
                    speed=point.speed,
                    elevation=point.elevation,
                    altitude_diff=point.altitude_diff,
                    pressure_alt=point.pressure_alt,
                    speed_smooth=point.speed_smooth,
                    altitude_diff_smooth=point.altitude_diff_smooth,
                    takeoff_condition=point.takeoff_condition,
                    in_flight=point.in_flight
                )
                track_points_data.append(track_point)

            # Return the response with all points
            return FlightPointsResponse(
                flight_uuid=flight_uuid,
                points_count=points_count,
                track_points=track_points_data
            )

    except HTTPException:
        # Re-raise HTTP exceptions as they already have proper status codes and details
        raise

    except SQLAlchemyError as e:
        # Log the error
        logger.error(f"Database error while fetching flight points: {str(e)}")

        # Return appropriate error response
        raise HTTPException(
            status_code=500,
            detail=f"Database error while fetching flight points: {str(e)}"
        )

    except Exception as e:
        # Handle any other exceptions
        logger.error(
            f"Unexpected error fetching flight points: {str(e)}", exc_info=True)

        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred while fetching flight points"
        )


@router.post("/postgis-mvt/daily/{z}/{x}/{y}")
async def get_daily_tracks_tile(
    z: int,
    x: int,
    y: int,
    request: MVTRequest,
    db: Session = Depends(get_db)
):
    """
    Serve vector tiles for all tracks from today for a specific race.
    Returns track points and lines with different colors per pilot.

    Parameters:
    - z/x/y: Tile coordinates
    - request: MVTRequest containing flight UUIDs to include in the tile
    """
    try:
        # Log the request
        logger.info(
            f"MVT request received for z={z}, x={x}, y={y} with {len(request.flight_uuids)} flight UUIDs")
        if not request.flight_uuids:
            # No flights found, return empty tile
            logger.warning("No flight UUIDs provided, returning empty tile")
            return Response(content=b"", media_type="application/x-protobuf")

        # Format UUIDs as a string list for the SQL query
        # Convert each UUID to string before joining
        flight_uuids_str = "', '".join(str(uuid)
                                       for uuid in request.flight_uuids)
        if flight_uuids_str:
            flight_uuids_str = f"('{flight_uuids_str}')"
            logger.info(f"Formatted UUIDs string: {flight_uuids_str}")
        else:
            # Use NULL to ensure valid SQL when list is empty
            flight_uuids_str = "(NULL)"

        # SQL query using ST_AsMVT
        # This generates MVT tiles with both points and lines for all flights
        query = f"""
        WITH 
        bounds AS (
            SELECT ST_TileEnvelope({z}, {x}, {y}) AS geom
        ),
        -- Assign colors to flights based on their UUID for consistent coloring
        flights_colors AS (
            SELECT 
                DISTINCT flight_uuid,
                -- Use hash of flight_uuid for color assignment
                (('x' || substr(md5(flight_uuid::text), 1, 6))::bit(24)::int % 10) as color_index
            FROM scoring_tracks 
            WHERE flight_uuid::text IN {flight_uuids_str}
        ),
        -- First get all points with row numbers for sampling
        numbered_points AS (
            SELECT 
                ROW_NUMBER() OVER (PARTITION BY t.flight_uuid ORDER BY t.date_time) as point_num,
                t.*,
                fc.color_index
            FROM scoring_tracks t
            -- Join with the colors CTE to get consistent coloring
            LEFT JOIN flights_colors fc ON t.flight_uuid = fc.flight_uuid
            WHERE t.flight_uuid::text IN {flight_uuids_str}
            -- Apply basic coordinate validation regardless of zoom level to exclude bogus data
            AND t.lat BETWEEN -90 AND 90 
            AND t.lon BETWEEN -180 AND 180
        ),
        -- For each flight, find the last point to always include
        last_points AS (
            SELECT DISTINCT ON (flight_uuid) 
                *
            FROM numbered_points
            ORDER BY flight_uuid, date_time DESC
        ),
        -- Select and filter points within this tile - improved filtering for different zoom levels
        filtered_points AS (
            SELECT 
                np.point_num as id,
                ST_SetSRID(ST_MakePoint(np.lon, np.lat, COALESCE(np.gps_alt, 0)), 4326) as geom,
                np.gps_alt as elevation,
                np.date_time as datetime,
                np.lat,
                np.lon,
                np.flight_uuid,
                np.color_index
            FROM numbered_points np
            WHERE 1=1
            -- Apply appropriate spatial filtering based on zoom level
            {
            "" if z == 0 else  # No spatial filtering for level 0
            "AND (np.lat BETWEEN -85 AND 85 AND np.lon BETWEEN -180 AND 180)" if z <= 2 else
            "AND ST_Intersects(ST_Transform(ST_SetSRID(ST_MakePoint(np.lon, np.lat), 4326), 3857), (SELECT geom FROM bounds))"
        }
            -- Apply sampling based on zoom level and point number
            AND (
                {
            "1=1" if z == 0 else  # For zoom level 0, include ALL points for proper lines
            "np.point_num % 60 = 0" if z < 3 else
            "np.point_num % 30 = 0" if z < 7 else
            "np.point_num % 10 = 0" if z < 10 else
            "1=1"  # Include all points for high zoom levels
        }
                -- Always include the last point of each flight
                OR EXISTS (
                    SELECT 1 FROM last_points lp 
                    WHERE lp.flight_uuid = np.flight_uuid AND lp.date_time = np.date_time
                )
            )
            ORDER BY np.flight_uuid, np.date_time
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
                fp.flight_uuid::text as flight_uuid,
                fp.color_index
            FROM filtered_points fp
        ),
        -- First group points by flight to form lines
        flight_lines AS (
            SELECT 
                fp.flight_uuid,
                fp.color_index,
                ST_MakeLine(fp.geom ORDER BY fp.datetime) AS line_geom,
                count(fp.id) as point_count,
                min(fp.datetime) as start_time,
                max(fp.datetime) as end_time
            FROM filtered_points fp
            GROUP BY fp.flight_uuid, fp.color_index
            HAVING count(fp.id) > 1  -- Ensure we have at least 2 points to form a valid line
        ),
        -- Then create the MVT geometries for the lines
        line_data AS (
            SELECT 
                ST_AsMVTGeom(
                    ST_Transform(fl.line_geom, 3857),
                    (SELECT geom FROM bounds),
                    4096,
                    256,
                    true
                ) AS geom,
                fl.flight_uuid::text as flight_uuid,
                fl.color_index,
                fl.point_count,
                fl.start_time,
                fl.end_time
            FROM flight_lines fl
            WHERE fl.line_geom IS NOT NULL
        )
        -- Final SELECT statement to generate MVT - using a better approach for empty results
        SELECT 
            (
                SELECT COALESCE(
                    (SELECT ST_AsMVT(l.*, 'track_lines') FROM line_data l),
                    ''
                )
            ) || 
            (
                SELECT COALESCE(
                    (SELECT ST_AsMVT(p.*, 'track_points') FROM point_mvt p),
                    ''
                )
            ) AS mvt
        """

        # Add a debug query to check if we have any points for these UUIDs
        debug_query = f"""
        SELECT COUNT(*) FROM scoring_tracks WHERE flight_uuid::text IN {flight_uuids_str};
        """
        debug_result = db.execute(text(debug_query)).fetchone()
        point_count = debug_result[0] if debug_result else 0
        logger.info(
            f"Found {point_count} points for the requested flight UUIDs")

        # Add a debug query to check if points are within the tile bounds
        if point_count > 0:
            bounds_query = f"""
            WITH bounds AS (SELECT ST_TileEnvelope({z}, {x}, {y}) AS geom)
            SELECT COUNT(*) FROM scoring_tracks t, bounds b 
            WHERE flight_uuid::text IN {flight_uuids_str}
            AND ST_Intersects(
                ST_Transform(ST_SetSRID(ST_MakePoint(t.lon, t.lat), 4326), 3857), 
                b.geom
            );
            """
            bounds_result = db.execute(text(bounds_query)).fetchone()
            bounds_count = bounds_result[0] if bounds_result else 0
            logger.info(
                f"Found {bounds_count} points within the requested tile bounds")

        try:
            # Execute the query and get the tile with better error handling
            result = db.execute(text(query)).fetchone()

            # Add more detailed diagnostic logging for points and lines

            # Add a check specifically for line generation issues
            line_check_query = f"""
            WITH 
            bounds AS (SELECT ST_TileEnvelope({z}, {x}, {y}) AS geom),
            -- Use same numbered_points CTE as the main query
            numbered_points AS (
                SELECT 
                    ROW_NUMBER() OVER (PARTITION BY t.flight_uuid ORDER BY t.date_time) as point_num,
                    t.*
                FROM scoring_tracks t
                WHERE t.flight_uuid::text IN {flight_uuids_str}
                AND t.lat BETWEEN -90 AND 90 
                AND t.lon BETWEEN -180 AND 180
            ),
            -- Sample for different zoom levels - same logic as main query
            sampled_points AS (
                SELECT 
                    np.flight_uuid,
                    ST_SetSRID(ST_MakePoint(np.lon, np.lat), 4326) as geom,
                    np.date_time
                FROM numbered_points np
                WHERE (
                    {
                "1=1" if z == 0 else  # For zoom level 0, include ALL points for proper lines
                "np.point_num % 60 = 0" if z < 3 else
                "np.point_num % 30 = 0" if z < 7 else
                "np.point_num % 10 = 0" if z < 10 else
                "1=1"  # Include all points for high zoom levels
            }
                )
            ),
            -- Group by flight to check line formation
            line_formation AS (
                SELECT 
                    flight_uuid,
                    ST_NPoints(ST_MakeLine(geom ORDER BY date_time)) as line_points,
                    COUNT(*) as num_points
                FROM sampled_points 
                GROUP BY flight_uuid
            )
            SELECT 
                COUNT(*) as flights_with_lines,
                SUM(CASE WHEN line_points >= 2 THEN 1 ELSE 0 END) as valid_lines,
                AVG(line_points) as avg_points_per_line,
                MAX(line_points) as max_points_in_line
            FROM line_formation
            WHERE num_points > 1;
            """

            try:
                line_check_result = db.execute(
                    text(line_check_query)).fetchone()
                if line_check_result:
                    logger.info(
                        f"Line diagnostic: {line_check_result[0]} flights with {line_check_result[1]} valid lines, " +
                        f"avg {int(line_check_result[2]) if line_check_result[2] else 0} points/line, " +
                        f"max {line_check_result[3]} points in a line"
                    )
            except Exception as e:
                logger.warning(f"Line diagnostic query failed: {str(e)}")

            # Run a simplified query to check if points are being properly filtered
            check_filtered_points_query = f"""
            WITH 
            bounds AS (SELECT ST_TileEnvelope({z}, {x}, {y}) AS geom),
            -- First get all points with row numbers for sampling
            numbered_points AS (
                SELECT 
                    ROW_NUMBER() OVER (PARTITION BY t.flight_uuid ORDER BY t.date_time) as point_num,
                    t.*
                FROM scoring_tracks t
                WHERE t.flight_uuid::text IN {flight_uuids_str}
                -- Apply basic coordinate validation regardless of zoom level
                AND t.lat BETWEEN -90 AND 90 
                AND t.lon BETWEEN -180 AND 180
            ),
            -- For each flight, find the last point to always include
            last_points AS (
                SELECT DISTINCT ON (flight_uuid) 
                    *
                FROM numbered_points
                ORDER BY flight_uuid, date_time DESC
            ),
            -- Apply the same filtering as the main query
            filtered_check AS (
                SELECT COUNT(*) as filtered_count
                FROM numbered_points np
                WHERE 1=1
                -- Apply appropriate spatial filtering based on zoom level
                {
                "" if z == 0 else  # No spatial filtering for level 0
                "AND (np.lat BETWEEN -85 AND 85 AND np.lon BETWEEN -180 AND 180)" if z <= 2 else
                "AND ST_Intersects(ST_Transform(ST_SetSRID(ST_MakePoint(np.lon, np.lat), 4326), 3857), (SELECT geom FROM bounds))"
            }
                -- Apply sampling based on zoom level and point number
                AND (
                    {
                "1=1" if z == 0 else  # For zoom level 0, include ALL points for proper lines
                "np.point_num % 60 = 0" if z < 3 else
                "np.point_num % 30 = 0" if z < 7 else
                "np.point_num % 10 = 0" if z < 10 else
                "1=1"  # Include all points for high zoom levels
            }
                    -- Always include the last point of each flight
                    OR EXISTS (
                        SELECT 1 FROM last_points lp 
                        WHERE lp.flight_uuid = np.flight_uuid AND lp.date_time = np.date_time
                    )
                )
            )
            SELECT filtered_count FROM filtered_check;
            """
            filtered_check_result = db.execute(
                text(check_filtered_points_query)).fetchone()
            filtered_count = filtered_check_result[0] if filtered_check_result else 0

            logger.info(
                f"Diagnostic - Points after filtering: {filtered_count}")
            logger.info(
                f"Diagnostic - MVT result is {'present' if result and result[0] else 'missing'}")
            if result and result[0]:
                logger.info(
                    f"MVT result type: {type(result[0])}, size: {len(result[0])}")

        except Exception as e:
            logger.error(
                f"MVT generation or diagnostic queries failed: {str(e)}")
            # If the main query failed, return empty tile
            result = None

        # Create a simpler but more robust tile generation approach
        if result and result[0] is not None:
            # Always return the MVT tile as binary data, even if it's empty
            mvt_size = len(result[0])
            logger.info(
                f"Generated MVT tile successfully with size: {mvt_size} bytes")

            # Add debug info but don't block valid MVT returns
            if mvt_size > 0:
                logger.info(
                    f"MVT structure hex sample: {result[0][:20].hex()}")
            else:
                logger.warning("Empty MVT structure returned")

            return Response(content=result[0], media_type="application/x-protobuf")
        else:
            # Create a minimal valid MVT if the result is None
            logger.warning(
                "No MVT tile was generated, creating minimal empty MVT response")

            # Use a simple empty tile fallback query
            fallback_query = """
            WITH empty_table AS (
                SELECT NULL::geometry AS geom 
                WHERE false
            )
            SELECT ST_AsMVT(empty_table.*, 'empty_layer') FROM empty_table
            """
            try:
                fallback_result = db.execute(text(fallback_query)).fetchone()
                if fallback_result and fallback_result[0]:
                    logger.info("Returning fallback empty MVT structure")
                    return Response(content=fallback_result[0], media_type="application/x-protobuf")
            except Exception as e:
                logger.error(f"Failed to generate fallback MVT: {str(e)}")

            # Last resort: return empty content with proper content type
            return Response(content=b"", media_type="application/x-protobuf")

    except Exception as e:
        logger.error(f"Error generating daily tracks vector tile: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to generate daily tracks tile: {str(e)}")
