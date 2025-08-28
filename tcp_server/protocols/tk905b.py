"""
TK905B Watch Protocol Handler
Supports single and batch location updates
"""
from typing import Dict, Any, Optional, List
from datetime import datetime
import re
import logging
from .base import BaseProtocolHandler

logger = logging.getLogger(__name__)


class TK905BProtocolHandler(BaseProtocolHandler):
    """Handler for TK905B watch protocol (3G*ID*LENGTH*DATA format)"""
    
    # Protocol patterns
    WATCH_PATTERN = re.compile(r'^\[(3G|ZJ|SG)\*([0-9]+)\*([0-9A-Fa-f]{4})\*(.+)\]$')
    
    # Response codes
    RESPONSE_OK = "OK"
    RESPONSE_FAIL = "FAIL"
    RESPONSE_ERROR = "ERROR"
    
    def get_protocol_name(self) -> str:
        return "TK905B"
    
    def can_handle(self, data: str) -> bool:
        """Check if this is a TK905B watch protocol message"""
        return bool(self.WATCH_PATTERN.match(data))
    
    def parse_message(self, data: str) -> Optional[Dict[str, Any]]:
        """Parse TK905B watch protocol message"""
        match = self.WATCH_PATTERN.match(data)
        if not match:
            return None
            
        protocol_type = match.group(1)  # 3G, ZJ, or SG
        device_id = match.group(2)
        length = match.group(3)
        command_data = match.group(4)
        
        # Store device ID
        if not self.device_id:
            self.device_id = device_id
            
        # Parse command and data
        parts = command_data.split(',')
        command = parts[0]
        
        # Route to specific command handler
        if command in ['UD2', 'UD', 'UD_LBS', 'UD_WIFI']:
            return self._parse_location(device_id, parts, data)
        elif command == 'UD3':
            return self._parse_batch_location(device_id, parts, data)
        elif command in ['LK', 'HEART']:
            return self._parse_heartbeat(device_id, parts, data)
        elif command == 'AL':
            return self._parse_alarm(device_id, parts, data)
        elif command == 'TKQ':
            return self._parse_voice_message(device_id, parts, data)
        elif command == 'TKQ2':
            return self._parse_image_message(device_id, parts, data)
        else:
            # Unknown command, return basic info
            return {
                'protocol': 'watch',
                'device_id': device_id,
                'command': command,
                'data': parts[1:] if len(parts) > 1 else [],
                'raw': data
            }
    
    def _parse_location(self, device_id: str, parts: List[str], raw: str) -> Optional[Dict[str, Any]]:
        """Parse single location update (UD2/UD format)"""
        if len(parts) < 8:
            return None
            
        try:
            # Parse date and time (DDMMYY,HHMMSS)
            date_str = parts[1]
            time_str = parts[2]
            dt = datetime.strptime(f"{date_str}{time_str}", "%d%m%y%H%M%S")
            
            # GPS validity (A=valid, V=invalid)
            valid = parts[3] == 'A'
            
            # Parse coordinates
            lat = self.parse_nmea_coordinate(parts[4], is_longitude=False)
            if parts[5] == 'S':
                lat = -lat
                
            lon = self.parse_nmea_coordinate(parts[6], is_longitude=True)
            if parts[7] == 'W':
                lon = -lon
                
            # Validate coordinates
            if not self.validate_coordinates(lat, lon):
                logger.warning(f"Invalid coordinates: {lat}, {lon}")
                valid = False
                
            result = {
                'protocol': 'watch',
                'device_id': device_id,
                'command': 'location',
                'latitude': lat,
                'longitude': lon,
                'timestamp': dt,
                'valid': valid,
                'raw': raw
            }
            
            # Parse optional fields
            if len(parts) > 8 and parts[8]:
                result['speed'] = float(parts[8])  # km/h
            if len(parts) > 9 and parts[9]:
                result['heading'] = float(parts[9])  # degrees
            if len(parts) > 10 and parts[10]:
                result['altitude'] = float(parts[10])  # meters
            if len(parts) > 11 and parts[11]:
                result['satellites'] = int(parts[11])
            if len(parts) > 12 and parts[12]:
                result['gsm_signal'] = int(parts[12])
            if len(parts) > 13 and parts[13]:
                result['battery'] = int(parts[13])  # percentage
                
            # Cell tower info (if present)
            if len(parts) > 20:
                result['cell_info'] = {
                    'mcc': parts[17] if len(parts) > 17 else None,
                    'mnc': parts[18] if len(parts) > 18 else None,
                    'lac': parts[19] if len(parts) > 19 else None,
                    'cell_id': parts[20] if len(parts) > 20 else None
                }
                
            return result
            
        except (ValueError, IndexError) as e:
            logger.error(f"Error parsing location: {e}")
            return None
    
    def _parse_batch_location(self, device_id: str, parts: List[str], raw: str) -> Optional[Dict[str, Any]]:
        """
        Parse batch location update (UD3 format)
        Format: UD3,COUNT,RECORD1;RECORD2;...
        Each record: DATE,TIME,STATUS,LAT,LAT_DIR,LON,LON_DIR,SPEED,HEADING,ALT[,SATS,GSM,BATTERY]
        """
        if len(parts) < 3:
            return None
            
        try:
            count = int(parts[1])
            # Rejoin the rest as it might contain commas
            batch_data = ','.join(parts[2:])
            records = batch_data.split(';')
            
            if len(records) != count:
                logger.warning(f"UD3 count mismatch: expected {count}, got {len(records)}")
            
            points = []
            for record_str in records:
                record = record_str.split(',')
                if len(record) < 10:
                    continue
                    
                try:
                    # Parse timestamp
                    dt = datetime.strptime(f"{record[0]}{record[1]}", "%d%m%y%H%M%S")
                    
                    # GPS validity
                    valid = record[2] == 'A'
                    
                    # Parse coordinates
                    lat = self.parse_nmea_coordinate(record[3], is_longitude=False)
                    if record[4] == 'S':
                        lat = -lat
                        
                    lon = self.parse_nmea_coordinate(record[5], is_longitude=True)
                    if record[6] == 'W':
                        lon = -lon
                        
                    point = {
                        'latitude': lat,
                        'longitude': lon,
                        'timestamp': dt,
                        'valid': valid,
                        'speed': float(record[7]) if record[7] else 0,
                        'heading': float(record[8]) if record[8] else 0,
                        'altitude': float(record[9]) if record[9] else 0
                    }
                    
                    # Optional fields
                    if len(record) > 10:
                        point['satellites'] = int(record[10])
                    if len(record) > 11:
                        point['gsm_signal'] = int(record[11])
                    if len(record) > 12:
                        point['battery'] = int(record[12])
                        
                    if self.validate_point(point):
                        points.append(point)
                        
                except (ValueError, IndexError) as e:
                    logger.debug(f"Skipping invalid record in batch: {e}")
                    continue
            
            return {
                'protocol': 'watch',
                'device_id': device_id,
                'command': 'batch_location',
                'batch': True,
                'count': len(points),
                'points': points,
                'raw': raw
            }
            
        except (ValueError, IndexError) as e:
            logger.error(f"Error parsing UD3 batch: {e}")
            return None
    
    def _parse_heartbeat(self, device_id: str, parts: List[str], raw: str) -> Dict[str, Any]:
        """Parse heartbeat/login message (LK/HEART)"""
        result = {
            'protocol': 'watch',
            'device_id': device_id,
            'command': 'heartbeat',
            'raw': raw
        }
        
        # LK format: LK,steps,rolls,battery
        if len(parts) > 3:
            result['steps'] = int(parts[1]) if parts[1] else 0
            result['rolls'] = int(parts[2]) if parts[2] else 0
            result['battery'] = int(parts[3]) if parts[3] else 0
            
        return result
    
    def _parse_alarm(self, device_id: str, parts: List[str], raw: str) -> Dict[str, Any]:
        """Parse alarm message"""
        alarm_types = {
            '01': 'sos',
            '02': 'low_battery',
            '03': 'offline',
            '04': 'shock',
            '05': 'fence_in',
            '06': 'fence_out'
        }
        
        result = {
            'protocol': 'watch',
            'device_id': device_id,
            'command': 'alarm',
            'raw': raw
        }
        
        if len(parts) > 1:
            alarm_code = parts[1]
            result['alarm_type'] = alarm_types.get(alarm_code, f'unknown_{alarm_code}')
            
        if len(parts) > 2:
            result['battery'] = int(parts[2])
            
        return result
    
    def _parse_voice_message(self, device_id: str, parts: List[str], raw: str) -> Dict[str, Any]:
        """Parse voice message metadata"""
        return {
            'protocol': 'watch',
            'device_id': device_id,
            'command': 'voice',
            'duration': int(parts[1]) if len(parts) > 1 else 0,
            'raw': raw
        }
    
    def _parse_image_message(self, device_id: str, parts: List[str], raw: str) -> Dict[str, Any]:
        """Parse image message metadata"""
        return {
            'protocol': 'watch',
            'device_id': device_id,
            'command': 'image',
            'size': int(parts[1]) if len(parts) > 1 else 0,
            'raw': raw
        }
    
    def create_response(self, parsed_data: Dict[str, Any], success: bool = True) -> str:
        """Create response message for TK905B"""
        if not parsed_data:
            return ""
            
        device_id = parsed_data.get('device_id', self.device_id)
        if not device_id:
            return ""
            
        # Determine response based on command
        command = parsed_data.get('command', '')
        
        if command == 'heartbeat':
            # Heartbeat response can include server commands
            response_data = self.RESPONSE_OK
        elif command in ['location', 'batch_location']:
            # Location acknowledgment
            response_data = self.RESPONSE_OK if success else self.RESPONSE_FAIL
        elif command == 'alarm':
            # Alarm acknowledgment
            response_data = "AL"  # Acknowledge alarm
        else:
            # Generic response
            response_data = self.RESPONSE_OK if success else self.RESPONSE_ERROR
            
        # Format: [ID*LENGTH*DATA]
        length = f"{len(response_data):04X}"
        return f"[{device_id}*{length}*{response_data}]"
    
    def send_command(self, device_id: str, command: str, params: List[str] = None) -> str:
        """
        Create a command to send to the device
        Common commands:
        - UPLOAD,interval - Set upload interval (seconds)
        - LZ,language,timezone - Set language and timezone
        - FACTORY - Factory reset
        - POWEROFF - Power off device
        - RESET - Restart device
        - TS - Take screenshot
        - CR - Check location immediately
        """
        if params:
            command_data = f"{command},{','.join(params)}"
        else:
            command_data = command
            
        length = f"{len(command_data):04X}"
        return f"[{device_id}*{length}*{command_data}]"