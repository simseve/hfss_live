"""
JT/T 808 Protocol Handler
Handles JT/T 808 (Chinese transportation industry standard) GPS tracker protocol
Protocol uses 0x7E frame delimiters and binary message format
"""
import struct
import logging
from typing import Dict, Any, Optional
from datetime import datetime
from .base import BaseProtocolHandler

logger = logging.getLogger(__name__)


class BinaryGPSProtocolHandler(BaseProtocolHandler):
    """
    Handler for JT/T 808 protocol with 0x7E delimiters
    Message IDs:
    - 0x0100: Terminal registration
    - 0x0102: Terminal authentication  
    - 0x0200: Location report
    - 0x0002: Terminal heartbeat
    """
    
    def get_protocol_name(self) -> str:
        return "JT808"
    
    def can_handle(self, data: str) -> bool:
        """Check if this handler can process the message"""
        # For binary protocols, we need to check the raw bytes
        # The data might come as hex string or decoded string
        try:
            # Check if it's a hex string
            if all(c in '0123456789abcdefABCDEF' for c in data.strip()):
                raw = bytes.fromhex(data.strip())
            else:
                # Try to encode back to bytes
                raw = data.encode('latin-1')
            
            # Check for 0x7E delimiters
            if len(raw) >= 2 and raw[0] == 0x7E and raw[-1] == 0x7E:
                return True
                
        except Exception as e:
            logger.debug(f"Not binary GPS format: {e}")
            
        return False
    
    def parse_message(self, data: str) -> Optional[Dict[str, Any]]:
        """Parse JT/T 808 message"""
        try:
            # Convert to bytes
            if all(c in '0123456789abcdefABCDEF' for c in data.strip()):
                raw = bytes.fromhex(data.strip())
            else:
                raw = data.encode('latin-1')
            
            # Verify frame delimiters
            if len(raw) < 10 or raw[0] != 0x7E or raw[-1] != 0x7E:
                logger.warning(f"Invalid JT808 frame format")
                return None
            
            # Remove frame delimiters
            payload = raw[1:-1]
            
            result = {
                'protocol': self.get_protocol_name(),
                'raw_hex': raw.hex(),
                'timestamp': datetime.now(),
                'valid': False
            }
            
            # Parse JT808 message header
            if len(payload) < 12:  # Minimum header size
                logger.warning("Payload too short for JT808")
                return None
            
            # Message header structure:
            # Bytes 0-1: Message ID
            # Bytes 2-3: Message properties
            # Bytes 4-9 or 4-23: Terminal phone number (6 bytes BCD for 2011/2013, 10 bytes for 2019)
            # Next 2 bytes: Message serial number
            
            msg_id = struct.unpack('>H', payload[0:2])[0]
            msg_props = struct.unpack('>H', payload[2:4])[0]
            
            # Extract message properties
            body_length = msg_props & 0x3FF  # Bits 0-9
            encryption = (msg_props >> 10) & 0x7  # Bits 10-12  
            is_subpackage = (msg_props >> 13) & 0x1  # Bit 13
            version_flag = (msg_props >> 14) & 0x1  # Bit 14 (1 for 2019 version)
            
            result['message_id'] = f"0x{msg_id:04x}"
            result['body_length'] = body_length
            result['version'] = "2019" if version_flag else "2011/2013"
            
            # Terminal ID position depends on version
            if version_flag:  # 2019 version - 10 byte terminal ID
                terminal_id_end = 14
            else:  # 2011/2013 - 6 byte BCD terminal ID
                terminal_id_end = 10
            
            # Extract terminal phone/ID
            terminal_bytes = payload[4:terminal_id_end]
            
            # Try to extract readable device ID from the message
            # Looking for ASCII device ID like "70111EG-05" in the body
            device_id = self._extract_device_id(payload)
            if device_id:
                result['device_id'] = device_id
            else:
                # Use terminal phone as device ID
                result['device_id'] = terminal_bytes.hex()
            
            # Message serial number
            serial_pos = terminal_id_end
            if len(payload) > serial_pos + 2:
                serial_no = struct.unpack('>H', payload[serial_pos:serial_pos+2])[0]
                result['serial_no'] = serial_no
            
            # Parse message type
            if msg_id == 0x0100:  # Terminal registration
                result['message'] = "Terminal Registration"
                self._parse_registration(payload, result)
            elif msg_id == 0x0102:  # Terminal authentication
                result['message'] = "Terminal Authentication"
            elif msg_id == 0x0200:  # Location report
                result['message'] = "Location Report"
                result['valid'] = True  # Has GPS data
                self._parse_location_data(payload, result)
            elif msg_id == 0x0002:  # Heartbeat
                result['message'] = "Heartbeat"
            elif msg_id == 0x0001:  # Terminal general response
                result['message'] = "Terminal Response"
            else:
                result['message'] = f"Message ID 0x{msg_id:04x}"
            
            # Check for status codes in body
            if b'B88888' in payload:
                result['status_code'] = 'B88888'
                
            return result
            
        except Exception as e:
            logger.error(f"Error parsing binary GPS message: {e}")
            return None
    
    def _extract_device_id(self, payload: bytes) -> Optional[str]:
        """Extract ASCII device ID from binary payload"""
        # Look for continuous ASCII sequences
        best_id = None
        current_ascii = []
        
        for i, byte in enumerate(payload):
            if 32 <= byte <= 126:  # Printable ASCII
                current_ascii.append(chr(byte))
            else:
                if len(current_ascii) >= 5:
                    potential_id = ''.join(current_ascii).strip()
                    # Look for patterns like "70111EG-05" or alphanumeric IDs
                    if ('-' in potential_id or potential_id.replace('-', '').replace('_', '').isalnum()) and len(potential_id) >= 5:
                        # Prefer IDs with dashes or that look like device names
                        if not best_id or ('-' in potential_id and '-' not in best_id) or len(potential_id) > len(best_id):
                            best_id = potential_id
                current_ascii = []
        
        # Check last sequence
        if len(current_ascii) >= 5:
            potential_id = ''.join(current_ascii).strip()
            if ('-' in potential_id or potential_id.replace('-', '').replace('_', '').isalnum()) and len(potential_id) >= 5:
                if not best_id or ('-' in potential_id and '-' not in best_id) or len(potential_id) > len(best_id):
                    best_id = potential_id
        
        if best_id:
            # Clean up the ID
            best_id = best_id.strip('\x00').strip('/').strip()
            logger.debug(f"Extracted device ID: {best_id}")
        
        return best_id
    
    def _parse_registration(self, payload: bytes, result: dict):
        """Parse terminal registration message (0x0100)"""
        try:
            # Registration contains device info and ID
            # The "70111EG-05" ID is likely in the registration body
            result['message_details'] = "Device registering with server"
        except Exception as e:
            logger.debug(f"Error parsing registration: {e}")
    
    def _parse_location_data(self, payload: bytes, result: dict):
        """Parse location data from 0x0200 message"""
        try:
            # Location message body structure (after header):
            # 4 bytes: Alarm flags
            # 4 bytes: Status
            # 4 bytes: Latitude (multiplied by 10^6)
            # 4 bytes: Longitude (multiplied by 10^6)
            # 2 bytes: Altitude (meters)
            # 2 bytes: Speed (0.1 km/h)
            # 2 bytes: Direction (0-359 degrees)
            # 6 bytes: Time (BCD: YY MM DD HH MM SS)
            
            # Find where message body starts (after header and serial number)
            # This is approximate - would need full protocol spec
            body_start = 16  # Approximate position
            
            if len(payload) > body_start + 28:  # Minimum location data size
                body = payload[body_start:]
                
                # Try to parse GPS coordinates
                if len(body) >= 28:
                    # These offsets would need adjustment based on actual protocol
                    # alarm_flags = struct.unpack('>I', body[0:4])[0]
                    # status = struct.unpack('>I', body[4:8])[0]
                    # lat_raw = struct.unpack('>I', body[8:12])[0]
                    # lon_raw = struct.unpack('>I', body[12:16])[0]
                    
                    # result['latitude'] = lat_raw / 1000000.0
                    # result['longitude'] = lon_raw / 1000000.0
                    result['has_location'] = True
                    result['message_details'] = "Contains GPS location data"
            else:
                result['has_location'] = False
                
        except Exception as e:
            logger.debug(f"Error parsing location data: {e}")
            result['has_location'] = False
        
    def create_response(self, parsed_data: Dict[str, Any], success: bool = True) -> str:
        """Create JT808 response message"""
        msg_id = parsed_data.get('message_id', '0x0000')
        
        # JT808 server responses:
        # 0x8100: Registration response
        # 0x8001: General response
        
        if msg_id == '0x0100':  # Registration request
            # Send registration response (simplified)
            # Format: 7E 8100 [properties] [terminal] [serial] [result] [auth_code] 7E
            # For now, send simple ACK
            response = bytes([0x7E, 0x81, 0x00, 0x00, 0x00, 0x00, 0x7E])
        elif msg_id == '0x0200':  # Location report
            # Send general ACK
            response = bytes([0x7E, 0x80, 0x01, 0x00, 0x00, 0x00, 0x7E])
        else:
            # Generic ACK
            response = bytes([0x7E, 0x80, 0x01, 0x00, 0x00, 0x7E])
        
        logger.debug(f"Sending JT808 response: {response.hex()}")
        return response.hex()
    
    def format_parsed_data(self, parsed: Dict[str, Any]) -> str:
        """Format parsed data for display"""
        lines = []
        lines.append(f"Protocol: {parsed.get('protocol', 'Unknown')}")
        lines.append(f"Device ID: {parsed.get('device_id', 'Unknown')}")
        lines.append(f"Message Type: {parsed.get('message_type', 'Unknown')}")
        lines.append(f"Message: {parsed.get('message', 'Unknown')}")
        
        if parsed.get('status_code'):
            lines.append(f"Status: {parsed['status_code']}")
            
        if parsed.get('has_location'):
            lines.append("Contains: Location data")
            
        lines.append(f"Raw Hex: {parsed.get('raw_hex', 'N/A')[:50]}...")
        
        return '\n'.join(lines)