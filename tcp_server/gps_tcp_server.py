"""
Production-ready GPS Tracker TCP Server
Supports TK905B (watch protocol) and TK103 protocol devices
"""
import asyncio
import logging
import json
import time
import signal
import sys
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Set, List
from collections import defaultdict, deque
import re
import traceback

# Import protocol handlers
try:
    from protocols import parse_message, create_response, get_supported_protocols
except ImportError:
    # Fallback if protocols module not available yet
    parse_message = None
    create_response = None
    get_supported_protocols = None

logger = logging.getLogger(__name__)

# Server configuration constants
MAX_CONNECTIONS = 1000  # Maximum simultaneous connections
MAX_CONNECTIONS_PER_IP = 50  # Max connections from single IP (increased from 10)
CONNECTION_TIMEOUT = 300  # 5 minutes idle timeout
MAX_MESSAGE_SIZE = 4096  # Maximum message size in bytes
MAX_BUFFER_SIZE = 8192  # Maximum buffer size per connection
RATE_LIMIT_MESSAGES = 20  # Max messages per device (increased for poor coverage)
RATE_LIMIT_WINDOW = 60  # Rate limit window in seconds
HEARTBEAT_INTERVAL = 30  # Send heartbeat every 30 seconds
MAX_RECONNECT_ATTEMPTS = 100  # Max reconnection attempts (trackers reconnect often)
RECONNECT_COOLDOWN = 300  # 5 min window for counting reconnections
MIN_MESSAGE_INTERVAL = 0.3  # Minimum seconds between messages (allows batch sending)
MAX_RETRANSMISSIONS = 3  # Maximum retransmission attempts
RETRANSMISSION_TIMEOUT = 2  # Seconds to wait for ACK
AUTO_RESTART_ON_ERRORS = 5  # Auto restart after N consecutive errors


class PacketValidator:
    """Validate and manage packet integrity"""
    
    def __init__(self):
        self.packet_history = defaultdict(list)  # Track recent packets per device
        self.retransmission_queue = defaultdict(deque)  # Pending retransmissions
        self.last_sequence = defaultdict(int)  # Last sequence number per device
        
    def is_duplicate(self, device_id: str, packet_hash: str) -> bool:
        """Check if packet is a duplicate (retransmission)"""
        history = self.packet_history[device_id]
        
        # Keep only recent history (last 100 packets or 5 minutes)
        now = time.time()
        self.packet_history[device_id] = [
            (h, t) for h, t in history 
            if t > now - 300 and len(history) < 100
        ]
        
        # Check if packet seen before
        for hash_val, _ in self.packet_history[device_id]:
            if hash_val == packet_hash:
                return True
                
        # Add to history
        self.packet_history[device_id].append((packet_hash, now))
        return False
        
    def validate_packet(self, data: str) -> tuple[bool, str]:
        """Validate packet format and checksum if present"""
        # Basic format validation
        if not data:
            return False, "Empty packet"
            
        # Check for malformed packets
        if len(data) > MAX_MESSAGE_SIZE:
            return False, "Packet too large"
            
        # Validate bracket/parenthesis matching
        if data.startswith('['):
            if not data.endswith(']'):
                return False, "Unclosed bracket"
            if data.count('[') != data.count(']'):
                return False, "Mismatched brackets"
                
        elif data.startswith('('):
            if not data.endswith(')'):
                return False, "Unclosed parenthesis"
            if data.count('(') != data.count(')'):
                return False, "Mismatched parentheses"
                
        # Check for control characters (except newline/carriage return)
        for char in data:
            if ord(char) < 32 and char not in '\r\n':
                return False, "Invalid control character"
                
        return True, "OK"


class RateLimiter:
    """Rate limiting for device connections with interval checking"""
    
    def __init__(self, max_messages: int = RATE_LIMIT_MESSAGES, window: int = RATE_LIMIT_WINDOW):
        self.max_messages = max_messages
        self.window = window
        self.device_messages = defaultdict(deque)
        self.last_message_time = defaultdict(float)
        
    def is_allowed(self, device_id: str) -> tuple[bool, str]:
        """Check if device is allowed to send message"""
        now = time.time()
        messages = self.device_messages[device_id]
        
        # Check minimum interval between messages
        last_time = self.last_message_time.get(device_id, 0)
        if last_time and now - last_time < MIN_MESSAGE_INTERVAL:
            return False, f"Too frequent (min {MIN_MESSAGE_INTERVAL}s interval)"
        
        # Remove old messages outside window
        while messages and messages[0] < now - self.window:
            messages.popleft()
            
        # Check rate limit
        if len(messages) >= self.max_messages:
            return False, f"Rate limit exceeded ({self.max_messages} per {self.window}s)"
            
        # Add current message timestamp
        messages.append(now)
        self.last_message_time[device_id] = now
        return True, "OK"
        
    def reset_device(self, device_id: str):
        """Reset rate limit for a device"""
        if device_id in self.device_messages:
            del self.device_messages[device_id]
        if device_id in self.last_message_time:
            del self.last_message_time[device_id]


class ConnectionManager:
    """Manage connection limits and tracking"""
    
    def __init__(self):
        self.connections_by_ip = defaultdict(set)
        self.connection_attempts = defaultdict(list)
        self.blacklisted_ips = set()
        # Whitelist for testing/localhost - never blacklist these
        self.whitelisted_ips = {'127.0.0.1', 'localhost', '::1'}
        
    def can_connect(self, peername) -> bool:
        """Check if connection is allowed"""
        if not peername:
            return False
            
        ip = peername[0]
        
        # Skip blacklist check for whitelisted IPs
        if ip not in self.whitelisted_ips:
            # Check blacklist
            if ip in self.blacklisted_ips:
                logger.warning(f"Blocked blacklisted IP: {ip}")
                return False
            
        # Check connection limit per IP
        if len(self.connections_by_ip[ip]) >= MAX_CONNECTIONS_PER_IP:
            logger.warning(f"Connection limit exceeded for IP: {ip}")
            return False
            
        # Check reconnection attempts (only for non-whitelisted IPs)
        if ip not in self.whitelisted_ips:
            now = time.time()
            attempts = self.connection_attempts[ip]
            
            # Clean old attempts
            self.connection_attempts[ip] = [
                t for t in attempts 
                if t > now - RECONNECT_COOLDOWN
            ]
            
            # Only blacklist for extremely high reconnection rates (likely attack)
            if len(self.connection_attempts[ip]) >= MAX_RECONNECT_ATTEMPTS:
                # Check if connections are too rapid (more than 10 per second = attack)
                recent_attempts = [t for t in self.connection_attempts[ip] if t > now - 1]
                if len(recent_attempts) > 10:
                    logger.warning(f"Rapid reconnection attack from IP: {ip} ({len(recent_attempts)} connections/sec)")
                    self.blacklist_ip(ip, duration=60)  # 1 min blacklist
                    return False
                else:
                    # Normal reconnections from tracker losing signal - just log it
                    logger.info(f"Device reconnecting frequently from IP: {ip} (likely coverage issues)")
            
        return True
        
    def add_connection(self, peername, conn_id):
        """Register a new connection"""
        if peername:
            ip = peername[0]
            self.connections_by_ip[ip].add(conn_id)
            self.connection_attempts[ip].append(time.time())
            
    def remove_connection(self, peername, conn_id):
        """Remove a connection"""
        if peername:
            ip = peername[0]
            self.connections_by_ip[ip].discard(conn_id)
            if not self.connections_by_ip[ip]:
                del self.connections_by_ip[ip]
                
    def blacklist_ip(self, ip: str, duration: int = 3600):
        """Temporarily blacklist an IP"""
        self.blacklisted_ips.add(ip)
        # Schedule removal from blacklist
        asyncio.create_task(self._unblacklist_after(ip, duration))
        
    async def _unblacklist_after(self, ip: str, duration: int):
        """Remove IP from blacklist after duration"""
        await asyncio.sleep(duration)
        self.blacklisted_ips.discard(ip)
        logger.info(f"Removed {ip} from blacklist")


class GPSProtocolParser:
    """Parse different GPS tracker protocols with validation"""
    
    @staticmethod
    def validate_coordinates(lat: float, lon: float) -> bool:
        """Validate GPS coordinates"""
        return -90 <= lat <= 90 and -180 <= lon <= 180
    
    @staticmethod
    def parse_watch_protocol(data: str) -> Optional[Dict[str, Any]]:
        """
        Parse watch protocol format (TK905B) with validation
        Format: [SG*ID*LENGTH*COMMAND,data...]
        """
        try:
            # Validate format
            if not data or len(data) > MAX_MESSAGE_SIZE:
                return None
                
            if not data.startswith('[') or not data.endswith(']'):
                return None
                
            # Remove brackets and validate content
            content = data[1:-1]
            if not content:
                return None
                
            # Split header and data
            parts = content.split('*')
            if len(parts) < 4:
                return None
                
            # Validate manufacturer code
            manufacturer = parts[0]
            if manufacturer not in ['SG', '3G', 'LG']:
                logger.warning(f"Unknown manufacturer code: {manufacturer}")
                
            # Validate device ID (should be numeric)
            device_id = parts[1]
            if not device_id or not device_id.isdigit():
                logger.warning(f"Invalid device ID: {device_id}")
                return None
                
            # Validate length field
            length = parts[2]
            if not length.isdigit():
                return None
                
            # Get command and data
            command_data = '*'.join(parts[3:])
            command_parts = command_data.split(',')
            command = command_parts[0]
            
            # Parse UD2/UD (location) messages
            if command in ['UD2', 'UD', 'UD_LBS', 'UD_WIFI']:
                if len(command_parts) < 7:
                    return None
                    
                # Parse date and time
                date_str = command_parts[1]  # DDMMYY
                time_str = command_parts[2]  # HHMMSS
                
                # Validate date/time format
                if len(date_str) != 6 or len(time_str) != 6:
                    return None
                    
                try:
                    dt = datetime.strptime(f"{date_str}{time_str}", "%d%m%y%H%M%S")
                    
                    # Sanity check - not too far in future or past
                    now = datetime.now()
                    if abs((dt - now).days) > 365:
                        logger.warning(f"Suspicious timestamp: {dt}")
                        
                except ValueError:
                    logger.error(f"Invalid date/time: {date_str} {time_str}")
                    return None
                    
                valid = command_parts[3] == 'A'  # A=valid, V=invalid
                
                # Parse coordinates with validation
                try:
                    # Parse latitude in DDMM.MMMM format
                    lat_str = command_parts[4]
                    lat_deg = float(lat_str[:2])  # First 2 digits are degrees
                    lat_min = float(lat_str[2:])  # Rest are minutes
                    lat = lat_deg + (lat_min / 60.0)
                    lat_dir = command_parts[5]  # N/S
                    
                    # Parse longitude in DDDMM.MMMM format  
                    lon_str = command_parts[6]
                    lon_deg = float(lon_str[:3]) if len(lon_str) > 4 else float(lon_str[:2])  # First 3 digits for longitude
                    lon_min = float(lon_str[3:]) if len(lon_str) > 4 else float(lon_str[2:])
                    lon = lon_deg + (lon_min / 60.0)
                    lon_dir = command_parts[7]  # E/W
                    
                    # Apply direction
                    if lat_dir == 'S':
                        lat = -lat
                    if lon_dir == 'W':
                        lon = -lon
                        
                    # Validate coordinates
                    if not GPSProtocolParser.validate_coordinates(lat, lon):
                        logger.warning(f"Invalid coordinates: {lat}, {lon}")
                        valid = False
                        
                except (ValueError, IndexError):
                    return None
                    
                result = {
                    'protocol': 'watch',
                    'device_id': device_id,
                    'latitude': lat,
                    'longitude': lon,
                    'timestamp': dt,
                    'valid': valid,
                    'raw': data
                }
                
                # Parse optional fields with validation
                try:
                    if len(command_parts) > 8 and command_parts[8]:
                        speed = float(command_parts[8])
                        result['speed'] = max(0, min(speed, 500))  # 0-500 km/h
                        
                    if len(command_parts) > 9 and command_parts[9]:
                        heading = float(command_parts[9])
                        result['heading'] = heading % 360  # 0-359 degrees
                        
                    if len(command_parts) > 10 and command_parts[10]:
                        altitude = float(command_parts[10])
                        result['altitude'] = max(-500, min(altitude, 9000))  # -500 to 9000m
                        
                    if len(command_parts) > 11 and command_parts[11]:
                        satellites = int(command_parts[11])
                        result['satellites'] = max(0, min(satellites, 50))  # 0-50 sats
                        
                    if len(command_parts) > 12 and command_parts[12]:
                        battery = int(command_parts[12])
                        result['battery'] = max(0, min(battery, 100))  # 0-100%
                        
                except (ValueError, IndexError):
                    pass  # Optional fields, ignore errors
                    
                return result
                
            # Parse UD3 (batch location) messages  
            elif command == 'UD3':
                # UD3 format: UD3,COUNT,RECORD1;RECORD2;...
                # Each record: DATE,TIME,STATUS,LAT,LAT_DIR,LON,LON_DIR,SPEED,HEADING,ALT
                if len(command_parts) < 3:
                    return None
                    
                try:
                    count = int(command_parts[1])
                    batch_data = ','.join(command_parts[2:])  # Rejoin remaining parts
                    records = batch_data.split(';')  # Split by semicolon
                    
                    if len(records) != count:
                        logger.warning(f"UD3 count mismatch: expected {count}, got {len(records)}")
                    
                    results = []
                    for record_str in records:
                        record_parts = record_str.split(',')
                        if len(record_parts) < 10:
                            continue
                            
                        # Parse each record similar to UD2
                        date_str = record_parts[0]
                        time_str = record_parts[1]
                        
                        try:
                            dt = datetime.strptime(f"{date_str}{time_str}", "%d%m%y%H%M%S")
                        except ValueError:
                            continue
                            
                        valid = record_parts[2] == 'A'
                        
                        # Parse coordinates
                        lat_str = record_parts[3]
                        lat_deg = float(lat_str[:2])
                        lat_min = float(lat_str[2:])
                        lat = lat_deg + (lat_min / 60.0)
                        if record_parts[4] == 'S':
                            lat = -lat
                            
                        lon_str = record_parts[5]
                        lon_deg = float(lon_str[:3]) if len(lon_str) > 4 else float(lon_str[:2])
                        lon_min = float(lon_str[3:]) if len(lon_str) > 4 else float(lon_str[2:])
                        lon = lon_deg + (lon_min / 60.0)
                        if record_parts[6] == 'W':
                            lon = -lon
                            
                        point = {
                            'protocol': 'watch',
                            'device_id': device_id,
                            'latitude': lat,
                            'longitude': lon,
                            'timestamp': dt,
                            'valid': valid,
                            'speed': float(record_parts[7]) if len(record_parts) > 7 else 0,
                            'heading': float(record_parts[8]) if len(record_parts) > 8 else 0,
                            'altitude': float(record_parts[9]) if len(record_parts) > 9 else 0
                        }
                        results.append(point)
                    
                    # Return batch result
                    return {
                        'protocol': 'watch',
                        'device_id': device_id,
                        'command': 'UD3',
                        'batch': True,
                        'count': len(results),
                        'points': results,
                        'raw': data
                    }
                    
                except (ValueError, IndexError) as e:
                    logger.error(f"Error parsing UD3 batch: {e}")
                    return None
                
            # Handle other known commands
            elif command in ['LK', 'HEART', 'AL', 'TK', 'PULSE', 'BPHRT', 'SOS']:
                return {
                    'protocol': 'watch',
                    'device_id': device_id,
                    'command': command,
                    'data': command_parts[1:] if len(command_parts) > 1 else [],
                    'raw': data
                }
                
            else:
                logger.debug(f"Unknown watch command: {command}")
                return {
                    'protocol': 'watch',
                    'device_id': device_id,
                    'command': command,
                    'data': command_parts[1:] if len(command_parts) > 1 else [],
                    'raw': data
                }
                
        except Exception as e:
            logger.error(f"Error parsing watch protocol: {e}, data: {data[:100]}")
            
        return None
    
    @staticmethod
    def parse_tk103_protocol(data: str) -> Optional[Dict[str, Any]]:
        """
        Parse TK103 protocol format with validation
        Format: (device_id,command,data)
        """
        try:
            # Validate format
            if not data or len(data) > MAX_MESSAGE_SIZE:
                return None
                
            if not data.startswith('(') or not data.endswith(')'):
                return None
                
            # Remove parentheses
            content = data[1:-1]
            if not content:
                return None
                
            parts = content.split(',')
            
            if len(parts) < 2:
                return None
                
            device_id = parts[0]
            
            # Validate device ID (should be numeric or IMEI)
            if not device_id or not re.match(r'^[0-9]{10,20}$', device_id):
                logger.warning(f"Invalid TK103 device ID: {device_id}")
                return None
                
            command = parts[1]
            
            # Parse location messages (BP00, BR00, BO01)
            if command in ['BP00', 'BR00', 'BO01'] and len(parts) >= 10:
                try:
                    date_str = parts[3]  # DDMMYY
                    valid = parts[4] == 'A'  # A=valid, V=invalid
                    
                    # Parse datetime
                    time_str = parts[8] if len(parts) > 8 else "000000"
                    dt = datetime.strptime(f"{date_str}{time_str}", "%d%m%y%H%M%S")
                    
                    # Parse latitude
                    lat_str = parts[5]
                    lat_match = re.match(r'(\d{2})(\d{2}\.\d+)([NS])', lat_str)
                    if lat_match:
                        lat_deg = float(lat_match.group(1))
                        lat_min = float(lat_match.group(2))
                        lat = lat_deg + lat_min / 60
                        if lat_match.group(3) == 'S':
                            lat = -lat
                    else:
                        lat = 0
                        valid = False
                    
                    # Parse longitude
                    lon_str = parts[6]
                    lon_match = re.match(r'(\d{3})(\d{2}\.\d+)([EW])', lon_str)
                    if lon_match:
                        lon_deg = float(lon_match.group(1))
                        lon_min = float(lon_match.group(2))
                        lon = lon_deg + lon_min / 60
                        if lon_match.group(3) == 'W':
                            lon = -lon
                    else:
                        lon = 0
                        valid = False
                    
                    # Validate coordinates
                    if not GPSProtocolParser.validate_coordinates(lat, lon):
                        valid = False
                    
                    speed = float(parts[7]) if parts[7] else 0
                    heading = float(parts[9]) if len(parts) > 9 and parts[9] else 0
                    
                    return {
                        'protocol': 'tk103',
                        'device_id': device_id,
                        'latitude': lat,
                        'longitude': lon,
                        'timestamp': dt,
                        'valid': valid,
                        'speed': max(0, min(speed, 500)),
                        'heading': heading % 360,
                        'command': command,
                        'raw': data
                    }
                    
                except (ValueError, IndexError) as e:
                    logger.error(f"Error parsing TK103 location: {e}")
                    return None
                    
            # Handle login message (BP05)
            elif command == 'BP05':
                return {
                    'protocol': 'tk103',
                    'device_id': device_id,
                    'command': 'login',
                    'raw': data
                }
                
            # Handle heartbeat (BP04)
            elif command == 'BP04':
                return {
                    'protocol': 'tk103',
                    'device_id': device_id,
                    'command': 'heartbeat',
                    'raw': data
                }
                
            # Handle other commands
            else:
                return {
                    'protocol': 'tk103',
                    'device_id': device_id,
                    'command': command,
                    'data': parts[2:] if len(parts) > 2 else [],
                    'raw': data
                }
                
        except Exception as e:
            logger.error(f"Error parsing TK103 protocol: {e}, data: {data[:100]}")
            
        return None
    
    @staticmethod
    def parse(data: str) -> Optional[Dict[str, Any]]:
        """Try to parse data with different protocol parsers"""
        if not data:
            return None
            
        # Sanitize input
        data = data.strip()
        
        # Try watch protocol first (TK905B)
        if data.startswith('['):
            result = GPSProtocolParser.parse_watch_protocol(data)
            if result:
                return result
                
        # Try TK103 protocol
        if data.startswith('('):
            result = GPSProtocolParser.parse_tk103_protocol(data)
            if result:
                return result
                
        return None


class GPSClientProtocol(asyncio.Protocol):
    """Handle individual GPS tracker connections with reliability features"""
    
    def __init__(self, server):
        self.server = server
        self.transport = None
        self.device_id = None
        self.buffer = b""
        self.peername = None
        self.conn_id = None
        self.last_activity = time.time()
        self.message_count = 0
        self.heartbeat_task = None
        self.timeout_task = None
        
    def connection_made(self, transport):
        """Handle new connection"""
        try:
            self.transport = transport
            self.peername = transport.get_extra_info('peername')
            self.conn_id = f"{self.peername}_{time.time()}"
            
            # Check connection limits
            if not self.server.conn_manager.can_connect(self.peername):
                logger.warning(f"Connection rejected from {self.peername}")
                transport.close()
                return
                
            # Check total connection limit
            if len(self.server.active_connections) >= MAX_CONNECTIONS:
                logger.warning(f"Max connections reached, rejecting {self.peername}")
                transport.close()
                return
                
            # Register connection
            self.server.conn_manager.add_connection(self.peername, self.conn_id)
            self.server.active_connections[self.conn_id] = self
            
            # Set socket options for reliability
            sock = transport.get_extra_info('socket')
            if sock:
                import socket
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                
            # Only log non-localhost connections
            if self.peername and self.peername[0] not in ('127.0.0.1', 'localhost', '::1'):
                logger.info(f"GPS tracker connected from {self.peername} (total: {len(self.server.active_connections)})")
            else:
                logger.debug(f"Health check connected from {self.peername}")
            
            # Start timeout monitor
            self.timeout_task = asyncio.create_task(self._monitor_timeout())
            
        except Exception as e:
            logger.error(f"Error in connection_made: {e}")
            if transport:
                transport.close()
                
    def connection_lost(self, exc):
        """Handle connection loss"""
        try:
            # Only log non-localhost disconnections
            if self.peername and self.peername[0] not in ('127.0.0.1', 'localhost', '::1'):
                if exc:
                    logger.info(f"GPS tracker disconnected from {self.peername}: {exc}")
                else:
                    logger.info(f"GPS tracker disconnected from {self.peername}")
            else:
                logger.debug(f"Health check disconnected from {self.peername}")
                
            # Cancel tasks
            if self.heartbeat_task:
                self.heartbeat_task.cancel()
            if self.timeout_task:
                self.timeout_task.cancel()
                
            # Clean up
            if self.conn_id in self.server.active_connections:
                del self.server.active_connections[self.conn_id]
                
            self.server.conn_manager.remove_connection(self.peername, self.conn_id)
            
            # Reset rate limit for device
            if self.device_id:
                self.server.rate_limiter.reset_device(self.device_id)
                
        except Exception as e:
            logger.error(f"Error in connection_lost: {e}")
            
    def data_received(self, data):
        """Handle incoming data from GPS tracker"""
        try:
            self.last_activity = time.time()
            
            # Check buffer size limit
            if len(self.buffer) + len(data) > MAX_BUFFER_SIZE:
                logger.warning(f"Buffer overflow from {self.peername}, closing connection")
                self.transport.close()
                return
                
            self.buffer += data
            
            # Process complete messages
            while self._process_buffer():
                pass
                
        except Exception as e:
            logger.error(f"Error in data_received: {e}")
            self.transport.close()
            
    def _process_buffer(self) -> bool:
        """Process buffer and extract complete messages"""
        # Look for message delimiters
        delimiters = [
            (b']', True),   # Watch protocol, include delimiter
            (b')', True),   # TK103 protocol, include delimiter
            (b'\n', False), # Newline, exclude delimiter
            (b'\r\n', False) # CRLF, exclude delimiter
        ]
        
        for delimiter, include in delimiters:
            pos = self.buffer.find(delimiter)
            if pos != -1:
                # Extract message
                if include:
                    message = self.buffer[:pos + len(delimiter)]
                else:
                    message = self.buffer[:pos]
                    
                self.buffer = self.buffer[pos + len(delimiter):]
                
                # Process message asynchronously
                asyncio.create_task(self.process_message(message))
                return True
                
        return False
        
    async def process_message(self, message: bytes):
        """Process a complete GPS message with error handling"""
        try:
            # Decode message
            try:
                text = message.decode('utf-8', errors='ignore').strip()
            except Exception:
                text = message.decode('latin-1', errors='ignore').strip()
                
            if not text:
                return
                
            # Validate packet format
            valid, reason = self.server.packet_validator.validate_packet(text)
            if not valid:
                logger.warning(f"Invalid packet from {self.peername}: {reason}")
                self.server.stats['errors'] += 1
                await self.send_response(text, error=True)
                return
                
            self.message_count += 1
            logger.debug(f"Received message #{self.message_count} from {self.peername}: {text[:100]}")
            
            # Parse message
            parsed = GPSProtocolParser.parse(text)
            if not parsed:
                logger.warning(f"Unable to parse message: {text[:100]}")
                self.server.stats['errors'] += 1
                await self.send_response(text, error=True)
                return
                
            # Extract and validate device ID
            if 'device_id' in parsed:
                if not self.device_id:
                    self.device_id = parsed['device_id']
                elif self.device_id != parsed['device_id']:
                    logger.warning(f"Device ID mismatch: {self.device_id} != {parsed['device_id']}")
                    
            # Check for duplicate/retransmission
            packet_hash = hash(text)
            if self.device_id and self.server.packet_validator.is_duplicate(self.device_id, str(packet_hash)):
                logger.debug(f"Duplicate packet from {self.device_id}, sending ACK")
                await self.send_response(text)  # Send ACK for retransmission
                return
                    
            # Check rate limit
            if self.device_id:
                allowed, reason = self.server.rate_limiter.is_allowed(self.device_id)
                if not allowed:
                    logger.warning(f"Rate limit for device {self.device_id}: {reason}")
                    await self.send_response(text, error=True)
                    return
                
            # Handle different message types
            if parsed.get('command') == 'login':
                await self.send_login_ack(parsed)
                # Start heartbeat after login
                if not self.heartbeat_task:
                    self.heartbeat_task = asyncio.create_task(self._send_heartbeat())
                    
            elif parsed.get('command') == 'heartbeat':
                await self.send_heartbeat_ack(parsed)
                
            # Handle batch messages
            elif parsed.get('batch') and parsed.get('points'):
                logger.info(f"Processing batch of {len(parsed['points'])} points from {self.device_id}")
                for point in parsed['points']:
                    point['device_id'] = self.device_id
                    if point.get('valid'):
                        await self.queue_gps_data(point)
                        self.server.stats['valid_locations'] += 1
                # Send response using new protocol system
                if create_response:
                    response = create_response(parsed, success=True)
                    if response:
                        self.transport.write(response.encode('utf-8'))
                else:
                    await self.send_response(text)
            # Handle single location
            elif 'latitude' in parsed and 'longitude' in parsed:
                # Queue GPS data for processing
                await self.queue_gps_data(parsed)
                # Send response using new protocol system  
                if create_response:
                    response = create_response(parsed, success=True)
                    if response:
                        self.transport.write(response.encode('utf-8'))
                else:
                    await self.send_response(text)
                
            else:
                # Log other message types
                logger.info(f"Received {parsed.get('command', 'unknown')} from {self.device_id}: {parsed}")
                await self.send_response(text)
                
        except Exception as e:
            logger.error(f"Error processing message: {e}\n{traceback.format_exc()}")
            
    async def queue_gps_data(self, parsed: Dict[str, Any]):
        """Log GPS data for now - will queue to Redis later"""
        try:
            # Enhanced logging with connection info
            logger.info(f"=== GPS DATA RECEIVED ===")
            logger.info(f"Connection: {self.conn_id}")
            logger.info(f"Message #: {self.message_count}")
            logger.info(f"Protocol: {parsed.get('protocol', 'unknown')}")
            logger.info(f"Device ID: {parsed.get('device_id', 'unknown')}")
            logger.info(f"Timestamp: {parsed.get('timestamp', 'N/A')}")
            logger.info(f"Location: {parsed.get('latitude', 0)}, {parsed.get('longitude', 0)}")
            logger.info(f"Altitude: {parsed.get('altitude', 0)} m")
            logger.info(f"Speed: {parsed.get('speed', 0)} km/h")
            logger.info(f"Heading: {parsed.get('heading', 0)}°")
            logger.info(f"Satellites: {parsed.get('satellites', 0)}")
            logger.info(f"Battery: {parsed.get('battery', 0)}%")
            logger.info(f"Valid: {parsed.get('valid', False)}")
            logger.info(f"========================")
            
            # Save to log file as JSON
            with open('gps_tcp_data.log', 'a') as f:
                log_entry = {
                    'timestamp': datetime.now().isoformat(),
                    'connection_id': self.conn_id,
                    'message_count': self.message_count,
                    'parsed_data': parsed,
                    'source_ip': str(self.peername)
                }
                # Convert datetime objects to strings
                if isinstance(parsed.get('timestamp'), datetime):
                    log_entry['parsed_data']['timestamp'] = parsed['timestamp'].isoformat()
                f.write(json.dumps(log_entry) + '\n')
            
            # Update statistics
            self.server.stats['messages_received'] += 1
            if parsed.get('valid'):
                self.server.stats['valid_locations'] += 1
                
        except Exception as e:
            logger.error(f"Error logging GPS data: {e}")
            
    async def send_response(self, original_message: str, error: bool = False):
        """Send response to tracker with error handling"""
        try:
            if not self.transport or self.transport.is_closing():
                return
                
            protocol = 'watch' if original_message.startswith('[') else 'tk103'
            
            if protocol == 'watch':
                if not error:
                    response = f"[{self.device_id or 'SG'}*0002*OK]"
                else:
                    response = f"[{self.device_id or 'SG'}*0004*FAIL]"
            else:
                if not error:
                    response = f"({self.device_id or '0'};)"
                else:
                    response = f"({self.device_id or '0'}BP00HSO)"
                    
            self.transport.write(response.encode('utf-8'))
            logger.debug(f"Sent response to {self.peername}: {response}")
            
        except Exception as e:
            logger.error(f"Error sending response: {e}")
            
    async def send_login_ack(self, parsed: Dict[str, Any]):
        """Send login acknowledgment"""
        try:
            if not self.transport or self.transport.is_closing():
                return
                
            if parsed['protocol'] == 'tk103':
                response = f"({parsed['device_id']}AP05)"
            else:
                response = f"[{parsed['device_id']}*0002*LK]"
                
            self.transport.write(response.encode('utf-8'))
            logger.info(f"Sent login ACK to {parsed['device_id']}")
            
        except Exception as e:
            logger.error(f"Error sending login ACK: {e}")
            
    async def send_heartbeat_ack(self, parsed: Dict[str, Any]):
        """Send heartbeat acknowledgment"""
        try:
            if not self.transport or self.transport.is_closing():
                return
                
            if parsed['protocol'] == 'tk103':
                response = f"({parsed['device_id']}AP04)"
            else:
                response = f"[{parsed['device_id']}*0002*HEART]"
                
            self.transport.write(response.encode('utf-8'))
            logger.debug(f"Sent heartbeat ACK to {parsed['device_id']}")
            
        except Exception as e:
            logger.error(f"Error sending heartbeat ACK: {e}")
            
    async def _send_heartbeat(self):
        """Send periodic heartbeat to keep connection alive"""
        try:
            while True:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                
                if not self.transport or self.transport.is_closing():
                    break
                    
                # Send heartbeat based on protocol
                if self.device_id:
                    if self.buffer and self.buffer.startswith(b'['):
                        heartbeat = f"[{self.device_id}*0002*HEART]"
                    else:
                        heartbeat = f"({self.device_id}BP04)"
                        
                    self.transport.write(heartbeat.encode('utf-8'))
                    logger.debug(f"Sent heartbeat to {self.device_id}")
                    
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Error in heartbeat task: {e}")
            
    async def _monitor_timeout(self):
        """Monitor connection timeout"""
        try:
            while True:
                await asyncio.sleep(30)  # Check every 30 seconds
                
                if time.time() - self.last_activity > CONNECTION_TIMEOUT:
                    logger.warning(f"Connection timeout for {self.peername}")
                    if self.transport and not self.transport.is_closing():
                        self.transport.close()
                    break
                    
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Error in timeout monitor: {e}")


class GPSTrackerTCPServer:
    """Production-ready TCP server for GPS trackers"""
    
    def __init__(self, host: str = '0.0.0.0', port: int = 9090):
        self.host = host
        self.port = port
        self.server = None
        self.active_connections = {}
        self.conn_manager = ConnectionManager()
        self.rate_limiter = RateLimiter()
        self.packet_validator = PacketValidator()
        self.stats = {
            'start_time': None,
            'messages_received': 0,
            'valid_locations': 0,
            'errors': 0,
            'consecutive_errors': 0,
            'restarts': 0
        }
        self.shutdown_event = asyncio.Event()
        self.should_restart = False
        
    async def start(self):
        """Start the TCP server with error recovery"""
        try:
            self.stats['start_time'] = datetime.now()
            
            loop = asyncio.get_event_loop()
            
            # Set up signal handlers for graceful shutdown
            for sig in (signal.SIGTERM, signal.SIGINT):
                loop.add_signal_handler(
                    sig, lambda: asyncio.create_task(self.shutdown())
                )
            
            # Create server with SO_REUSEADDR
            self.server = await loop.create_server(
                lambda: GPSClientProtocol(self),
                self.host,
                self.port,
                reuse_address=True,
                reuse_port=True
            )
            
            logger.info(f"GPS TCP Server started on {self.host}:{self.port}")
            logger.info(f"Configuration:")
            logger.info(f"  - Max connections: {MAX_CONNECTIONS}")
            logger.info(f"  - Max per IP: {MAX_CONNECTIONS_PER_IP}")
            logger.info(f"  - Connection timeout: {CONNECTION_TIMEOUT}s")
            logger.info(f"  - Rate limit: {RATE_LIMIT_MESSAGES} msg/{RATE_LIMIT_WINDOW}s")
            
            # Start monitoring task
            monitor_task = asyncio.create_task(self._monitor_server())
            
            async with self.server:
                await self.shutdown_event.wait()
                
            monitor_task.cancel()
            
        except Exception as e:
            logger.error(f"Error starting TCP server: {e}")
            raise
            
    async def shutdown(self):
        """Graceful shutdown"""
        logger.info("Shutting down GPS TCP Server...")
        
        # Close all connections
        for conn in list(self.active_connections.values()):
            if conn.transport and not conn.transport.is_closing():
                conn.transport.close()
                
        # Stop accepting new connections
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            
        self.shutdown_event.set()
        logger.info("GPS TCP Server stopped")
        
    async def _monitor_server(self):
        """Monitor server health and log statistics"""
        try:
            error_check_interval = 10  # Check errors every 10 seconds
            last_error_check = time.time()
            last_error_count = 0
            
            while True:
                await asyncio.sleep(10)  # Check every 10 seconds
                
                now = time.time()
                
                # Check for error rate
                if now - last_error_check >= error_check_interval:
                    error_increase = self.stats['errors'] - last_error_count
                    if error_increase >= AUTO_RESTART_ON_ERRORS:
                        logger.error(f"High error rate detected ({error_increase} errors in {error_check_interval}s)")
                        self.stats['consecutive_errors'] += error_increase
                        
                        if self.stats['consecutive_errors'] >= AUTO_RESTART_ON_ERRORS * 2:
                            logger.critical("Too many consecutive errors, requesting restart")
                            self.should_restart = True
                            self.shutdown_event.set()
                            return
                    else:
                        self.stats['consecutive_errors'] = 0
                        
                    last_error_count = self.stats['errors']
                    last_error_check = now
                
                # Log stats every minute
                if int(now) % 60 == 0:
                    uptime = datetime.now() - self.stats['start_time']
                    logger.info(f"Server Statistics:")
                    logger.info(f"  - Uptime: {uptime}")
                    logger.info(f"  - Active connections: {len(self.active_connections)}")
                    logger.info(f"  - Messages received: {self.stats['messages_received']}")
                    logger.info(f"  - Valid locations: {self.stats['valid_locations']}")
                    logger.info(f"  - Errors: {self.stats['errors']}")
                    logger.info(f"  - Restarts: {self.stats['restarts']}")
                    logger.info(f"  - Blacklisted IPs: {len(self.conn_manager.blacklisted_ips)}")
                    
                    # Wait to avoid duplicate logs
                    await asyncio.sleep(1)
                
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Error in server monitor: {e}")
            self.stats['errors'] += 1
            
    def get_status(self):
        """Get detailed server status"""
        uptime = datetime.now() - self.stats['start_time'] if self.stats['start_time'] else timedelta(0)
        
        return {
            'running': self.server is not None and self.server.is_serving(),
            'uptime': str(uptime),
            'active_connections': len(self.active_connections),
            'total_messages': self.stats['messages_received'],
            'valid_locations': self.stats['valid_locations'],
            'blacklisted_ips': list(self.conn_manager.blacklisted_ips),
            'connections': [
                {
                    'id': conn_id,
                    'device_id': conn.device_id,
                    'peername': str(conn.peername),
                    'messages': conn.message_count,
                    'last_activity': datetime.fromtimestamp(conn.last_activity).isoformat()
                }
                for conn_id, conn in self.active_connections.items()
            ]
        }


async def run_server_with_restart(host: str, port: int, max_restarts: int = 10):
    """Run server with auto-restart capability"""
    restart_count = 0
    
    while restart_count < max_restarts:
        server = GPSTrackerTCPServer(host=host, port=port)
        server.stats['restarts'] = restart_count
        
        try:
            logger.info(f"Starting server (attempt {restart_count + 1}/{max_restarts})")
            await server.start()
            
            # Check if restart was requested
            if server.should_restart:
                restart_count += 1
                logger.warning(f"Server restart requested, restarting... ({restart_count}/{max_restarts})")
                await asyncio.sleep(5)  # Brief pause before restart
                continue
            else:
                break  # Normal shutdown
                
        except Exception as e:
            logger.error(f"Server crashed: {e}")
            restart_count += 1
            
            if restart_count < max_restarts:
                logger.info(f"Restarting server in 10 seconds... ({restart_count}/{max_restarts})")
                await asyncio.sleep(10)
            else:
                logger.critical("Maximum restart attempts reached, giving up")
                break
                
        finally:
            await server.shutdown()
            
    logger.info("Server shutdown complete")


async def main():
    """Run the production GPS TCP server with auto-restart"""
    
    # Configure logging with rotation
    import logging.handlers
    
    # Create logs directory
    import os
    os.makedirs('logs', exist_ok=True)
    
    # Set up rotating file handler
    file_handler = logging.handlers.RotatingFileHandler(
        'logs/gps_tcp_server.log',
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5
    )
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),  # Console
            file_handler  # Rotating file
        ]
    )
    
    # Get port from command line or use default
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9090
    
    # Run server with auto-restart
    await run_server_with_restart('0.0.0.0', port)


if __name__ == "__main__":
    asyncio.run(main())