"""
Production-ready JT/T 808 Protocol Handler
Implements JT/T 808-2011/2013/2019 GPS tracker protocol
"""
import struct
import logging
from typing import Dict, Any, Optional, Tuple
from datetime import datetime
from .base import BaseProtocolHandler

logger = logging.getLogger(__name__)


class JT808ProductionHandler(BaseProtocolHandler):
    """
    Production JT/T 808 protocol handler with full message parsing
    """
    
    # Message IDs
    MSG_TERMINAL_RESPONSE = 0x0001
    MSG_HEARTBEAT = 0x0002
    MSG_TERMINAL_REGISTER = 0x0100
    MSG_TERMINAL_AUTH = 0x0102
    MSG_LOCATION_REPORT = 0x0200
    MSG_BATCH_LOCATION = 0x0704
    
    # Server response IDs
    MSG_SERVER_RESPONSE = 0x8001
    MSG_REGISTER_RESPONSE = 0x8100
    
    def get_protocol_name(self) -> str:
        return "JT808"
    
    def can_handle(self, data: str) -> bool:
        """Check if this is JT808 protocol data"""
        try:
            # Convert to bytes if needed
            if isinstance(data, str):
                if all(c in '0123456789abcdefABCDEF' for c in data.strip()):
                    raw = bytes.fromhex(data.strip())
                else:
                    raw = data.encode('latin-1', errors='ignore')
            else:
                raw = data
            
            # Check for 0x7E frame delimiters
            return len(raw) >= 2 and raw[0] == 0x7E and raw[-1] == 0x7E
            
        except Exception:
            return False
    
    def parse_message(self, data: str) -> Optional[Dict[str, Any]]:
        """Parse JT808 message with full protocol support"""
        try:
            # Convert to bytes
            if isinstance(data, str):
                if all(c in '0123456789abcdefABCDEF' for c in data.strip()):
                    raw = bytes.fromhex(data.strip())
                else:
                    raw = data.encode('latin-1', errors='ignore')
            else:
                raw = data
            
            # Verify frame
            if len(raw) < 12 or raw[0] != 0x7E or raw[-1] != 0x7E:
                logger.warning("Invalid JT808 frame")
                return None
            
            # Remove delimiters and unescape
            payload = self._unescape(raw[1:-1])
            
            # Parse header
            header, body_start = self._parse_header(payload)
            if not header:
                return None
            
            # Extract message body
            body = payload[body_start:body_start + header['body_length']]
            
            # Create result
            result = {
                'protocol': self.get_protocol_name(),
                'timestamp': datetime.now(),
                'raw_hex': raw.hex(),
                **header
            }
            
            # Parse body based on message type
            if header['msg_id'] == self.MSG_TERMINAL_REGISTER:
                self._parse_registration(body, result)
            elif header['msg_id'] == self.MSG_LOCATION_REPORT:
                self._parse_location(body, result)
            elif header['msg_id'] == self.MSG_HEARTBEAT:
                result['message'] = "Heartbeat"
            elif header['msg_id'] == self.MSG_TERMINAL_AUTH:
                self._parse_authentication(body, result)
            elif header['msg_id'] == self.MSG_BATCH_LOCATION:
                result['message'] = "Batch Location"
                result['valid'] = True
            
            return result
            
        except Exception as e:
            logger.error(f"Error parsing JT808 message: {e}")
            return None
    
    def _unescape(self, data: bytes) -> bytes:
        """Unescape JT808 data (0x7D 0x02 -> 0x7E, 0x7D 0x01 -> 0x7D)"""
        result = bytearray()
        i = 0
        while i < len(data):
            if data[i] == 0x7D and i + 1 < len(data):
                if data[i + 1] == 0x02:
                    result.append(0x7E)
                    i += 2
                elif data[i + 1] == 0x01:
                    result.append(0x7D)
                    i += 2
                else:
                    result.append(data[i])
                    i += 1
            else:
                result.append(data[i])
                i += 1
        return bytes(result)
    
    def _escape(self, data: bytes) -> bytes:
        """Escape JT808 data for transmission"""
        result = bytearray()
        for byte in data:
            if byte == 0x7E:
                result.extend([0x7D, 0x02])
            elif byte == 0x7D:
                result.extend([0x7D, 0x01])
            else:
                result.append(byte)
        return bytes(result)
    
    def _parse_header(self, payload: bytes) -> Tuple[Optional[Dict], int]:
        """Parse JT808 message header"""
        if len(payload) < 12:
            return None, 0
        
        # Message ID (2 bytes)
        msg_id = struct.unpack('>H', payload[0:2])[0]
        
        # Message properties (2 bytes)
        msg_props = struct.unpack('>H', payload[2:4])[0]
        body_length = msg_props & 0x03FF  # Bits 0-9
        encryption = (msg_props >> 10) & 0x07  # Bits 10-12
        is_subpackage = (msg_props >> 13) & 0x01  # Bit 13
        version_flag = (msg_props >> 14) & 0x01  # Bit 14
        
        # Protocol version
        version = "2019" if version_flag else "2011/2013"
        
        # Terminal phone number position depends on version
        if version_flag:  # 2019 version
            if len(payload) < 17:
                return None, 0
            # Version byte
            protocol_version = payload[4]
            # Terminal phone (10 bytes BCD)
            terminal_phone = self._bcd_to_string(payload[5:15])
            serial_no = struct.unpack('>H', payload[15:17])[0]
            body_start = 17
        else:  # 2011/2013 version
            if len(payload) < 12:
                return None, 0
            # Terminal phone (6 bytes BCD)
            terminal_phone = self._bcd_to_string(payload[4:10])
            serial_no = struct.unpack('>H', payload[10:12])[0]
            body_start = 12
        
        # Handle subpackage header if present
        if is_subpackage:
            if len(payload) < body_start + 4:
                return None, 0
            body_start += 4  # Skip subpackage info
        
        header = {
            'msg_id': msg_id,
            'msg_id_hex': f'0x{msg_id:04x}',
            'body_length': body_length,
            'encryption': encryption,
            'is_subpackage': is_subpackage,
            'version': version,
            'terminal_phone': terminal_phone,
            'device_id': terminal_phone,  # Use phone as device ID
            'serial_no': serial_no
        }
        
        return header, body_start
    
    def _bcd_to_string(self, bcd_bytes: bytes) -> str:
        """Convert BCD bytes to string"""
        result = ""
        for byte in bcd_bytes:
            result += f"{(byte >> 4) & 0x0F:01d}{byte & 0x0F:01d}"
        return result.lstrip('0') or '0'
    
    def _string_to_bcd(self, s: str, length: int) -> bytes:
        """Convert string to BCD bytes"""
        s = s.zfill(length * 2)
        result = bytearray()
        for i in range(0, len(s), 2):
            byte = ((int(s[i]) & 0x0F) << 4) | (int(s[i+1]) & 0x0F)
            result.append(byte)
        return bytes(result)
    
    def _parse_registration(self, body: bytes, result: dict):
        """Parse terminal registration message (0x0100)"""
        result['message'] = "Terminal Registration"
        
        # Extract manufacturer ID, terminal model, terminal ID if present
        if len(body) >= 37:  # 2013/2019 format
            # Province ID (2 bytes)
            province_id = struct.unpack('>H', body[0:2])[0]
            # City ID (2 bytes)  
            city_id = struct.unpack('>H', body[2:4])[0]
            # Manufacturer ID (5 bytes)
            manufacturer = body[4:9].decode('ascii', errors='ignore').strip('\x00')
            # Terminal model (20 bytes for 2013, 30 for 2019)
            model_end = 29 if result['version'] == "2011/2013" else 39
            terminal_model = body[9:model_end].decode('ascii', errors='ignore').strip('\x00')
            # Terminal ID (7 bytes)
            terminal_id = body[model_end:model_end+7].decode('ascii', errors='ignore').strip('\x00')
            
            result['manufacturer'] = manufacturer
            result['terminal_model'] = terminal_model
            result['terminal_id'] = terminal_id
            
            # If we found a readable terminal ID, use it as device ID
            if terminal_id and len(terminal_id) > 3:
                result['device_id'] = terminal_id
    
    def _parse_authentication(self, body: bytes, result: dict):
        """Parse terminal authentication message (0x0102)"""
        result['message'] = "Terminal Authentication"
        if body:
            # Authentication code
            auth_code = body.decode('ascii', errors='ignore').strip('\x00')
            result['auth_code'] = auth_code
    
    def _parse_location(self, body: bytes, result: dict):
        """Parse location report message (0x0200)"""
        result['message'] = "Location Report"
        result['valid'] = True
        
        if len(body) < 28:
            logger.warning("Location body too short")
            return
        
        try:
            # Alarm flags (4 bytes)
            alarm = struct.unpack('>I', body[0:4])[0]
            
            # Status (4 bytes)
            status = struct.unpack('>I', body[4:8])[0]
            
            # Latitude (4 bytes, multiplied by 10^6)
            lat_raw = struct.unpack('>I', body[8:12])[0]
            latitude = lat_raw / 1000000.0
            
            # Longitude (4 bytes, multiplied by 10^6)
            lon_raw = struct.unpack('>I', body[12:16])[0]
            longitude = lon_raw / 1000000.0
            
            # Altitude (2 bytes, meters)
            altitude = struct.unpack('>H', body[16:18])[0]
            
            # Speed (2 bytes, 0.1 km/h)
            speed_raw = struct.unpack('>H', body[18:20])[0]
            speed = speed_raw / 10.0
            
            # Direction (2 bytes, 0-359)
            direction = struct.unpack('>H', body[20:22])[0]
            
            # Time (6 bytes BCD: YY MM DD HH MM SS)
            time_bcd = body[22:28]
            gps_time = self._parse_bcd_time(time_bcd)
            
            # Store parsed values
            result['latitude'] = latitude
            result['longitude'] = longitude
            result['altitude'] = altitude
            result['speed'] = speed
            result['heading'] = direction
            result['gps_time'] = gps_time
            result['status'] = status
            result['alarm'] = alarm
            
            # Check GPS validity from status bits
            result['gps_valid'] = (status & 0x02) != 0  # Bit 1: GPS positioning
            
            logger.info(f"Parsed location: {latitude}, {longitude} @ {speed} km/h")
            
        except Exception as e:
            logger.error(f"Error parsing location data: {e}")
            result['valid'] = False
    
    def _parse_bcd_time(self, bcd: bytes) -> str:
        """Parse BCD time to ISO format"""
        if len(bcd) != 6:
            return ""
        
        year = 2000 + ((bcd[0] >> 4) * 10 + (bcd[0] & 0x0F))
        month = (bcd[1] >> 4) * 10 + (bcd[1] & 0x0F)
        day = (bcd[2] >> 4) * 10 + (bcd[2] & 0x0F)
        hour = (bcd[3] >> 4) * 10 + (bcd[3] & 0x0F)
        minute = (bcd[4] >> 4) * 10 + (bcd[4] & 0x0F)
        second = (bcd[5] >> 4) * 10 + (bcd[5] & 0x0F)
        
        return f"{year:04d}-{month:02d}-{day:02d}T{hour:02d}:{minute:02d}:{second:02d}"
    
    def create_response(self, parsed_data: Dict[str, Any], success: bool = True) -> str:
        """Create proper JT808 response message"""
        msg_id = parsed_data.get('msg_id')
        terminal_phone = parsed_data.get('terminal_phone', '000000000000')
        serial_no = parsed_data.get('serial_no', 0)
        
        if msg_id == self.MSG_TERMINAL_REGISTER:
            # Registration response (0x8100)
            return self._create_register_response(terminal_phone, serial_no, success)
        elif msg_id == self.MSG_LOCATION_REPORT:
            # General response (0x8001)
            return self._create_general_response(terminal_phone, serial_no, msg_id, success)
        elif msg_id == self.MSG_HEARTBEAT:
            # General response for heartbeat
            return self._create_general_response(terminal_phone, serial_no, msg_id, success)
        elif msg_id == self.MSG_TERMINAL_AUTH:
            # General response for auth
            return self._create_general_response(terminal_phone, serial_no, msg_id, success)
        else:
            # Default general response
            return self._create_general_response(terminal_phone, serial_no, msg_id, success)
    
    def _create_general_response(self, phone: str, serial_no: int, response_msg_id: int, success: bool) -> str:
        """Create general response message (0x8001)"""
        # Message body
        body = struct.pack('>H', serial_no)  # Response serial number
        body += struct.pack('>H', response_msg_id)  # Response message ID
        body += struct.pack('B', 0 if success else 1)  # Result: 0=success, 1=failure
        
        # Create full message
        msg = self._create_message(self.MSG_SERVER_RESPONSE, phone, body)
        return msg.hex()
    
    def _create_register_response(self, phone: str, serial_no: int, success: bool) -> str:
        """Create registration response message (0x8100)"""
        # Message body
        body = struct.pack('>H', serial_no)  # Response serial number
        body += struct.pack('B', 0 if success else 1)  # Result: 0=success
        
        if success:
            # Add authentication code (simple example)
            auth_code = f"AUTH{serial_no:04d}".encode('ascii')
            body += auth_code
        
        # Create full message
        msg = self._create_message(self.MSG_REGISTER_RESPONSE, phone, body)
        return msg.hex()
    
    def _create_message(self, msg_id: int, phone: str, body: bytes) -> bytes:
        """Create a complete JT808 message"""
        # Message properties
        body_length = len(body)
        msg_props = body_length & 0x03FF  # No encryption, no subpackage
        
        # Build header (2013 version for compatibility)
        header = struct.pack('>H', msg_id)  # Message ID
        header += struct.pack('>H', msg_props)  # Message properties
        
        # Terminal phone (6 bytes BCD for 2013)
        phone_bcd = self._string_to_bcd(phone[:12].zfill(12), 6)
        header += phone_bcd
        
        # Message serial number (incrementing)
        header += struct.pack('>H', 1)  # Simple serial
        
        # Combine header and body
        payload = header + body
        
        # Calculate checksum (XOR)
        checksum = 0
        for byte in payload:
            checksum ^= byte
        payload += struct.pack('B', checksum)
        
        # Escape special characters
        escaped = self._escape(payload)
        
        # Add frame delimiters
        return bytes([0x7E]) + escaped + bytes([0x7E])
    
    def format_parsed_data(self, parsed: Dict[str, Any]) -> str:
        """Format parsed data for display"""
        lines = []
        lines.append(f"Protocol: {parsed.get('protocol', 'JT808')}")
        lines.append(f"Message: {parsed.get('message', 'Unknown')}")
        lines.append(f"Device ID: {parsed.get('device_id', 'Unknown')}")
        lines.append(f"Terminal Phone: {parsed.get('terminal_phone', 'Unknown')}")
        lines.append(f"Message ID: {parsed.get('msg_id_hex', 'Unknown')}")
        
        if parsed.get('latitude') is not None:
            lines.append(f"Location: {parsed['latitude']:.6f}, {parsed['longitude']:.6f}")
            lines.append(f"Speed: {parsed.get('speed', 0)} km/h")
            lines.append(f"Altitude: {parsed.get('altitude', 0)} m")
            lines.append(f"Heading: {parsed.get('heading', 0)}°")
            lines.append(f"GPS Time: {parsed.get('gps_time', 'N/A')}")
            lines.append(f"GPS Valid: {parsed.get('gps_valid', False)}")
        
        return '\n'.join(lines)