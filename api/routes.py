from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database.schemas import LiveTrackPointCreate, UploadedTrackPointCreate, FlightCreate, FlightResponse
from database.models import LiveTrackPoint, UploadedTrackPoint, Flight
from typing import List, Dict, Any
from database.db_conf import get_db
import logging
from datetime import datetime, timezone
from api.auth import verify_tracking_token


logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/live", status_code=202)
async def live_tracking(
    track_points: List[LiveTrackPointCreate],
    flight_id: str,
    db: Session = Depends(get_db),
    token_data: dict = Depends(verify_tracking_token)
):
    """Handle live tracking data updates from mobile devices"""
    try:
        pilot_id = token_data['pilot_id']
        race_id = token_data['race_id']

        logger.info(f"Received live tracking batch for flight {flight_id}")
        logger.info(f"Total points in batch: {len(track_points)}")

        # Check if flight exists
        flight = db.query(Flight).filter(Flight.flight_id == flight_id).first()
        
        if not flight:
            # Verify assignment (you'll need to implement this check based on your requirements)
            if not verify_assignment(db, race_id, pilot_id):
                raise HTTPException(status_code=404, detail="No valid assignment found")
            
            # Create new flight record
            flight = Flight(
                flight_id=flight_id,
                race_id=race_id,
                pilot_id=pilot_id,
                # assignment_id=get_assignment_id(db, race_id, pilot_id),  # Implement this helper
                created_at=datetime.now(timezone.utc),
                type='live'
            )
            db.add(flight)

        # Convert track points to TimescaleDB format
        timescale_points = [
            LiveTrackPoint(
                flight_id=flight_id,
                datetime=point.datetime,
                lat=point.lat,
                lon=point.lon,
                elevation=point.elevation,
                speed=point.speed
            )
            for point in track_points
        ]
        
        # Bulk insert points
        db.bulk_save_objects(timescale_points)
        db.commit()
        
        return {
            'success': True,
            'message': f'Live tracking data processed ({len(track_points)} points)',
            'flight_id': flight_id
        }
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error processing live tracking data: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to process tracking data")



@router.post("/upload", status_code=202, response_model=FlightResponse)
async def upload_track(
    track_points: List[UploadedTrackPointCreate],
    flight_id: str,
    metadata: Dict[str, Any] = {},
    db: Session = Depends(get_db),
    token_data: dict = Depends(verify_tracking_token)
):
    """Handle complete track upload from mobile devices"""
    try:
        pilot_id = token_data['pilot_id']
        race_id = token_data['race_id']

        # Add start and end times to metadata
        if track_points:
            metadata.update({
                'total_points': len(track_points)
            })

        logger.info(f"Received track upload from pilot {pilot_id} for race {race_id}")
        logger.info(f"Total points: {len(track_points)}")

        # Verify assignment
        if not verify_assignment(db, race_id, pilot_id):
            raise HTTPException(status_code=404, detail="No valid assignment found")

        # Create or update flight record
        flight = db.query(Flight).filter(Flight.flight_id == flight_id).first()
        if flight:
            # Update existing flight
            flight.metadata = metadata
            flight.start_time = track_points[0].datetime if track_points else None
            flight.end_time = track_points[-1].datetime if track_points else None
            flight.total_points = len(track_points)
        else:
            # Create new flight
            flight = Flight(
                flight_id=flight_id,
                race_id=race_id,
                pilot_id=pilot_id,
                created_at=datetime.now(timezone.utc),
                type='upload',
                metadata=metadata,
                start_time=track_points[0].datetime if track_points else None,
                end_time=track_points[-1].datetime if track_points else None,
                total_points=len(track_points)
            )
            db.add(flight)

        # Convert and store track points
        timescale_points = [
            UploadedTrackPoint(
                flight_id=flight_id,
                datetime=point.datetime,
                lat=point.lat,
                lon=point.lon,
                elevation=point.elevation,
                speed=point.speed
            )
            for point in track_points
        ]
        
        db.bulk_save_objects(timescale_points)
        db.commit()

        return flight
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error processing track upload: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to process track data")




# Helper functions to implement
def verify_assignment(db: Session, race_id: str, pilot_id: str) -> bool:
    """Verify that a valid assignment exists for the given race and pilot"""
    # Implement your assignment verification logic here
    pass




        
# @tracking_blueprint.route('/points/<flight_id>', methods=['GET'])
# def get_flight_points(flight_id):
#     """
#     Get all tracking points for a specific flight up to the current moment.
#     For admin/testing use only.
#     """
#     try:
#         # Get collection type from request body
#         collection_type = request.args.get('type', 'upload')  # Default to 'live' if not specified
        
#         # Choose collection based on type
#         collection = db.uploads if collection_type == 'upload' else db.live
#         flight = collection.find_one({'flight_id': flight_id})
            
#         if not flight:
#             return jsonify({
#                 'success': False,
#                 'message': f'Flight not found in {collection_type} collection'
#             }), 404

#         # Extract flight info
#         flight_data = flight['flight']
        
#         # Get track points from TimescaleDB
#         session = current_app.timescale_db()
#         try:
#             # Choose the correct table model based on collection type
#             TrackModel = UploadedTrackPoint if collection_type == 'upload' else LiveTrackPoint
            
#             track_points = session.query(TrackModel).filter(
#                 TrackModel.flight_id == flight_id
#             ).order_by(TrackModel.datetime).all()
            
#             # Convert track points to dictionary format
#             points = [{
#                 'datetime': point.datetime.isoformat(),
#                 'lat': point.lat,
#                 'lon': point.lon,
#                 'elevation': point.elevation,
#                 'speed': point.speed
#             } for point in track_points]
#         finally:
#             session.close()
        
#         return jsonify({
#             'success': True,
#             'flight_id': flight_id,
#             'pilot_id': str(flight_data['pilot_id']),
#             'race_id': str(flight_data['race_id']),
#             'assignment_id': str(flight_data['assignment_id']),
#             'type': flight_data.get('type', 'unknown'),  # 'live' or 'upload'
#             'metadata': flight_data.get('metadata', {}),
#             'created_at': flight_data.get('created_at'),
#             'track_points': points,
#             'total_points': len(points),
#             'storage_type': 'timescaledb',
#             'collection': collection_type
#         }), 200
        
#     except Exception as e:
#         logger.error(f"Error retrieving flight points: {str(e)}")
#         return jsonify({
#             'error': 'Failed to retrieve flight points',
#             'details': str(e)
#         }), 500

        
        