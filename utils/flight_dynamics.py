"""
Flight dynamics calculation utilities for speed, heading, and vario.
"""

import math
from typing import Optional, Tuple, List, Dict, Any
from datetime import datetime


def calculate_distance_haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate distance between two points using haversine formula.

    Args:
        lat1, lon1: First point coordinates
        lat2, lon2: Second point coordinates

    Returns:
        Distance in meters
    """
    R = 6371000  # Earth radius in meters

    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)

    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * \
        math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

    return R * c


def calculate_bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate bearing/heading from point 1 to point 2.

    Args:
        lat1, lon1: Start point coordinates
        lat2, lon2: End point coordinates

    Returns:
        Bearing in degrees (0-360)
    """
    dLon = math.radians(lon2 - lon1)
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)

    y = math.sin(dLon) * math.cos(lat2_rad)
    x = math.cos(lat1_rad) * math.sin(lat2_rad) - \
        math.sin(lat1_rad) * math.cos(lat2_rad) * math.cos(dLon)

    bearing = math.degrees(math.atan2(y, x))
    return (bearing + 360) % 360  # Normalize to 0-360


def calculate_speed(distance: float, time_seconds: float) -> float:
    """
    Calculate speed from distance and time.

    Args:
        distance: Distance in meters
        time_seconds: Time in seconds

    Returns:
        Speed in m/s
    """
    if time_seconds <= 0:
        return 0
    return distance / time_seconds


def calculate_vario(altitude1: float, altitude2: float, time_seconds: float) -> float:
    """
    Calculate vertical speed (vario) from altitude change.

    Args:
        altitude1: Start altitude in meters
        altitude2: End altitude in meters
        time_seconds: Time difference in seconds

    Returns:
        Vario in m/s (positive = climbing, negative = descending)
    """
    if time_seconds <= 0:
        return 0
    return (altitude2 - altitude1) / time_seconds


def calculate_flight_dynamics(recent_points: List[Any],
                             flight_state: Optional[Dict[str, Any]] = None,
                             vario_smoothing: int = 3) -> Dict[str, float]:
    """
    Calculate speed, heading, and vario from recent track points.

    Args:
        recent_points: List of track points (newest first) with lat, lon, elevation, datetime
        flight_state: Optional flight state dict with avg_speed, altitude_change
        vario_smoothing: Number of points to use for vario averaging (default 3)

    Returns:
        Dictionary with speed (m/s), heading (degrees), and vario (m/s)
    """
    result = {
        'speed': 0.0,
        'heading': 0.0,
        'vario': 0.0
    }

    # Use flight_state for speed if available
    if flight_state:
        result['speed'] = float(flight_state.get('avg_speed', 0))

        # Simple vario estimate from flight_state if no points
        altitude_change = flight_state.get('altitude_change', 0)
        if altitude_change:
            result['vario'] = altitude_change / 60  # Rough estimate

    # Need at least 2 points for calculations
    if len(recent_points) < 2:
        return result

    # Points are ordered newest first
    p1 = recent_points[1]  # Older point
    p2 = recent_points[0]  # Newer point

    # Extract coordinates
    lat1, lon1 = p1.lat, p1.lon
    lat2, lon2 = p2.lat, p2.lon

    # Calculate time difference
    time_diff = (p2.datetime - p1.datetime).total_seconds()

    if time_diff > 0:
        # Calculate heading
        result['heading'] = calculate_bearing(lat1, lon1, lat2, lon2)

        # Calculate smoothed vario using multiple points if available
        if len(recent_points) >= vario_smoothing and vario_smoothing > 1:
            # Calculate vario over a longer period for smoothing
            oldest_point = recent_points[min(vario_smoothing - 1, len(recent_points) - 1)]
            newest_point = recent_points[0]

            if (oldest_point.elevation is not None and newest_point.elevation is not None):
                total_time = (newest_point.datetime - oldest_point.datetime).total_seconds()
                if total_time > 0:
                    total_altitude_change = newest_point.elevation - oldest_point.elevation
                    result['vario'] = total_altitude_change / total_time
        else:
            # Fall back to instant vario between last 2 points
            if p1.elevation is not None and p2.elevation is not None:
                result['vario'] = calculate_vario(p1.elevation, p2.elevation, time_diff)

        # Calculate instant speed if not from flight_state
        if result['speed'] == 0:
            distance = calculate_distance_haversine(lat1, lon1, lat2, lon2)
            result['speed'] = calculate_speed(distance, time_diff)

    return result


def calculate_flight_dynamics_from_dicts(recent_points: List[Dict[str, Any]],
                                        flight_state: Optional[Dict[str, Any]] = None) -> Dict[str, float]:
    """
    Calculate speed, heading, and vario from recent track points as dictionaries.

    Args:
        recent_points: List of track point dicts (newest first) with keys: lat, lon, elevation, datetime
        flight_state: Optional flight state dict with avg_speed, altitude_change

    Returns:
        Dictionary with speed (m/s), heading (degrees), and vario (m/s)
    """
    result = {
        'speed': 0.0,
        'heading': 0.0,
        'vario': 0.0
    }

    # Use flight_state for speed if available
    if flight_state:
        result['speed'] = float(flight_state.get('avg_speed', 0))

        # Simple vario estimate from flight_state if no points
        altitude_change = flight_state.get('altitude_change', 0)
        if altitude_change:
            result['vario'] = altitude_change / 60  # Rough estimate

    # Need at least 2 points for calculations
    if len(recent_points) < 2:
        return result

    # Points are ordered newest first
    p1 = recent_points[1]  # Older point
    p2 = recent_points[0]  # Newer point

    # Extract coordinates
    lat1, lon1 = p1['lat'], p1['lon']
    lat2, lon2 = p2['lat'], p2['lon']

    # Parse datetime if string
    dt1 = p1['datetime']
    dt2 = p2['datetime']
    if isinstance(dt1, str):
        dt1 = datetime.fromisoformat(dt1.replace('Z', '+00:00'))
    if isinstance(dt2, str):
        dt2 = datetime.fromisoformat(dt2.replace('Z', '+00:00'))

    # Calculate time difference
    time_diff = (dt2 - dt1).total_seconds()

    if time_diff > 0:
        # Calculate heading
        result['heading'] = calculate_bearing(lat1, lon1, lat2, lon2)

        # Calculate vario from actual altitude changes
        if p1.get('elevation') is not None and p2.get('elevation') is not None:
            result['vario'] = calculate_vario(p1['elevation'], p2['elevation'], time_diff)

        # Calculate instant speed if not from flight_state
        if result['speed'] == 0:
            distance = calculate_distance_haversine(lat1, lon1, lat2, lon2)
            result['speed'] = calculate_speed(distance, time_diff)

    return result