from datetime import datetime, timezone, timedelta
from database.models import Flight, LiveTrackPoint, Race
import asyncio
from ws_conn import manager
from database.db_conf import Session
import logging


logger = logging.getLogger(__name__)

# Add this function to periodically send tracking updates


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
                    # Query for latest tracking data
                    current_time = datetime.now(timezone.utc)
                    lookback_time = current_time - \
                        timedelta(minutes=10)  # Last 10 minutes

                    # Get flights with recent updates
                    flights = (
                        db.query(Flight)
                        .filter(
                            Flight.race_id == race_id
                        )
                        .all()
                    )

                    # Filter flights with recent updates
                    active_flights = []
                    for flight in flights:
                        # Skip flights without last_fix
                        if not flight.last_fix or 'datetime' not in flight.last_fix:
                            continue

                        try:
                            # Parse last_fix datetime and compare with lookback time
                            last_fix_time = datetime.fromisoformat(
                                flight.last_fix['datetime'].replace(
                                    'Z', '+00:00')
                            ).astimezone(timezone.utc)

                            if last_fix_time >= lookback_time:
                                active_flights.append(flight)
                        except (ValueError, KeyError) as e:
                            logger.error(
                                f"Error parsing datetime for flight {flight.id}: {e}")

                    if not active_flights:
                        continue

                    # Format flight data for the update
                    flight_updates = []
                    for flight in active_flights:
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
                            "total_points": flight.total_points
                        }

                        # Only for live tracks, include most recent points
                        if flight.source == 'live':
                            # Get latest points
                            latest_time = datetime.fromisoformat(
                                flight.last_fix['datetime'].replace('Z', '+00:00')).astimezone(timezone.utc)

                            flight_id_str = str(flight.id)
                            race_pilots_sent = manager.get_pilots_with_sent_data(
                                race_id)

                            # Check if we've seen this pilot before
                            first_update = flight_id_str not in race_pilots_sent

                            # Get just new points since last update
                            last_sent_time = manager.get_last_update_time(
                                race_id, flight_id_str)

                            if first_update:
                                # If this is the first update since connection, we don't need to send
                                # the full track history since it was already sent in initial_data
                                # Just mark this pilot as having data and continue to next pilot
                                manager.add_pilot_with_sent_data(
                                    race_id, flight_id_str, latest_time)
                                continue

                            # For subsequent updates, get points since last update
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
                                # No new points to send
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

                        flight_updates.append(flight_info)

                    # Only send update if there are valid flights with updates
                    if flight_updates:
                        # Broadcast update to all clients for this race
                        await manager.send_update(race_id, flight_updates)

        except Exception as e:
            logger.error(f"Error in periodic tracking update: {str(e)}")
            # Continue running despite errors
