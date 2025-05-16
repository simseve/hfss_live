from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy.sql import func
import uuid
from database.models import ScoringTracks
from database.db_conf import get_db
from database.schemas import ScoringTrackBatchCreate, ScoringTrackBatchResponse, FlightDeleteResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.dialects.postgresql import insert
import logging
from aiohttp import ClientSession
from config import settings
from uuid import UUID
from sqlalchemy import text
import json

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




# @router.get("/track-preview/{flight_uuid}")
# async def get_track_preview(
#     flight_uuid: UUID,
#     width: int = Query(600, description="Width of the preview image in pixels"),
#     height: int = Query(400, description="Height of the preview image in pixels"),
#     color: str = Query("0x0000ff", description="Color of the track path in hex format"),
#     weight: int = Query(5, description="Weight/thickness of the track path"),
#     max_points: int = Query(1000, description="Maximum number of points to use in the polyline"),
#     credentials: HTTPAuthorizationCredentials = Security(security),
#     db: Session = Depends(get_db)
# ):
#     """
#     Generate a Google Static Maps preview URL for a flight track using the encoded polyline.
#     Also returns track statistics including distance, duration, speeds, and elevation data.
#     Includes location information for the start point of the flight.

#     Parameters:
#     - flight_uuid: UUID of the flight
#     - width: Width of the preview image (default: 600)
#     - height: Height of the preview image (default: 400)
#     - color: Color of the track path in hex format (default: 0x0000ff - blue)
#     - weight: Weight/thickness of the track path (default: 5)
#     - max_points: Maximum number of points to use (default: 1000, reduces URL length)
#     """
#     try:
#         # Verify token
#         token = credentials.credentials
#         try:
#             token_data = jwt.decode(
#                 token,
#                 settings.SECRET_KEY,
#                 algorithms=["HS256"],
#                 audience="api.hikeandfly.app",
#                 issuer="hikeandfly.app",
#                 verify=True
#             )

#             if not token_data.get("sub", "").startswith("contest:"):
#                 raise HTTPException(
#                     status_code=403,
#                     detail="Invalid token subject - must be contest-specific"
#                 )

#         except jwt.ExpiredSignatureError:
#             raise HTTPException(status_code=401, detail="Token expired")
#         except PyJWTError as e:
#             raise HTTPException(
#                 status_code=401, detail=f"Invalid token: {str(e)}")

#         # Get flight from database
#         flight = db.query(Flight).filter(
#             Flight.id == flight_uuid
#         ).first()

#         if not flight:
#             raise HTTPException(
#                 status_code=404,
#                 detail=f"Flight not found with UUID {flight_uuid}"
#             )

#         # Get the encoded polyline for the flight with simplification
#         if flight.source == 'live':
#             func_name = 'generate_live_track_linestring'
#             table_name = 'live_track_points'
#         else:  # source == 'upload'
#             func_name = 'generate_uploaded_track_linestring'
#             table_name = 'uploaded_track_points'

#         # First get track statistics using PostGIS - fixed query to handle elevation gain/loss
#         stats_query = f"""
#         WITH track AS (
#             SELECT 
#                 tp.datetime,
#                 tp.elevation,
#                 tp.geom
#             FROM {table_name} tp
#             WHERE tp.flight_uuid = '{flight_uuid}'
#             ORDER BY tp.datetime
#         ),
#         track_stats AS (
#             SELECT
#                 -- Distance in meters
#                 ST_Length(ST_MakeLine(geom)::geography) as distance,
#                 -- Time values
#                 MIN(datetime) as start_time,
#                 MAX(datetime) as end_time,
#                 -- Elevation values
#                 MIN(elevation) as min_elevation,
#                 MAX(elevation) as max_elevation,
#                 MAX(elevation) - MIN(elevation) as elevation_range
#             FROM track
#         ),
#         -- Handle elevation gain/loss without using window functions inside aggregates
#         track_with_prev AS (
#             SELECT
#                 datetime,
#                 elevation,
#                 LAG(elevation) OVER (ORDER BY datetime) as prev_elevation
#             FROM track
#         ),
#         elevation_changes AS (
#             SELECT
#                 SUM(CASE WHEN (elevation - prev_elevation) > 1 THEN (elevation - prev_elevation) ELSE 0 END) as elevation_gain,
#                 SUM(CASE WHEN (elevation - prev_elevation) < -1 THEN ABS(elevation - prev_elevation) ELSE 0 END) as elevation_loss
#             FROM track_with_prev
#             WHERE prev_elevation IS NOT NULL
#         )
#         SELECT
#             ts.distance,
#             ts.start_time,
#             ts.end_time,
#             EXTRACT(EPOCH FROM (ts.end_time - ts.start_time)) as duration_seconds,
#             ts.min_elevation,
#             ts.max_elevation,
#             ts.elevation_range,
#             ec.elevation_gain,
#             ec.elevation_loss,
#             -- Speed calculations
#             CASE
#                 WHEN EXTRACT(EPOCH FROM (ts.end_time - ts.start_time)) > 0
#                 THEN ts.distance / EXTRACT(EPOCH FROM (ts.end_time - ts.start_time))
#                 ELSE 0
#             END as avg_speed_m_s,
#             COUNT(*) as total_points
#         FROM track_stats ts, elevation_changes ec, track
#         GROUP BY 
#             ts.distance, ts.start_time, ts.end_time, ts.min_elevation, 
#             ts.max_elevation, ts.elevation_range, ec.elevation_gain, ec.elevation_loss;
#         """
        
#         stats_result = db.execute(text(stats_query)).fetchone()
        
#         # Use ST_SimplifyPreserveTopology to reduce the number of points
#         # This keeps the general shape but reduces the point count
#         query = f"""
#         WITH original AS (
#             SELECT {func_name}('{flight_uuid}'::uuid) AS geom
#         )
#         SELECT 
#             ST_NPoints(geom) as original_points,
#             CASE 
#                 -- If original has too many points, simplify to reduce size
#                 WHEN ST_NPoints(geom) > {max_points}
#                 THEN ST_AsEncodedPolyline(ST_SimplifyPreserveTopology(
#                     geom, 
#                     ST_Length(geom::geography) / (5000 * SQRT({max_points}))
#                 ))
#                 -- Otherwise use the original
#                 ELSE ST_AsEncodedPolyline(geom) 
#             END as encoded_polyline,
#             CASE 
#                 -- If original has too many points, get count after simplification
#                 WHEN ST_NPoints(geom) > {max_points}
#                 THEN ST_NPoints(ST_SimplifyPreserveTopology(
#                     geom, 
#                     ST_Length(geom::geography) / (5000 * SQRT({max_points}))
#                 ))
#                 -- Otherwise use original count
#                 ELSE ST_NPoints(geom) 
#             END as simplified_points
#         FROM original;
#         """

#         result = db.execute(text(query)).fetchone()

#         if not result or not result[1]:
#             return {
#                 "status": "error",
#                 "detail": "No track data available for this flight"
#             }

#         encoded_polyline = result[1]
#         original_points = result[0]
#         simplified_points = result[2]
        
#         # Check if the encoded polyline is still too large (> 6000 chars to be safe)
#         # If so, further simplify by sampling points
#         if len(encoded_polyline) > 6000:
#             # More aggressive simplification for very long tracks
#             simplify_factor = len(encoded_polyline) / 6000
#             query = f"""
#             WITH original AS (
#                 SELECT {func_name}('{flight_uuid}'::uuid) AS geom
#             )
#             SELECT 
#                 ST_AsEncodedPolyline(ST_SimplifyPreserveTopology(
#                     geom, 
#                     ST_Length(geom::geography) / (2000 * SQRT({max_points // 2}))
#                 )) as encoded_polyline
#             FROM original;
#             """
#             result = db.execute(text(query)).fetchone()
#             if result and result[0]:
#                 encoded_polyline = result[0]
            
#             # If still too large, create a bounding box preview instead
#             if len(encoded_polyline) > 6000:
#                 # Get bounding box and center point
#                 bbox_query = f"""
#                 SELECT 
#                     ST_XMin(ST_Envelope(geom)) as min_lon,
#                     ST_YMin(ST_Envelope(geom)) as min_lat,
#                     ST_XMax(ST_Envelope(geom)) as max_lon,
#                     ST_YMax(ST_Envelope(geom)) as max_lat,
#                     ST_X(ST_Centroid(geom)) as center_lon,
#                     ST_Y(ST_Centroid(geom)) as center_lat
#                 FROM (SELECT {func_name}('{flight_uuid}'::uuid) AS geom) AS track;
#                 """
#                 bbox_result = db.execute(text(bbox_query)).fetchone()
                
#                 if bbox_result:
#                     # Create a static map with the center point and appropriate zoom
#                     center_lat = bbox_result[4]
#                     center_lon = bbox_result[5]
                    
#                     # Create Google Static Maps URL with center point and appropriate zoom
#                     google_maps_preview_url = (
#                         f"https://maps.googleapis.com/maps/api/staticmap?"
#                         f"size={width}x{height}&center={center_lat},{center_lon}"
#                         f"&zoom=11"  # Default zoom level that shows reasonable area
#                         f"&markers=color:red|{center_lat},{center_lon}"
#                         f"&sensor=false"
#                         f"&key={settings.GOOGLE_MAPS_API_KEY}"
#                     )
                    
#                     return {
#                         "flight_id": flight.flight_id,
#                         "flight_uuid": str(flight.id),
#                         "preview_url": google_maps_preview_url,
#                         "source": flight.source,
#                         "note": "Track was too complex for detailed preview, showing center point only"
#                     }

#         # Create Google Static Maps URL with the encoded polyline
#         google_maps_preview_url = (
#             f"https://maps.googleapis.com/maps/api/staticmap?"
#             f"size={width}x{height}&path=color:{color}|weight:{weight}|enc:{encoded_polyline}"
#             f"&sensor=false"
#             f"&key={settings.GOOGLE_MAPS_API_KEY}"
#         )

#         # Get start location information using Google Geocoding API
#         start_location = {
#             "lat": float(flight.first_fix['lat']),
#             "lon": float(flight.first_fix['lon']),
#             "formatted_address": None,
#             "locality": None,
#             "administrative_area": None,
#             "country": None
#         }

#         try:
#             async with ClientSession() as session:
#                 url = f"https://maps.googleapis.com/maps/api/geocode/json?latlng={start_location['lat']},{start_location['lon']}&key={settings.GOOGLE_MAPS_API_KEY}"
#                 async with session.get(url) as response:
#                     if response.status == 200:
#                         data = await response.json()
#                         if data['results']:
#                             # Get the most relevant result (first one)
#                             result = data['results'][0]
#                             start_location["formatted_address"] = result['formatted_address']
                            
#                             # Extract specific address components
#                             for component in result['address_components']:
#                                 if 'locality' in component['types']:
#                                     start_location["locality"] = component['long_name']
#                                 elif 'administrative_area_level_1' in component['types']:
#                                     start_location["administrative_area"] = component['long_name']
#                                 elif 'country' in component['types']:
#                                     start_location["country"] = component['long_name']
#         except Exception as e:
#             logger.error(f"Error getting location data: {str(e)}")
#             # Continue even if geocoding fails

#         # Format flight statistics
#         stats = {}
#         if stats_result:
#             hours, remainder = divmod(int(stats_result.duration_seconds), 3600)
#             minutes, seconds = divmod(remainder, 60)
            
#             # Convert meters to kilometers
#             distance_km = float(stats_result.distance) / 1000 if stats_result.distance else 0
            
#             # Convert m/s to km/h
#             avg_speed_kmh = float(stats_result.avg_speed_m_s) * 3.6 if stats_result.avg_speed_m_s else 0
            
#             stats = {
#                 "distance": {
#                     "meters": round(float(stats_result.distance), 2) if stats_result.distance else 0,
#                     "kilometers": round(distance_km, 2)
#                 },
#                 "duration": {
#                     "seconds": int(stats_result.duration_seconds) if stats_result.duration_seconds else 0,
#                     "formatted": f"{hours:02d}:{minutes:02d}:{seconds:02d}"
#                 },
#                 "speed": {
#                     "avg_m_s": round(float(stats_result.avg_speed_m_s), 2) if stats_result.avg_speed_m_s else 0,
#                     "avg_km_h": round(avg_speed_kmh, 2)
#                 },
#                 "elevation": {
#                     "min": round(float(stats_result.min_elevation), 1) if stats_result.min_elevation is not None else None,
#                     "max": round(float(stats_result.max_elevation), 1) if stats_result.max_elevation is not None else None,
#                     "range": round(float(stats_result.elevation_range), 1) if stats_result.elevation_range is not None else None,
#                     "gain": round(float(stats_result.elevation_gain), 1) if stats_result.elevation_gain is not None else None,
#                     "loss": round(float(stats_result.elevation_loss), 1) if stats_result.elevation_loss is not None else None
#                 },
#                 "points": {
#                     "total": stats_result.total_points if hasattr(stats_result, 'total_points') else 0
#                 },
#                 "timestamps": {
#                     "start": stats_result.start_time.isoformat() if stats_result.start_time else None,
#                     "end": stats_result.end_time.isoformat() if stats_result.end_time else None
#                 }
#             }

#         return {
#             "flight_id": flight.flight_id,
#             "flight_uuid": str(flight.id),
#             "preview_url": google_maps_preview_url,
#             "source": flight.source,
#             "original_points": original_points,
#             "simplified_points": simplified_points,
#             "url_length": len(google_maps_preview_url),
#             "start_location": start_location,  # Added start location information
#             "stats": stats
#         }

#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.error(f"Error generating track preview: {str(e)}")
#         raise HTTPException(
#             status_code=500,
#             detail=f"Failed to generate track preview: {str(e)}"
#         )