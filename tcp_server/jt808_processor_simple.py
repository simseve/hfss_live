#!/usr/bin/env python3
"""
Simplified JT808 processor - flight separation moved to queue processor
This ensures consistency with Flymaster processing
"""

import asyncio
import struct
import logging
import json
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from database.models import DeviceRegistration
from database.db_conf import get_db
from redis_queue_system.redis_queue import redis_queue, QUEUE_NAMES
from config import settings

logger = logging.getLogger(__name__)

class JT808ProcessorSimple:
    """
    Simplified JT808 GPS tracker protocol processor
    Flight separation logic moved to queue processor for consistency
    """
    
    def __init__(self):
        self.device_cache = {}  # Cache device registrations
    
    async def process_message(self, data: bytes, client_address: str) -> Optional[bytes]:
        """Process incoming JT808 message - simplified version"""
        if len(data) < 12:
            return None
            
        try:
            # Parse message ID and device ID
            message_id = struct.unpack('>H', data[1:3])[0]
            device_id_bytes = data[5:11]
            device_id = ''.join(f'{b:02d}' for b in device_id_bytes).lstrip('0')
            
            # Handle location report (0x0200)
            if message_id == 0x0200:
                return await self._handle_location_simple(data, device_id)
                
            # Simple ACK for other messages
            return self._create_ack(data)
            
        except Exception as e:
            logger.error(f"Error processing JT808 message: {e}")
            return None
    
    async def _handle_location_simple(self, data: bytes, device_id: str) -> Optional[bytes]:
        """Simplified location handler - no flight separation logic"""
        try:
            # Parse GPS data (same as before)
            parsed_data = self._parse_location_data(data)
            if not parsed_data:
                return self._create_ack(data)
            
            # Get device registration
            registration = await self._get_device_registration(device_id)
            if not registration:
                logger.warning(f"Device {device_id} not registered")
                return self._create_ack(data)
            
            # Prepare point for queue with basic flight info
            # Let the queue processor handle flight separation
            device_type = registration.get('device_type', 'tk905b')
            base_flight_id = f"{device_type}-{registration['pilot_id']}-{registration['race_id']}-{device_id}"
            
            # Parse GPS time or use current time
            gps_time_str = parsed_data.get('gps_time')
            if gps_time_str:
                try:
                    dt = datetime.fromisoformat(gps_time_str).replace(tzinfo=timezone.utc)
                    timestamp = dt.isoformat()
                except:
                    timestamp = datetime.now(timezone.utc).isoformat()
            else:
                timestamp = datetime.now(timezone.utc).isoformat()
            
            # Queue point with basic info - queue processor will handle flight creation/separation
            track_point = {
                'datetime': timestamp,
                'lat': parsed_data['latitude'],
                'lon': parsed_data['longitude'],
                'elevation': parsed_data.get('altitude', 0),
                'device_id': device_id,
                'device_type': device_type,
                'barometric_altitude': None,
                # Include registration info for flight creation
                'race_id': registration['race_id'],
                'race_uuid': registration['race_uuid'],
                'pilot_id': registration['pilot_id'],
                'pilot_name': registration['pilot_name'],
                'base_flight_id': base_flight_id  # Base ID without suffix
            }
            
            # Queue to Redis
            queued = await redis_queue.queue_points(
                QUEUE_NAMES['live'],
                [track_point],
                batch_size=100
            )
            
            if queued:
                logger.debug(f"Queued point from device {device_id}")
            else:
                logger.error(f"Failed to queue point from device {device_id}")
            
            return self._create_ack(data)
            
        except Exception as e:
            logger.error(f"Error handling location: {e}")
            return self._create_ack(data)
    
    async def _get_device_registration(self, device_id: str) -> Optional[Dict[str, Any]]:
        """Get device registration with caching"""
        # Check cache
        if device_id in self.device_cache:
            cached = self.device_cache[device_id]
            if (datetime.now(timezone.utc) - cached['timestamp']).seconds < 3600:
                return cached['data']
        
        # Query database
        db = next(get_db())
        try:
            registration = db.query(DeviceRegistration).filter(
                DeviceRegistration.device_id == device_id,
                DeviceRegistration.is_active == True
            ).first()
            
            if registration:
                reg_data = {
                    'device_id': device_id,
                    'device_type': registration.device_type,
                    'race_id': registration.race_id,
                    'race_uuid': registration.race_uuid,
                    'pilot_id': registration.pilot_id,
                    'pilot_name': registration.pilot_name
                }
                
                # Cache it
                self.device_cache[device_id] = {
                    'data': reg_data,
                    'timestamp': datetime.now(timezone.utc)
                }
                
                return reg_data
                
            return None
            
        except Exception as e:
            logger.error(f"Error getting device registration: {e}")
            return None
        finally:
            db.close()
    
    def _parse_location_data(self, data: bytes) -> Optional[Dict]:
        """Parse location data from JT808 message"""
        try:
            if len(data) < 40:
                return None
            
            # Parse status and GPS data (same as original)
            status = struct.unpack('>I', data[13:17])[0]
            lat_raw = struct.unpack('>I', data[17:21])[0]
            lon_raw = struct.unpack('>I', data[21:25])[0]
            altitude = struct.unpack('>H', data[25:27])[0]
            
            # Convert coordinates
            latitude = lat_raw / 1000000.0
            longitude = lon_raw / 1000000.0
            
            # Parse timestamp if available
            gps_time = None
            if len(data) >= 33:
                try:
                    year = 2000 + ((data[27] >> 4) * 10 + (data[27] & 0x0F))
                    month = ((data[28] >> 4) * 10 + (data[28] & 0x0F))
                    day = ((data[29] >> 4) * 10 + (data[29] & 0x0F))
                    hour = ((data[30] >> 4) * 10 + (data[30] & 0x0F))
                    minute = ((data[31] >> 4) * 10 + (data[31] & 0x0F))
                    second = ((data[32] >> 4) * 10 + (data[32] & 0x0F))
                    
                    gps_time = f"{year:04d}-{month:02d}-{day:02d}T{hour:02d}:{minute:02d}:{second:02d}"
                except:
                    pass
            
            return {
                'latitude': latitude,
                'longitude': longitude,
                'altitude': altitude,
                'gps_time': gps_time,
                'status': status
            }
            
        except Exception as e:
            logger.error(f"Error parsing location data: {e}")
            return None
    
    def _create_ack(self, original_data: bytes) -> bytes:
        """Create acknowledgment message"""
        if len(original_data) < 12:
            return b''
        
        # Simple ACK: copy header, set message ID to 0x8001
        ack = bytearray(original_data[:12])
        ack[1:3] = struct.pack('>H', 0x8001)  # ACK message ID
        
        # Add checksum
        checksum = sum(ack[1:-1]) & 0xFF
        ack.append(checksum)
        
        return bytes(ack)