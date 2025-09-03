"""
JT808 GPS data processor with device registration and Redis queueing
"""
import logging
import jwt
import uuid
import json
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from database.models import DeviceRegistration, Flight, Race
from database.db_conf import get_db
from utils.flight_separator import FlightSeparator
from redis_queue_system.redis_queue import redis_queue, QUEUE_NAMES
from config import settings
import redis.asyncio as redis
import pickle

logger = logging.getLogger(__name__)


class JT808Processor:
    """Process JT808 GPS data with device validation and Redis caching"""
    
    # Redis cache key prefixes and TTLs
    CACHE_PREFIX_DEVICE = "jt808:device:"
    CACHE_PREFIX_FLIGHT = "jt808:flight:"
    CACHE_PREFIX_PILOT = "jt808:pilot:"
    CACHE_TTL_DEVICE = 900  # 15 minutes
    CACHE_TTL_FLIGHT = 3600  # 1 hour
    CACHE_TTL_PILOT = 900  # 15 minutes
    REVALIDATE_INTERVAL = 300  # Re-validate every 5 minutes
    
    def __init__(self):
        self.redis_client = None
        self._init_redis()
        
    def _init_redis(self):
        """Initialize Redis connection"""
        try:
            redis_url = settings.get_redis_url()
            self.redis_client = redis.from_url(redis_url, decode_responses=False)
            logger.info(f"JT808 processor connected to Redis at {redis_url}")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            # Fall back to in-memory cache if Redis fails
            self.fallback_cache = {}
    
    async def _get_cached_registration(self, device_id: str) -> Optional[Dict]:
        """Get cached device registration from Redis"""
        if not self.redis_client:
            return None
            
        try:
            cache_key = f"{self.CACHE_PREFIX_DEVICE}{device_id}"
            cached_data = await self.redis_client.get(cache_key)
            if cached_data:
                # Also get the timestamp to calculate age
                timestamp_key = f"{cache_key}:timestamp"
                timestamp_data = await self.redis_client.get(timestamp_key)
                
                registration = pickle.loads(cached_data)
                cache_age = 0
                if timestamp_data:
                    cached_time = float(timestamp_data)
                    cache_age = (datetime.now(timezone.utc).timestamp() - cached_time)
                
                return {
                    'registration': registration,
                    'cache_age': cache_age
                }
        except Exception as e:
            logger.error(f"Error getting cached registration for {device_id}: {e}")
        return None
    
    async def _get_cached_flight(self, device_id: str) -> Optional[Dict]:
        """Get cached flight info from Redis"""
        if not self.redis_client:
            return None
            
        try:
            cache_key = f"{self.CACHE_PREFIX_FLIGHT}{device_id}"
            cached_data = await self.redis_client.get(cache_key)
            if cached_data:
                return pickle.loads(cached_data)
        except Exception as e:
            logger.error(f"Error getting cached flight for {device_id}: {e}")
        return None
    
    async def _cache_flight(self, device_id: str, flight_id: str, flight_uuid: str):
        """Cache flight info in Redis"""
        if not self.redis_client:
            return
            
        try:
            cache_key = f"{self.CACHE_PREFIX_FLIGHT}{device_id}"
            flight_data = {
                'flight_id': flight_id,
                'flight_uuid': flight_uuid,
                'id': flight_id,
                'uuid': flight_uuid
            }
            
            await self.redis_client.setex(
                cache_key,
                self.CACHE_TTL_FLIGHT,
                pickle.dumps(flight_data)
            )
            logger.debug(f"Cached flight {flight_id} for device {device_id} in Redis")
        except Exception as e:
            logger.error(f"Error caching flight for {device_id}: {e}")
    
    async def _cache_registration(self, device_id: str, registration: Dict):
        """Cache device registration in Redis"""
        if not self.redis_client:
            return
            
        try:
            cache_key = f"{self.CACHE_PREFIX_DEVICE}{device_id}"
            timestamp_key = f"{cache_key}:timestamp"
            pilot_key = f"{self.CACHE_PREFIX_PILOT}{device_id}"
            
            # Store registration with TTL
            await self.redis_client.setex(
                cache_key,
                self.CACHE_TTL_DEVICE,
                pickle.dumps(registration)
            )
            
            # Store timestamp
            await self.redis_client.setex(
                timestamp_key,
                self.CACHE_TTL_DEVICE,
                str(datetime.now(timezone.utc).timestamp())
            )
            
            # Store pilot ID for change detection
            if registration.get('pilot_id'):
                await self.redis_client.setex(
                    pilot_key,
                    self.CACHE_TTL_PILOT,
                    registration['pilot_id']
                )
            
            logger.debug(f"Cached registration for device {device_id} in Redis")
        except Exception as e:
            logger.error(f"Error caching registration for {device_id}: {e}")
    
    async def _invalidate_device_caches(self, device_id: str):
        """Invalidate all Redis caches for a device when reassignment is detected"""
        if not self.redis_client:
            # Fallback to clearing in-memory cache
            if device_id in self.fallback_cache:
                del self.fallback_cache[device_id]
            return
            
        try:
            keys_to_delete = [
                f"{self.CACHE_PREFIX_DEVICE}{device_id}",
                f"{self.CACHE_PREFIX_FLIGHT}{device_id}",
                f"{self.CACHE_PREFIX_PILOT}{device_id}"
            ]
            if keys_to_delete:
                await self.redis_client.delete(*keys_to_delete)
                logger.info(f"Invalidated all Redis caches for device {device_id}")
        except Exception as e:
            logger.error(f"Error invalidating Redis cache for {device_id}: {e}")
    
    async def process_gps_data(self, parsed_data: Dict[str, Any]) -> bool:
        """
        Process GPS data from JT808 device
        Returns True if data was queued successfully
        """
        try:
            # Extract device ID from parsed data
            device_id = parsed_data.get('device_id')
            if not device_id:
                logger.warning("No device ID in parsed data")
                return False
                
            # Check Redis cache for device registration
            cached_registration = await self._get_cached_registration(device_id)
            if cached_registration:
                # Check if we should revalidate (every 5 minutes)
                cache_age = cached_registration.get('cache_age', 0)
                if cache_age > self.REVALIDATE_INTERVAL:
                    # Re-validate from database
                    fresh_registration = self._validate_device(device_id)
                    if not fresh_registration:
                        # Device no longer valid
                        await self._invalidate_device_caches(device_id)
                        return False
                    
                    # Check if pilot changed
                    old_pilot = cached_registration['registration'].get('pilot_id')
                    new_pilot = fresh_registration.get('pilot_id')
                    if old_pilot != new_pilot:
                        logger.warning(f"Device {device_id} reassigned from pilot {old_pilot} to {new_pilot} - creating new flight")
                        await self._invalidate_device_caches(device_id)
                    
                    # Update cache with fresh data
                    await self._cache_registration(device_id, fresh_registration)
                    return await self._queue_data(parsed_data, fresh_registration)
                
                # Use cached registration
                return await self._queue_data(parsed_data, cached_registration['registration'])
            
            # Validate device registration
            registration = self._validate_device(device_id)
            if not registration:
                logger.warning(f"Device {device_id} not registered or inactive")
                return False
                
            # Cache the validation in Redis
            await self._cache_registration(device_id, registration)
            
            # Queue the data
            return await self._queue_data(parsed_data, registration)
            
        except Exception as e:
            logger.error(f"Error processing GPS data: {e}")
            return False
    
    def _validate_device(self, device_id: str) -> Optional[Dict[str, Any]]:
        """
        Validate device registration in database
        Returns registration data if valid, None otherwise
        """
        db = next(get_db())
        try:
            # Query device registration
            # For JT808 devices, the device_id might be the terminal phone number
            # Accept any device type - JT808 protocol can be used by various tracker types
            registration = db.query(DeviceRegistration).filter(
                DeviceRegistration.serial_number == device_id,
                DeviceRegistration.is_active == True
            ).first()
            
            if not registration:
                # Try alternative lookup - device might be registered with different format
                # Terminal phone numbers might have leading zeros or country code
                alt_device_id = device_id.lstrip('0')
                registration = db.query(DeviceRegistration).filter(
                    DeviceRegistration.serial_number == alt_device_id,
                    DeviceRegistration.device_type.in_(['jt808', 'gps_tracker']),
                    DeviceRegistration.is_active == True
                ).first()
            
            if not registration:
                return None
                
            # Validate the stored token
            try:
                token_data = jwt.decode(
                    registration.pilot_token,
                    settings.SECRET_KEY,
                    algorithms=["HS256"],
                    options={"verify_aud": False, "verify_iss": False}
                )
                
                # Check if token is expired
                if 'exp' in token_data and token_data['exp'] < datetime.now(timezone.utc).timestamp():
                    # Token expired - deactivate registration
                    registration.is_active = False
                    registration.updated_at = datetime.now(timezone.utc)
                    db.commit()
                    logger.warning(f"Token expired for device {device_id}")
                    return None
                    
                # Return registration data
                return {
                    'device_id': device_id,
                    'race_id': registration.race_id,
                    'pilot_id': registration.pilot_id,
                    'pilot_name': registration.pilot_name,
                    'race_uuid': str(registration.race_uuid),
                    'token_data': token_data
                }
                
            except jwt.PyJWTError as e:
                logger.error(f"Invalid token for device {device_id}: {e}")
                return None
                
        finally:
            db.close()
    
    async def _queue_data(self, parsed_data: Dict[str, Any], registration: Dict[str, Any]) -> bool:
        """
        Queue GPS data to Redis for processing
        """
        try:
            # Only queue location reports with valid GPS data
            if parsed_data.get('msg_id') != 0x0200:
                logger.debug(f"Skipping non-location message: {parsed_data.get('message')}")
                return True  # Return True as it's successfully "processed"
                
            # Check if we have GPS coordinates
            if not parsed_data.get('latitude') or not parsed_data.get('longitude'):
                logger.warning("Location report missing GPS coordinates")
                return False
            
            # Prepare current point info for flight separator
            current_point = {
                'datetime': datetime.now(timezone.utc),
                'lat': parsed_data['latitude'],
                'lon': parsed_data['longitude'],
                'elevation': parsed_data.get('altitude', 0)
            }
            
            # Get or create flight ID (may create new flight based on separation logic)
            flight_info = await self._get_or_create_flight(registration, current_point)
            if not flight_info:
                logger.error(f"Could not get flight ID for device {registration['device_id']}")
                return False
            
            # Prepare track point data for Redis queue - match LiveTrackPoint format
            # Parse GPS time or use current time
            gps_time_str = parsed_data.get('gps_time')
            if gps_time_str:
                # Parse the GPS time and add UTC timezone
                try:
                    # GPS time comes as "2025-09-01T13:35:00" without timezone
                    dt = datetime.fromisoformat(gps_time_str).replace(tzinfo=timezone.utc)
                    timestamp = dt.isoformat()
                except:
                    timestamp = datetime.now(timezone.utc).isoformat()
            else:
                timestamp = datetime.now(timezone.utc).isoformat()
                
            # The processor expects these exact field names
            track_point = {
                'datetime': timestamp,
                'flight_uuid': flight_info['uuid'],  # UUID as string
                'flight_id': flight_info['id'],       # String identifier for triggers
                'lat': parsed_data['latitude'],
                'lon': parsed_data['longitude'],
                'elevation': parsed_data.get('altitude', 0),
                'device_id': registration['device_id'],
                'barometric_altitude': None  # JT808 doesn't provide this
            }
            
            # Queue to Redis
            queued = await redis_queue.queue_points(
                QUEUE_NAMES['live'],
                [track_point],  # Queue as list
                priority=1  # High priority for live tracking
            )
            
            if queued:
                logger.info(f"Queued GPS data for device {registration['device_id']}: "
                          f"lat={track_point['lat']:.6f}, lon={track_point['lon']:.6f}")
                return True
            else:
                logger.error(f"Failed to queue GPS data for device {registration['device_id']}")
                return False
                
        except Exception as e:
            logger.error(f"Error queueing GPS data: {e}")
            return False
    
    async def _get_or_create_flight(self, registration: Dict[str, Any], current_point: Optional[Dict] = None) -> Optional[str]:
        """
        Get existing flight or create new one for device
        """
        device_id = registration['device_id']
        
        # Check Redis cache first
        cached_flight = await self._get_cached_flight(device_id)
        if cached_flight:
            return cached_flight
        
        db = next(get_db())
        try:
            device_type = registration.get('device_type', 'tk905b')
            source_type = f"{device_type}_live"  # Add _live suffix for WebSocket filtering
            base_flight_id = f"{device_type}-{registration['pilot_id']}-{registration['race_id']}-{device_id}"
            
            # Get the most recent flight for this device
            latest_flight = db.query(Flight).filter(
                Flight.device_id == device_id,
                Flight.source == source_type,
                Flight.race_id == registration['race_id']
            ).order_by(Flight.created_at.desc()).first()
            
            # Check if we need a new flight
            should_create_new = False
            separation_reason = "no_previous_flight"
            
            if latest_flight:
                # Convert latest flight to dict format for separator
                last_flight_info = {
                    'last_fix': latest_flight.last_fix,
                    'created_at': latest_flight.created_at,
                    'flight_state': latest_flight.flight_state
                }
                
                # Get race timezone if available
                race = db.query(Race).filter(Race.race_id == registration['race_id']).first()
                race_timezone = race.timezone if race and race.timezone else "UTC"
                
                # Check if we should create a new flight
                if current_point:
                    should_create_new, separation_reason = FlightSeparator.should_create_new_flight(
                        device_id=device_id,
                        current_point=current_point,
                        last_flight=last_flight_info,
                        race_timezone=race_timezone
                    )
                else:
                    # If no current point provided, continue with existing flight
                    should_create_new = False
            else:
                should_create_new = True
            
            if should_create_new:
                # Generate new flight_id with suffix based on reason
                suffix = FlightSeparator.get_flight_id_suffix(separation_reason)
                flight_id = f"{base_flight_id}-{suffix}"
                
                # Check if this specific flight_id already exists (shouldn't happen but just in case)
                existing = db.query(Flight).filter(Flight.flight_id == flight_id).first()
                if existing:
                    flight = existing
                    logger.info(f"Using existing flight with ID {flight_id}")
                else:
                    # Create new flight using registration data (same as Flymaster)
                    flight = Flight(
                        flight_id=flight_id,
                        race_uuid=registration['race_uuid'],
                        race_id=registration['race_id'],
                        pilot_id=registration['pilot_id'],
                        pilot_name=registration['pilot_name'],
                        source=source_type,
                        device_id=device_id,
                        created_at=datetime.now(timezone.utc)
                    )
                    db.add(flight)
                    db.commit()
                    logger.info(f"Created new flight for device {device_id}: {flight.id} (reason: {separation_reason})")
            else:
                # Use existing flight
                flight = latest_flight
                flight_id = latest_flight.flight_id
                logger.debug(f"Continuing with existing flight {flight_id} for device {device_id}")
            
            flight_uuid = str(flight.id)
            
            # Cache flight info in Redis
            await self._cache_flight(device_id, flight_id, flight_uuid)
            
            return {'uuid': flight_uuid, 'id': flight_id}
            
        except Exception as e:
            logger.error(f"Error getting/creating flight: {e}")
            return None
        finally:
            db.close()


# Global processor instance
jt808_processor = JT808Processor()