import logging
from typing import Dict, List, Optional, Tuple, Literal
from datetime import datetime, timedelta
import math

# Define the flight states
FlightState = Literal['flying', 'walking',
                      'stationary', 'launch', 'landing', 'unknown',
                      'uploaded', 'inactive']

# Constants for flight state detection

# m/s (~10 km/h) - typical minimum paraglider flying speed
FLYING_MIN_SPEED = 2.7
WALKING_MAX_SPEED = 2.0  # m/s (~7.2 km/h) - upper limit for walking
# m/s (~1.8 km/h) - upper limit for being stationary
STATIONARY_MAX_SPEED = 0.5
SIGNIFICANT_ALTITUDE_CHANGE = 5.0  # meters - significant change in altitude
MIN_POINTS_FOR_STATE = 5  # minimum points needed for reliable state detection
# time to keep flying status after potential landing
FLYING_BUFFER_TIME = timedelta(seconds=60)
# time window to check for significant altitude changes
ALTITUDE_CHANGE_WINDOW = timedelta(seconds=30)
# inactivity threshold for live flights
INACTIVITY_THRESHOLD = timedelta(minutes=5)

logger = logging.getLogger(__name__)


def calculate_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance between two points using Haversine formula (in meters)"""
    R = 6371000  # Earth radius in meters

    # Convert latitude and longitude from degrees to radians
    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    lat2_rad = math.radians(lat2)
    lon2_rad = math.radians(lon2)

    # Haversine formula
    dlon = lon2_rad - lon1_rad
    dlat = lat2_rad - lat1_rad
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1_rad) * \
        math.cos(lat2_rad) * math.sin(dlon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    distance = R * c

    return distance


def calculate_speed(distance: float, time_diff_seconds: float) -> float:
    """Calculate speed in m/s given distance and time difference"""
    if time_diff_seconds <= 0:
        return 0
    return distance / time_diff_seconds


def detect_flight_state(
    track_points: List[Dict],
    previous_state: Optional[FlightState] = None,
    min_points: int = MIN_POINTS_FOR_STATE
) -> Tuple[FlightState, Dict]:
    """
    Detect flight state from track points

    Args:
        track_points: List of track points with lat, lon, elevation, datetime
        previous_state: Previous flight state (if known)
        min_points: Minimum points needed for reliable detection

    Returns:
        Tuple of (flight_state, state_info)
    """
    if not track_points or len(track_points) < min_points:
        return previous_state or 'unknown', {'confidence': 'low', 'reason': 'insufficient_data'}

    # Sort track points by datetime
    sorted_points = sorted(track_points, key=lambda p:
                           datetime.fromisoformat(
                               p['datetime'].replace('Z', '+00:00'))
                           if isinstance(p['datetime'], str) else p['datetime'])

    # Calculate speeds between consecutive points
    speeds = []
    altitude_changes = []
    total_distance = 0
    total_time = 0

    for i in range(1, len(sorted_points)):
        p1 = sorted_points[i-1]
        p2 = sorted_points[i]

        # Get timestamps
        t1 = p1['datetime'] if isinstance(p1['datetime'], datetime) else datetime.fromisoformat(
            p1['datetime'].replace('Z', '+00:00'))
        t2 = p2['datetime'] if isinstance(p2['datetime'], datetime) else datetime.fromisoformat(
            p2['datetime'].replace('Z', '+00:00'))

        time_diff = (t2 - t1).total_seconds()
        if time_diff <= 0:
            continue  # Skip invalid time differences

        # Calculate distance
        distance = calculate_distance(
            p1['lat'], p1['lon'], p2['lat'], p2['lon'])
        total_distance += distance
        total_time += time_diff

        # Calculate speed
        speed = calculate_speed(distance, time_diff)
        speeds.append(speed)

        # Calculate altitude change
        if 'elevation' in p1 and 'elevation' in p2 and p1['elevation'] is not None and p2['elevation'] is not None:
            alt_change = p2['elevation'] - p1['elevation']
            altitude_changes.append((alt_change, time_diff, t2))

    if not speeds:
        return previous_state or 'unknown', {'confidence': 'low', 'reason': 'no_speed_data'}

    # Calculate average speed
    avg_speed = sum(speeds) / len(speeds)
    max_speed = max(speeds)

    # Calculate average speed over the entire track
    overall_avg_speed = total_distance / total_time if total_time > 0 else 0

    # Check for significant altitude changes in recent points
    recent_altitude_change = 0
    if altitude_changes:
        latest_time = altitude_changes[-1][2]
        window_start = latest_time - ALTITUDE_CHANGE_WINDOW
        recent_changes = [change for change, _,
                          t in altitude_changes if t >= window_start]
        if recent_changes:
            recent_altitude_change = sum(recent_changes)

    # Determine state based on speeds and altitude changes
    state_info = {
        'avg_speed': avg_speed,
        'max_speed': max_speed,
        'overall_avg_speed': overall_avg_speed,
        'speed_count': len(speeds),
        'altitude_change': recent_altitude_change,
        'confidence': 'high' if len(speeds) >= min_points else 'medium'
    }

    # State determination logic
    if avg_speed >= FLYING_MIN_SPEED or abs(recent_altitude_change) >= SIGNIFICANT_ALTITUDE_CHANGE:
        state = 'flying'
    elif avg_speed <= WALKING_MAX_SPEED and avg_speed > STATIONARY_MAX_SPEED:
        state = 'walking'
    elif avg_speed <= STATIONARY_MAX_SPEED:
        state = 'stationary'
    else:
        # In between walking and flying - need context
        state = previous_state or 'unknown'

    # Detect launch and landing transitions
    if previous_state == 'flying' and (state == 'walking' or state == 'stationary'):
        state = 'landing'
    elif (previous_state == 'walking' or previous_state == 'stationary') and state == 'flying':
        state = 'launch'

    return state, state_info


def determine_if_landed(point, previous_points=None, previous_state=None):
    """Determine if a pilot has landed based on track point data"""
    if not previous_points:
        return False

    state, _ = detect_flight_state(previous_points + [point], previous_state)
    return state in ['landing', 'stationary', 'walking']


def update_flight_state_in_db(flight_uuid, db, force_update=False, source=None):
    """
    Updates the flight state in the database for a specific flight

    Args:
        flight_uuid: UUID of the flight
        db: Database session
        force_update: Whether to force update even if recently updated
        source: Source of the flight data ('live' or 'upload') - if None, will be determined by the flight record

    Returns:
        Tuple of (state, state_info)
    """
    from database.models import Flight, LiveTrackPoint, UploadedTrackPoint
    from datetime import datetime, timezone, timedelta
    import json

    # Get the flight from database
    flight_query = db.query(Flight).filter(Flight.id == flight_uuid)

    # If source is explicitly provided, filter by it
    if source:
        flight_query = flight_query.filter(Flight.source == source)

    flight = flight_query.first()

    if not flight:
        return 'unknown', {'confidence': 'low', 'reason': 'flight_not_found'}

    # Check if we've updated recently (within last minute) and don't need to force update
    if not force_update and flight.flight_state is not None:
        try:
            state_data = flight.flight_state
            last_updated = datetime.fromisoformat(
                state_data.get('last_updated', '').replace('Z', '+00:00'))

            # If updated within the last 30 seconds, return existing state
            if (datetime.now(timezone.utc) - last_updated).total_seconds() < 30:
                return state_data.get('state', 'unknown'), state_data
        except (ValueError, AttributeError, KeyError):
            # If any error occurs, continue with update
            pass

    # Handle uploaded flights specially - they always have the 'uploaded' state
    if source == 'upload' or (flight and flight.source == 'upload'):
        state_info = {
            'state': 'uploaded',
            'confidence': 'high',
            'reason': 'track_uploaded',
            'last_updated': datetime.now(timezone.utc).isoformat()
        }
        flight.flight_state = state_info
        db.commit()
        return 'uploaded', state_info

    # For live flights, check for inactivity
    if source == 'live' or (flight and flight.source == 'live'):
        # Check if the last fix is older than the inactivity threshold
        if flight.last_fix and 'datetime' in flight.last_fix:
            try:
                last_fix_time = datetime.fromisoformat(
                    flight.last_fix['datetime'].replace('Z', '+00:00'))

                if (datetime.now(timezone.utc) - last_fix_time) > INACTIVITY_THRESHOLD:
                    state_info = {
                        'state': 'inactive',
                        'confidence': 'high',
                        'reason': 'connection_lost',
                        'last_updated': datetime.now(timezone.utc).isoformat(),
                        'last_active': flight.last_fix['datetime']
                    }
                    flight.flight_state = state_info
                    db.commit()
                    return 'inactive', state_info
            except (ValueError, KeyError):
                # If there's an error parsing the datetime, continue with normal detection
                pass

    # Get the flight state
    state, state_info = detect_flight_state_from_db(flight_uuid, db)

    # Add timestamp to state_info
    state_info['last_updated'] = datetime.now(timezone.utc).isoformat()
    state_info['state'] = state

    # Update the flight state in the database
    flight.flight_state = state_info
    db.commit()

    return state, state_info


def detect_flight_state_from_db(flight_uuid, db, recent_points_limit=20):
    """Get the current flight state for a specific flight from database points"""
    from database.models import Flight, LiveTrackPoint, UploadedTrackPoint

    # First determine the flight source
    flight = db.query(Flight).filter(Flight.id == flight_uuid).first()
    if not flight:
        return 'unknown', {'confidence': 'low', 'reason': 'flight_not_found'}

    # Get the most recent track points for this flight based on the source
    if flight.source == 'live':
        recent_points = db.query(LiveTrackPoint).filter(
            LiveTrackPoint.flight_uuid == flight_uuid
        ).order_by(LiveTrackPoint.datetime.desc()).limit(recent_points_limit).all()
    else:  # 'upload'
        recent_points = db.query(UploadedTrackPoint).filter(
            UploadedTrackPoint.flight_uuid == flight_uuid
        ).order_by(UploadedTrackPoint.datetime.desc()).limit(recent_points_limit).all()

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
