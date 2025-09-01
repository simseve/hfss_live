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
from database.models import DeviceRegistration, Flight
from database.db_conf import get_db
from redis_queue_system.redis_queue import redis_queue, QUEUE_NAMES
from config import settings

logger = logging.getLogger(__name__)


class JT808Processor:
    """Process JT808 GPS data with device validation and queueing"""
    
    def __init__(self):
        self.device_cache = {}  # Cache validated devices
        self.flight_cache = {}  # Cache flight IDs for devices
        
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
                
            # Check if we have cached validation
            if device_id in self.device_cache:
                cached = self.device_cache[device_id]
                # Check if cache is still valid (15 minutes)
                if (datetime.now(timezone.utc) - cached['timestamp']).seconds < 900:
                    return await self._queue_data(parsed_data, cached['registration'])
            
            # Validate device registration
            registration = self._validate_device(device_id)
            if not registration:
                logger.warning(f"Device {device_id} not registered or inactive")
                return False
                
            # Cache the validation
            self.device_cache[device_id] = {
                'registration': registration,
                'timestamp': datetime.now(timezone.utc)
            }
            
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
            
            # Get or create flight ID
            flight_info = await self._get_or_create_flight(registration)
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
    
    async def _get_or_create_flight(self, registration: Dict[str, Any]) -> Optional[str]:
        """
        Get existing flight or create new one for device
        """
        device_id = registration['device_id']
        
        # Check cache first
        if device_id in self.flight_cache:
            cached = self.flight_cache[device_id]
            # Use cached flight if less than 1 hour old
            if (datetime.now(timezone.utc) - cached['timestamp']).seconds < 3600:
                return {'uuid': cached.get('flight_uuid'), 'id': cached.get('flight_id')}
        
        db = next(get_db())
        try:
            # Create flight ID using same pattern as Flymaster
            # Format: {source}-{pilot_id}-{race_id}-{device_id}
            device_type = registration.get('device_type', 'tk905b')
            source_type = f"{device_type}_live"  # Add _live suffix for WebSocket filtering
            flight_id = f"{device_type}-{registration['pilot_id']}-{registration['race_id']}-{device_id}"
            
            # Check if we already have this flight
            flight = db.query(Flight).filter(
                Flight.flight_id == flight_id,
                Flight.source == source_type
            ).first()
            
            if not flight:
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
                logger.info(f"Created new flight for device {device_id}: {flight.id}")
            
            flight_uuid = str(flight.id)
            
            # Cache both the UUID and the string flight_id
            self.flight_cache[device_id] = {
                'flight_id': flight_id,  # String identifier
                'flight_uuid': flight_uuid,  # UUID
                'timestamp': datetime.now(timezone.utc)
            }
            
            return {'uuid': flight_uuid, 'id': flight_id}
            
        except Exception as e:
            logger.error(f"Error getting/creating flight: {e}")
            return None
        finally:
            db.close()


# Global processor instance
jt808_processor = JT808Processor()