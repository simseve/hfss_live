from datetime import datetime, timezone, timedelta, time
from database.models import Flight, LiveTrackPoint, Race
import asyncio
from ws_conn import manager
from database.db_conf import Session
import logging
from zoneinfo import ZoneInfo


logger = logging.getLogger(__name__)

# Background task to send periodic tracking updates to connected clients


async def periodic_tracking_update(interval_seconds: int = 30):
    """Background task to send periodic tracking updates to connected clients"""
    while True:
        try:
            # Wait for the specified interval
            await asyncio.sleep(interval_seconds)

            # Get active races with connected clients
            active_races = list(manager.active_connections.keys())

            if not active_races:
                continue

            # Process each active race
            for race_id in active_races:
                # Only process races with active viewers
                if manager.get_active_viewers(race_id) == 0:
                    continue

                # Get a DB session
                with Session() as db:
                    # Current server time in UTC
                    current_time = datetime.now(timezone.utc)

                    # Get race information including timezone
                    race = db.query(Race).filter(
                        Race.race_id == race_id).first()
                    if not race or not race.timezone:
                        race_timezone = timezone.utc  # Default to UTC if race timezone not found
                    else:
                        # Get the timezone object from the race
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
                            Flight.created_at >= utc_day_start - lookback_buffer,
                            Flight.created_at <= utc_day_end,
                            Flight.source == 'live'
                        )
                        .order_by(Flight.created_at.desc())
                        .all()
                    )

                    # # Further filter to only pilots who have been active in the last hour
                    # active_threshold = current_time - timedelta(minutes=60)
                    # active_flights = []

                    # for flight in flights:
                    #     last_fix_time = datetime.fromisoformat(
                    #         flight.last_fix['datetime'].replace('Z', '+00:00')
                    #     ).astimezone(timezone.utc)

                    #     if last_fix_time >= active_threshold:
                    #         active_flights.append(flight)

                    # Process flights to get the most recent one per pilot
                    pilot_latest_flights = {}

                    for flight in flights:
                        pilot_id = str(flight.pilot_id)

                        # If we haven't seen this pilot yet, this is their most recent flight
                        # (since flights are already ordered by created_at DESC)
                        if pilot_id not in pilot_latest_flights:
                            pilot_latest_flights[pilot_id] = flight

                    # Format flight data for the update
                    flight_updates = []

                    for pilot_id, flight in pilot_latest_flights.items():
                        flight_info = {
                            "uuid": str(flight.id),
                            "pilot_id": flight.pilot_id,
                            "pilot_name": flight.pilot_name,
                            "lastFix": {
                                "lat": flight.last_fix['lat'],
                                "lon": flight.last_fix['lon'],
                                "elevation": flight.last_fix.get('elevation', 0),
                                "datetime": flight.last_fix['datetime']
                            },
                            "source": flight.source,
                            "total_points": flight.total_points,
                            # Add flight state information if available
                            "flight_state": flight.flight_state.get('state', 'unknown') if flight.flight_state else 'unknown',
                            "flight_state_info": flight.flight_state if flight.flight_state else {}
                        }

                        # Track whether we need to add this flight to updates at the end
                        should_add_to_updates = False

                        # Only for live tracks, include most recent points
                        if flight.source == 'live':
                            # Get latest points
                            latest_time = datetime.fromisoformat(
                                flight.last_fix['datetime'].replace('Z', '+00:00')).astimezone(timezone.utc)

                            flight_id_str = str(flight.id)

                            # Get last sent time for this flight
                            last_sent_time = manager.get_last_update_time(
                                race_id, flight_id_str)

                            # For subsequent updates, get points since last update
                            # If no last_sent_time, use a small lookback period
                            earliest_time = last_sent_time if last_sent_time else (
                                latest_time - timedelta(seconds=30))

                            latest_points = (
                                db.query(LiveTrackPoint)
                                .filter(
                                    LiveTrackPoint.flight_uuid == flight.id,
                                    LiveTrackPoint.datetime > earliest_time
                                )
                                .order_by(LiveTrackPoint.datetime.asc())
                                .all()
                            )

                            # Update the last sent time
                            if latest_points:
                                manager.add_pilot_with_sent_data(
                                    race_id, flight_id_str, latest_time)
                            else:
                                # No new points to send, but check for inactivity
                                # Skip if already marked as inactive or uploaded
                                current_state = flight.flight_state.get(
                                    'state', 'unknown') if flight.flight_state else 'unknown'
                                if current_state in ['inactive', 'uploaded']:
                                    continue

                                # Import needed for INACTIVITY_THRESHOLD
                                from api.flight_state import INACTIVITY_THRESHOLD

                                # Check if the last fix is older than the inactivity threshold
                                try:
                                    last_fix_time = datetime.fromisoformat(
                                        flight.last_fix['datetime'].replace('Z', '+00:00'))

                                    if (datetime.now(timezone.utc) - last_fix_time) > INACTIVITY_THRESHOLD:
                                        # Update flight state to 'inactive'
                                        state_info = {
                                            'state': 'inactive',
                                            'confidence': 'high',
                                            'reason': 'connection_lost',
                                            'last_updated': datetime.now(timezone.utc).isoformat(),
                                            'last_active': flight.last_fix['datetime']
                                        }
                                        flight.flight_state = state_info
                                        db.commit()

                                        # Include the flight state info but no points
                                        flight_info["flight_state"] = "inactive"
                                        flight_info["flight_state_info"] = state_info
                                        should_add_to_updates = True
                                except (ValueError, KeyError):
                                    # If there's an error parsing the datetime, skip this flight
                                    pass

                                # Skip to the next iteration since there are no track points to process
                                continue

                            # Format points for transfer (similar to your GeoJSON endpoint)
                            coordinates = []
                            last_time = None
                            is_first_point = True

                            for point in latest_points:
                                current_time = point.datetime

                                coordinate = [
                                    float(point.lon),
                                    float(point.lat),
                                    int(point.elevation or 0)
                                ]

                                if is_first_point:
                                    extra_data = {"dt": 0}
                                    coordinate.append(extra_data)
                                    is_first_point = False
                                elif last_time is not None:
                                    dt = int(
                                        (current_time - last_time).total_seconds())
                                    if dt != 1:
                                        extra_data = {"dt": dt}
                                        coordinate.append(extra_data)

                                coordinates.append(coordinate)
                                last_time = current_time

                            # Add points to flight info
                            flight_info["track_update"] = {
                                "type": "LineString",
                                "coordinates": coordinates
                            }
                            should_add_to_updates = True

                        # Only add to flight_updates if it has track points or was marked as inactive
                        if should_add_to_updates or flight_info["flight_state"] == "inactive":
                            flight_updates.append(flight_info)

                    # Only send update if there are valid flights with updates
                    if flight_updates:
                        # Broadcast update to all clients for this race
                        await manager.send_update(race_id, flight_updates)

        except Exception as e:
            logger.error(f"Error in periodic tracking update: {str(e)}")
            # Continue running despite errors
