import httpx
import asyncio
import logging
from typing import Dict, List, Optional, Any, Set
from datetime import datetime, timedelta, timezone, time
from sqlalchemy.orm import Session
from database.models import Race, Flight
import jwt
from config import settings

logger = logging.getLogger(__name__)


class XContestService:
    """Service for fetching and processing XContest live tracking data"""
    
    def __init__(self):
        # XContest Livedata API endpoints
        self.users_url = "https://api.xcontest.org/livedata/users"
        self.track_url = "https://api.xcontest.org/livedata/track"
        
    async def get_race_config_and_pilots(
        self, 
        race_id: str,
        token: str
    ) -> Dict[str, Any]:
        """Fetch race configuration and pilots from HFSS API"""
        try:
            headers = {
                "accept": "application/json",
                "Authorization": f"Bearer {token}"
            }
            
            async with httpx.AsyncClient() as client:
                # Get XContest API key for this race (race_id is in the token)
                xc_key_response = await client.get(
                    f"{settings.HFSS_SERVER}race/xc_api_key",
                    headers=headers
                )
                
                # Get pilots (race_id is in the token)
                pilots_response = await client.get(
                    f"{settings.HFSS_SERVER}race/pilots",
                    headers=headers
                )
                
                if xc_key_response.status_code == 200 and pilots_response.status_code == 200:
                    xc_key_data = xc_key_response.json()
                    pilots_data = pilots_response.json()
                    
                    # Extract XContest handles from pilots
                    # pilots_data is likely a list directly, not a dict with 'pilots' key
                    xcontest_pilot_map = {}
                    pilots_list = pilots_data if isinstance(pilots_data, list) else pilots_data.get('pilots', [])
                    
                    for pilot in pilots_list:
                        xcontest_handle = pilot.get('xcontest') if isinstance(pilot, dict) else None
                        if xcontest_handle:
                            xc_id = xcontest_handle.strip().lower()
                            xcontest_pilot_map[xc_id] = {
                                'pilot_id': pilot.get('_id'),
                                'name': pilot.get('name', ''),
                                'surname': pilot.get('surname', ''),
                                # 'team_id': pilot.get('team_id'),
                                # 'task_id': pilot.get('task_id'),
                                'xcontest': xcontest_handle
                            }
                    
                    return {
                        'success': True,
                        'xc_entity': xc_key_data.get('xc_entity', '').rstrip() if xc_key_data else '',
                        'xc_api_key': xc_key_data.get('xc_api_key', '') if xc_key_data else '',
                        'pilots': pilots_list,
                        'xcontest_map': xcontest_pilot_map
                    }
                else:
                    # Log as info, not error - authentication issues are expected
                    if xc_key_response.status_code == 401 or pilots_response.status_code == 401:
                        logger.info("Unable to authenticate with HFSS API for XContest data - skipping XContest integration")
                    else:
                        logger.warning(f"Failed to fetch data: xc_key={xc_key_response.status_code}, pilots={pilots_response.status_code}")
                    return {'success': False, 'pilots': [], 'xcontest_map': {}}
                    
        except Exception as e:
            logger.error(f"Error fetching race config and pilots: {str(e)}")
            return {'success': False, 'pilots': [], 'xcontest_map': {}}
    
    async def get_users_and_flights(
        self,
        entity: str,
        open_time: str,
        close_time: str,
        api_key: str
    ) -> tuple[Optional[Dict], int]:
        """Fetch users and their live flights from XContest API"""
        try:
            params = {
                "entity": entity,
                "opentime": open_time,  # Note: lowercase per API docs
                "closetime": close_time,  # Note: lowercase per API docs
                "source": "live"
            }
            headers = {"Authorization": f"Bearer {api_key}"}
            
            logger.debug(f"XContest API request params: {params}")
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    self.users_url,
                    params=params,
                    headers=headers
                )
                
                if response.status_code == 200:
                    return response.json(), 200
                else:
                    logger.error(f"XContest API error: {response.status_code}")
                    return None, response.status_code
                    
        except Exception as e:
            logger.error(f"Error fetching XContest users: {str(e)}")
            return None, 500
    
    async def fetch_track_data(
        self,
        flight_uuid: str,
        entity: str,
        api_key: str,
        lastfixtime: Optional[str] = None
    ) -> Optional[Dict]:
        """Fetch detailed track data for a specific flight
        
        Args:
            flight_uuid: The flight UUID
            entity: The entity identifier (e.g., contest:xyz)
            api_key: XContest API key
            lastfixtime: ISO8601 UTC datetime for incremental updates (optional)
        """
        try:
            params = {"entity": entity, "flight": flight_uuid}
            if lastfixtime:
                params["lastfixtime"] = lastfixtime
                
            headers = {"Authorization": f"Bearer {api_key}"}
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    self.track_url,
                    params=params,
                    headers=headers
                )
                
                if response.status_code == 200:
                    track_response = response.json()
                    return self._process_track_coordinates(track_response)
                else:
                    logger.error(f"Failed to fetch track for flight {flight_uuid}: {response.status_code}")
                    return None
                    
        except Exception as e:
            logger.error(f"Error fetching track for flight {flight_uuid}: {str(e)}")
            return None
    
    def _process_track_coordinates(self, track_response: Dict) -> Dict:
        """Process raw XContest track coordinates into structured format"""
        try:
            coordinates = track_response['flight']['geometry']['coordinates']
            first_fix_time = datetime.strptime(
                track_response['flight']['properties']['firstFixTime'],
                "%Y-%m-%dT%H:%M:%SZ"
            )
            
            processed_coordinates = []
            current_time = first_fix_time
            
            for coord in coordinates:
                lon, lat, gps_alt = coord[:3]
                extra_data = coord[3] if len(coord) > 3 else {}
                baro_alt = extra_data.get('b')
                dt = extra_data.get('dt', 1)
                
                if dt is not None:
                    current_time += timedelta(seconds=dt)
                
                processed_coordinates.append({
                    'timestamp': current_time,
                    'lon': lon,
                    'lat': lat,
                    'gps_alt': gps_alt,
                    'baro_alt': baro_alt
                })
            
            return {
                'coordinates': processed_coordinates,
                'firstFixTime': first_fix_time
            }
        except Exception as e:
            logger.error(f"Error processing track coordinates: {str(e)}")
            return None
    
    async def get_xcontest_flights_for_race(
        self,
        xc_entity: str,
        xc_api_key: str,
        xcontest_pilot_map: Dict[str, Dict],
        race_timezone: Any
    ) -> List[Dict]:
        """Get all XContest flights for pilots in a race"""
        
        if not xc_entity or not xc_api_key:
            return []
        
        # Get current time in race timezone
        current_time = datetime.now(timezone.utc)
        race_local_time = current_time.astimezone(race_timezone)
        
        # Calculate the start and end of the current day in race's timezone
        race_day_start = datetime.combine(
            race_local_time.date(), time.min, tzinfo=race_timezone)
        race_day_end = datetime.combine(
            race_local_time.date(), time.max, tzinfo=race_timezone)
        
        # Convert back to UTC for API calls
        utc_day_start = race_day_start.astimezone(timezone.utc)
        utc_day_end = race_day_end.astimezone(timezone.utc)
        
        # XContest API returns flights that STARTED within the time window
        # Look back with a 4-hour buffer (same as default method) to catch flights that started slightly before today
        lookback_buffer = timedelta(hours=4)
        open_time_dt = utc_day_start - lookback_buffer
        close_time_dt = utc_day_end
        
        open_time = open_time_dt.strftime('%Y-%m-%dT%H:%M:%SZ')
        close_time = close_time_dt.strftime('%Y-%m-%dT%H:%M:%SZ')
        
        # Log the timing for initial fetch
        logger.info("="*60)
        logger.info("XCONTEST API INITIAL FETCH TIMING:")
        logger.info(f"  Race timezone:        {race_timezone}")
        logger.info(f"  Race local time:      {race_local_time.isoformat()}")
        logger.info(f"  Today in race TZ:     {race_day_start.isoformat()} to {race_day_end.isoformat()}")
        logger.info(f"  Open time (UTC):      {open_time} (today start - 4h buffer)")
        logger.info(f"  Close time (UTC):     {close_time} (today end)")
        logger.info(f"  API URL: {self.users_url}")
        logger.info(f"  Entity: {xc_entity}")
        logger.info("="*60)
        
        # Fetch users and flights from XContest
        logger.info(f"Fetching XContest flights for today in race timezone: {open_time} to {close_time}")
        users_response, status = await self.get_users_and_flights(
            xc_entity,
            open_time,
            close_time,
            xc_api_key
        )
        
        if not users_response or status != 200:
            logger.warning(f"Failed to get XContest users: status={status}")
            return []
        
        logger.info(f"XContest returned {len(users_response.get('users', {}))} users for today")
        
        # Filter users to only include registered pilots
        filtered_users = {}
        all_usernames = []
        for user_id, user_data in users_response.get('users', {}).items():
            username = user_data.get('username', '').lower()
            all_usernames.append(username)
            if username in xcontest_pilot_map:
                filtered_users[user_id] = user_data
        
        logger.info(f"XContest users found: {all_usernames}")
        logger.info(f"Filtered to {len(filtered_users)} pilots registered in race")
        
        # Process flights
        pilot_flights = []
        for user_id, user_data in filtered_users.items():
            xcontest_id = user_data['username']
            pilot_info = xcontest_pilot_map.get(xcontest_id.lower())
            
            if not pilot_info:
                continue
            
            # Get latest flight for this pilot that is from today or still active
            latest_flight = None
            latest_time = None
            flights_found = 0
            flights_filtered = 0
            
            for flight in user_data.get('flights', []):
                flights_found += 1
                # Check if this flight is from today or has last fix during today
                # First, check last fix time
                last_fix = flight.get('lastFix')
                if last_fix and len(last_fix) >= 4 and isinstance(last_fix[3], dict):
                    last_fix_str = last_fix[3].get('t')
                    if last_fix_str:
                        last_fix_time = datetime.strptime(last_fix_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                        
                        # Check if last fix is within today's window (or within lookback buffer)
                        if last_fix_time >= open_time_dt and last_fix_time <= close_time_dt:
                            # This flight is from today or still active today
                            if latest_time is None or last_fix_time > latest_time:
                                latest_time = last_fix_time
                                latest_flight = flight
                        else:
                            flights_filtered += 1
                            logger.debug(f"Filtered out flight for {xcontest_id}: last fix {last_fix_str} not in today's window")
            
            if flights_filtered > 0:
                logger.info(f"Pilot {xcontest_id}: {flights_found} flights found, {flights_filtered} filtered out (not today), using latest from today")
            
            if latest_flight:
                # Fetch track data
                track_data = await self.fetch_track_data(
                    latest_flight['uuid'],
                    xc_entity,
                    xc_api_key
                )
                
                if track_data and track_data.get('coordinates'):
                    # Convert to format compatible with WebSocket endpoint
                    downsampled_points = []
                    last_added_time = None
                    
                    for point in track_data['coordinates']:
                        current_time = point['timestamp']
                        if last_added_time is None or (current_time - last_added_time).total_seconds() >= 3:
                            downsampled_points.append({
                                "lat": float(point['lat']),
                                "lon": float(point['lon']),
                                "elevation": float(point['gps_alt']) if point['gps_alt'] is not None else 0,
                                "baro_altitude": float(point['baro_alt']) if point['baro_alt'] is not None else None,
                                "datetime": current_time.strftime("%Y-%m-%dT%H:%M:%SZ")
                            })
                            last_added_time = current_time
                    
                    # Create flight data structure
                    first_fix = latest_flight.get('firstFix', [])
                    last_fix = latest_flight.get('lastFix', [])
                    
                    pilot_flight = {
                        "uuid": f"xc_{latest_flight['uuid']}",  # Prefix to distinguish from HFSS flights
                        "pilot_id": pilot_info['pilot_id'],
                        "pilot_name": f"{pilot_info['name']} {pilot_info['surname']}",
                        "firstFix": {
                            "lat": first_fix[1] if len(first_fix) > 1 else 0,
                            "lon": first_fix[0] if len(first_fix) > 0 else 0,
                            "elevation": first_fix[2] if len(first_fix) > 2 else 0,
                            "datetime": first_fix[3].get('t') if len(first_fix) > 3 and isinstance(first_fix[3], dict) else None
                        },
                        "lastFix": {
                            "lat": last_fix[1] if len(last_fix) > 1 else 0,
                            "lon": last_fix[0] if len(last_fix) > 0 else 0,
                            "elevation": last_fix[2] if len(last_fix) > 2 else 0,
                            "datetime": last_fix[3].get('t') if len(last_fix) > 3 and isinstance(last_fix[3], dict) else None
                        },
                        "trackHistory": downsampled_points,
                        "totalPoints": len(track_data['coordinates']),
                        "downsampledPoints": len(downsampled_points),
                        "source": "XC",  # Mark as XContest data
                        "lastFixTime": last_fix[3].get('t') if len(last_fix) > 3 and isinstance(last_fix[3], dict) else None,
                        "isActive": not latest_flight.get('landed', False),
                        "flight_state": "flying" if not latest_flight.get('landed', False) else "landed",
                        "flight_state_info": {
                            "state": "flying" if not latest_flight.get('landed', False) else "landed",
                            "landed": latest_flight.get('landed', False)
                        },
                        "glider": latest_flight.get('glider', ''),
                        "xcontest_id": xcontest_id
                    }
                    
                    pilot_flights.append(pilot_flight)
                    logger.info(f"Added XContest flight for {xcontest_id} from today (last fix: {pilot_flight['lastFixTime']})")
        
        logger.info(f"Returning {len(pilot_flights)} XContest flights from today for race")
        return pilot_flights


    async def get_xcontest_incremental_updates(
        self,
        xc_entity: str,
        xc_api_key: str,
        xcontest_pilot_map: Dict[str, Dict],
        active_xc_flights: Dict[str, Dict],
        race_timezone: Any = None,
        lookback_seconds: int = 300
    ) -> List[Dict]:
        """Get incremental updates for active XContest flights
        
        Simply fetches new points for each tracked flight using lastfixtime
        
        Args:
            xc_entity: XContest entity identifier
            xc_api_key: XContest API key
            xcontest_pilot_map: Map of XContest usernames to pilot info
            active_xc_flights: Dict of currently tracked XC flights with their last update times
            
        Returns:
            List of flight updates with incremental track data
        """
        if not xc_entity or not xc_api_key:
            return []
            
        logger.info(f"Getting XContest incremental updates for {len(active_xc_flights)} tracked flights")
        
        # Log incremental update details
        logger.info("="*60)
        logger.info("XCONTEST INCREMENTAL UPDATES:")
        logger.info(f"  Tracked flights: {len(active_xc_flights)}")
        if active_xc_flights:
            for flight_id, flight_data in list(active_xc_flights.items())[:3]:  # Show first 3
                logger.info(f"    {flight_id}: last fix = {flight_data.get('lastFixTime')}")
        logger.info("="*60)
        
        flight_updates = []
        
        # For each tracked flight, fetch new points since last fix time
        for xc_flight_id, flight_info in active_xc_flights.items():
            # Extract the actual flight UUID (remove 'xc_' prefix)
            if not xc_flight_id.startswith('xc_'):
                continue
            
            flight_uuid = xc_flight_id[3:]  # Remove 'xc_' prefix
            last_known_time = flight_info.get('lastFixTime')
            pilot_id = flight_info.get('pilot_id')  # Get stored pilot_id
            pilot_name = flight_info.get('pilot_name')  # Get stored pilot name
            
            if not last_known_time:
                logger.warning(f"No last fix time for flight {xc_flight_id}, skipping")
                continue
            
            if not pilot_id:
                logger.warning(f"No pilot_id for flight {xc_flight_id}, skipping")
                continue
            
            logger.debug(f"Fetching updates for flight {xc_flight_id} since {last_known_time}")
            
            # Fetch incremental track data directly
            track_data = await self.fetch_track_data(
                flight_uuid,
                xc_entity,
                xc_api_key,
                lastfixtime=last_known_time  # Get only points after this time
            )
            
            if track_data and track_data.get('coordinates'):
                logger.info(f"Got {len(track_data['coordinates'])} new points for flight {xc_flight_id}")
                
                # Get the last coordinate to extract the new last fix
                last_coord = track_data['coordinates'][-1] if track_data['coordinates'] else None
                
                # Format the update (no downsampling for incremental updates)
                coordinates = []
                is_first_point = True
                last_time = None
                
                for point in track_data['coordinates']:
                    current_time = point['timestamp']
                    
                    coordinate = [
                        float(point['lon']),
                        float(point['lat']),
                        int(point['gps_alt'] or 0)
                    ]
                    
                    # Add barometric altitude if available
                    extra_data = {}
                    if point.get('baro_alt') is not None:
                        extra_data['b'] = int(point['baro_alt'])
                    
                    if is_first_point:
                        extra_data['dt'] = 0
                        is_first_point = False
                    elif last_time is not None:
                        dt = int((current_time - last_time).total_seconds())
                        if dt != 1:
                            extra_data['dt'] = dt
                    
                    if extra_data:
                        coordinate.append(extra_data)
                    
                    coordinates.append(coordinate)
                    last_time = current_time
                
                # Create flight update with pilot info and new track points
                flight_update = {
                    "uuid": xc_flight_id,
                    "pilot_id": pilot_id,  # REQUIRED for frontend to identify the pilot
                    "pilot_name": pilot_name if pilot_name else "",
                    "source": "XC",
                    "total_points": len(track_data['coordinates']),
                    "track_update": {
                        "type": "LineString",
                        "coordinates": coordinates
                    }
                }
                
                # Add last fix info if we have it
                if last_coord:
                    flight_update["lastFix"] = {
                        "lat": float(last_coord['lat']),
                        "lon": float(last_coord['lon']),
                        "elevation": float(last_coord['gps_alt']) if last_coord['gps_alt'] is not None else 0,
                        "datetime": last_coord['timestamp'].strftime("%Y-%m-%dT%H:%M:%SZ")
                    }
                
                flight_updates.append(flight_update)
                logger.info(f"Added XContest flight update for {xc_flight_id} with {len(coordinates)} new points")
            else:
                logger.debug(f"No new track data for flight {xc_flight_id} since {last_known_time}")
        
        logger.info(f"Returning {len(flight_updates)} XContest flight updates")
        return flight_updates


# Create a singleton instance
xcontest_service = XContestService()