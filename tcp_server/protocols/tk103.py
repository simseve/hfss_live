"""
TK103 Protocol Handler
Classic GPS tracker protocol
"""
from typing import Dict, Any, Optional, List
from datetime import datetime
import re
import logging
from .base import BaseProtocolHandler

logger = logging.getLogger(__name__)


class TK103ProtocolHandler(BaseProtocolHandler):
    """Handler for TK103 protocol (parenthesis format)"""
    
    # Protocol pattern
    TK103_PATTERN = re.compile(r'^\((\d+),(BR\d+|BP\d+),.*\)$')
    
    def get_protocol_name(self) -> str:
        return "TK103"
    
    def can_handle(self, data: str) -> bool:
        """Check if this is a TK103 protocol message"""
        return bool(self.TK103_PATTERN.match(data))
    
    def parse_message(self, data: str) -> Optional[Dict[str, Any]]:
        """Parse TK103 protocol message"""
        match = self.TK103_PATTERN.match(data)
        if not match:
            return None
            
        # Remove parentheses and split
        content = data[1:-1]  # Remove ( and )
        parts = content.split(',')
        
        if len(parts) < 3:
            return None
            
        device_id = parts[0]
        command = parts[1]
        
        # Store device ID
        if not self.device_id:
            self.device_id = device_id
            
        # Route based on command
        if command.startswith('BR'):
            return self._parse_location(device_id, command, parts, data)
        elif command == 'BP05':
            return self._parse_login(device_id, parts, data)
        elif command == 'BP00':
            return self._parse_heartbeat(device_id, parts, data)
        elif command.startswith('BO'):
            return self._parse_alarm(device_id, command, parts, data)
        else:
            return {
                'protocol': 'tk103',
                'device_id': device_id,
                'command': command,
                'data': parts[2:],
                'raw': data
            }
    
    def _parse_location(self, device_id: str, command: str, parts: List[str], raw: str) -> Optional[Dict[str, Any]]:
        """
        Parse location message
        Format: (ID,BR00,YYMMDD,A/V,DDMM.MMMM,N/S,DDDMM.MMMM,E/W,SPD,HHMMSS,HDG[,ALT])
        """
        if len(parts) < 10:
            return None
            
        try:
            # Parse date and time
            date_str = parts[2]  # YYMMDD
            time_str = parts[9]  # HHMMSS
            
            # Handle different date formats
            if len(date_str) == 6:
                # YYMMDD format
                dt = datetime.strptime(f"{date_str}{time_str}", "%y%m%d%H%M%S")
            else:
                # DDMMYY format
                dt = datetime.strptime(f"{date_str}{time_str}", "%d%m%y%H%M%S")
                
            # GPS validity
            valid = parts[3] == 'A'
            
            # Parse latitude (DDMM.MMMM format)
            lat_str = parts[4]
            lat_match = re.match(r'(\d{2})(\d{2}\.\d+)', lat_str)
            if lat_match:
                lat_deg = float(lat_match.group(1))
                lat_min = float(lat_match.group(2))
                lat = lat_deg + (lat_min / 60.0)
                if parts[5] == 'S':
                    lat = -lat
            else:
                lat = float(lat_str)
                valid = False
                
            # Parse longitude (DDDMM.MMMM format)
            lon_str = parts[6]
            lon_match = re.match(r'(\d{3})(\d{2}\.\d+)', lon_str)
            if not lon_match:
                lon_match = re.match(r'(\d{2})(\d{2}\.\d+)', lon_str)
                
            if lon_match:
                lon_deg = float(lon_match.group(1))
                lon_min = float(lon_match.group(2))
                lon = lon_deg + (lon_min / 60.0)
                if parts[7] == 'W':
                    lon = -lon
            else:
                lon = float(lon_str)
                valid = False
                
            # Validate coordinates
            if not self.validate_coordinates(lat, lon):
                logger.warning(f"Invalid coordinates: {lat}, {lon}")
                valid = False
                
            result = {
                'protocol': 'tk103',
                'device_id': device_id,
                'command': 'location',
                'latitude': lat,
                'longitude': lon,
                'timestamp': dt,
                'valid': valid,
                'speed': float(parts[8]) if parts[8] else 0,  # km/h
                'heading': float(parts[10]) if len(parts) > 10 and parts[10] else 0,
                'raw': raw
            }
            
            # Optional altitude
            if len(parts) > 11 and parts[11]:
                result['altitude'] = float(parts[11])
                
            return result
            
        except (ValueError, IndexError) as e:
            logger.error(f"Error parsing TK103 location: {e}")
            return None
    
    def _parse_login(self, device_id: str, parts: List[str], raw: str) -> Dict[str, Any]:
        """Parse login message"""
        result = {
            'protocol': 'tk103',
            'device_id': device_id,
            'command': 'login',
            'raw': raw
        }
        
        # Extract IMEI if present
        if len(parts) > 2:
            result['imei'] = parts[2]
            
        return result
    
    def _parse_heartbeat(self, device_id: str, parts: List[str], raw: str) -> Dict[str, Any]:
        """Parse heartbeat message"""
        return {
            'protocol': 'tk103',
            'device_id': device_id,
            'command': 'heartbeat',
            'raw': raw
        }
    
    def _parse_alarm(self, device_id: str, command: str, parts: List[str], raw: str) -> Dict[str, Any]:
        """Parse alarm message"""
        alarm_types = {
            'BO01': 'sos',
            'BO02': 'power_cut',
            'BO03': 'shock',
            'BO04': 'fence_out',
            'BO05': 'fence_in',
            'BO06': 'overspeed',
            'BO07': 'movement',
            'BO08': 'low_battery'
        }
        
        result = {
            'protocol': 'tk103',
            'device_id': device_id,
            'command': 'alarm',
            'alarm_type': alarm_types.get(command, f'unknown_{command}'),
            'raw': raw
        }
        
        # Include location if present
        if len(parts) >= 10:
            location = self._parse_location(device_id, command, parts, raw)
            if location:
                result.update({
                    'latitude': location['latitude'],
                    'longitude': location['longitude'],
                    'timestamp': location['timestamp'],
                    'valid': location['valid']
                })
                
        return result
    
    def create_response(self, parsed_data: Dict[str, Any], success: bool = True) -> str:
        """Create response message for TK103"""
        if not parsed_data:
            return ""
            
        device_id = parsed_data.get('device_id', self.device_id)
        if not device_id:
            return ""
            
        command = parsed_data.get('command', '')
        
        # TK103 responses
        if command == 'login':
            return f"({device_id}AP05)"  # Accept login
        elif command == 'heartbeat':
            return f"({device_id}BP00HSO)"  # Heartbeat response
        elif command == 'location':
            return ""  # No response needed for location
        elif command == 'alarm':
            alarm_type = parsed_data.get('alarm_type', 'unknown')
            return f"({device_id}AS01{alarm_type})"  # Acknowledge alarm
        else:
            return ""  # No response for unknown commands
    
    def send_command(self, device_id: str, command: str, params: List[str] = None) -> str:
        """
        Create a command to send to the device
        Common commands:
        - APN - Set APN
        - SERVER - Set server IP and port
        - TIMER - Set update interval
        - RESTART - Restart device
        """
        # TK103 command format varies
        if command == "APN" and params:
            return f"({device_id}AP00{params[0]})"
        elif command == "SERVER" and len(params) >= 2:
            return f"({device_id}AP01{params[0]},{params[1]})"
        elif command == "TIMER" and params:
            return f"({device_id}AP02{params[0]})"
        elif command == "RESTART":
            return f"({device_id}AT00)"
        else:
            return ""