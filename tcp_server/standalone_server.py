#!/usr/bin/env python3
"""
Standalone GPS TCP Server with raw data logging and debugging
This runs as a separate Docker service but shares database and Redis with FastAPI
"""
import asyncio
import logging
import os
import sys
from pathlib import Path
import time
from datetime import datetime
import binascii

# Add parent directory to path to import shared modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from gps_tcp_server import GPSTrackerTCPServer, GPSClientProtocol
from tcp_server.protocols import parse_message, create_response
from tcp_server.jt808_processor import jt808_processor
from database.db_conf import engine, test_db_connection
from redis_queue_system.redis_queue import redis_queue
from config import settings
import signal

# Configure logging with DEBUG level for raw data inspection
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('gps_tcp_raw.log', mode='a')
    ]
)
logger = logging.getLogger(__name__)


class RawLoggingProtocol(GPSClientProtocol):
    """Enhanced protocol with raw data logging and JT808 support"""
    
    def __init__(self, server):
        super().__init__(server)
        self.last_parsed = None
    
    def connection_made(self, transport):
        """Log raw connection details"""
        peername = transport.get_extra_info('peername')
        
        # Skip verbose logging for localhost health checks
        is_localhost = peername and peername[0] in ('127.0.0.1', 'localhost', '::1')
        
        if not is_localhost:
            logger.info("=" * 60)
            logger.info(f"🔌 NEW CONNECTION ESTABLISHED")
            logger.info(f"  Source IP: {peername[0] if peername else 'unknown'}")
            logger.info(f"  Source Port: {peername[1] if peername else 'unknown'}")
            logger.info(f"  Timestamp: {datetime.now().isoformat()}")
            logger.info(f"  Transport: {transport}")
            logger.info("=" * 60)
        else:
            # Simple log for health checks
            logger.debug(f"Health check from {peername}")
        
        # Store flag for later use
        self.is_localhost = is_localhost
        
        # Call parent implementation
        super().connection_made(transport)
    
    def data_received(self, data):
        """Log raw data at byte level before processing"""
        try:
            # Process localhost connections normally if they contain JT808 data
            if hasattr(self, 'is_localhost') and self.is_localhost:
                # Check if this might be JT808 test data (starts with 0x7E)
                if data[0:1] == b'\x7E':
                    logger.info(f"JT808 test data from localhost: {len(data)} bytes")
                    # Continue processing below
                else:
                    logger.debug(f"Health check data from {self.peername}: {len(data)} bytes")
                    super().data_received(data)
                    return
            
            # Log raw bytes for real connections
            logger.info("=" * 60)
            logger.info(f"📨 RAW DATA RECEIVED from {self.peername}")
            logger.info(f"  Timestamp: {datetime.now().isoformat()}")
            logger.info(f"  Size: {len(data)} bytes")
            logger.info(f"  Raw bytes: {data}")
            hex_data = binascii.hexlify(data).decode('ascii')
            logger.info(f"  Hex dump: {hex_data}")
            
            # Try to decode as various encodings
            for encoding in ['utf-8', 'ascii', 'latin-1', 'cp1252']:
                try:
                    decoded = data.decode(encoding)
                    logger.info(f"  Decoded ({encoding}): {repr(decoded)}")
                    # Show printable version
                    printable = ''.join(c if c.isprintable() or c in '\r\n\t' else f'\\x{ord(c):02x}' for c in decoded)
                    logger.info(f"  Printable: {printable}")
                    break
                except Exception as e:
                    logger.debug(f"  Could not decode as {encoding}: {e}")
            
            # Show ASCII representation with non-printable as dots
            ascii_repr = ''.join(chr(b) if 32 <= b < 127 else '.' for b in data)
            logger.info(f"  ASCII view: {ascii_repr}")
            
            # Hex dump in traditional format (16 bytes per line)
            hex_lines = []
            for i in range(0, len(data), 16):
                chunk = data[i:i+16]
                hex_part = ' '.join(f'{b:02x}' for b in chunk)
                ascii_part = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
                hex_lines.append(f"  {i:04x}: {hex_part:<48} {ascii_part}")
            if hex_lines:
                logger.info("  Hex dump (formatted):")
                for line in hex_lines:
                    logger.info(line)
            
            # Try to parse with JT808 protocol handler
            parsed = None
            response = None
            
            # Check if this is JT808 binary protocol (starts with 0x7E)
            if data[0:1] == b'\x7E':
                logger.info("  🔍 Detected JT808 binary protocol (0x7E frame)")
                from tcp_server.protocols.jt808_production import JT808ProductionHandler
                jt808_handler = JT808ProductionHandler()
                parsed = jt808_handler.parse_message(hex_data)
                if parsed:
                    logger.info("  ✅ JT808 MESSAGE PARSED:")
                    logger.info(f"    Message ID: 0x{parsed.get('msg_id', 0):04X}")
                    logger.info(f"    Device ID: {parsed.get('device_id')}")
                    logger.info(f"    Message Type: {parsed.get('message')}")
            elif parse_message:
                # Try parsing with other protocol handlers
                parsed = parse_message(hex_data)
            
            if parsed:
                    logger.info("  ✅ PROTOCOL PARSED:")
                    logger.info(f"    Protocol: {parsed.get('protocol')}")
                    logger.info(f"    Message: {parsed.get('message')}")
                    logger.info(f"    Device ID: {parsed.get('device_id')}")
                    
                    # Process GPS data through JT808 processor
                    if parsed.get('protocol') == 'JT808' and parsed.get('msg_id') == 0x0200:
                        # Location report - process through validator and queue
                        asyncio.create_task(self._process_location_data(parsed))
                    
                    # Create and send response
                    if parsed.get('protocol') == 'JT808':
                        # Check if device is registered for registration and location messages
                        success = True
                        device_id = parsed.get('device_id')
                        
                        if parsed.get('msg_id') == 0x0100:  # Terminal Registration
                            # Validate device registration
                            if device_id:
                                registration = jt808_processor._validate_device(device_id)
                                success = registration is not None
                                if not success:
                                    logger.warning(f"    ⚠️ Device {device_id} not registered - sending failure response")
                                else:
                                    logger.info(f"    ✅ Device {device_id} is registered - sending success response")
                        elif parsed.get('msg_id') == 0x0200:  # Location Report
                            # Also validate for location reports - don't ACK if not registered
                            if device_id:
                                registration = jt808_processor._validate_device(device_id)
                                success = registration is not None
                                if not success:
                                    logger.warning(f"    ⚠️ Device {device_id} not registered - rejecting location report")
                        
                        # Use JT808 handler to create response
                        from tcp_server.protocols.jt808_production import JT808ProductionHandler
                        jt808_handler = JT808ProductionHandler()
                        response = jt808_handler.create_response(parsed, success=success)
                    elif create_response:
                        response = create_response(parsed, success=True)
                    
                    if response:
                            # Convert hex response to bytes
                            response_bytes = bytes.fromhex(response)
                            logger.info(f"  📤 SENDING ACK RESPONSE:")
                            logger.info(f"    Message Type: {parsed.get('message', 'Unknown')}")
                            logger.info(f"    Response Hex: {response}")
                            logger.info(f"    Response Bytes: {response_bytes}")
                            
                            # Identify response type
                            if len(response_bytes) > 2:
                                msg_id = (response_bytes[1] << 8) | response_bytes[2] if response_bytes[0] == 0x7E else 0
                                if msg_id == 0x8100:
                                    logger.info(f"    ✅ Registration ACK (0x8100) sent to {self.peername}!")
                                elif msg_id == 0x8001:
                                    logger.info(f"    ✅ General ACK (0x8001) sent to {self.peername}!")
                                else:
                                    logger.info(f"    ✅ ACK sent to {self.peername}!")
                            
                            self.transport.write(response_bytes)
                            logger.info(f"    ✅ ACK DELIVERED successfully!")
            
            logger.info("=" * 60)
            
            # Store parsed data for parent class
            self.last_parsed = parsed
            
        except Exception as e:
            logger.error(f"Error in data_received: {e}")
        
        # Don't call parent if we already handled it
        if not parsed:
            super().data_received(data)
    
    async def _process_location_data(self, parsed_data):
        """Process location data through JT808 processor"""
        try:
            queued = await jt808_processor.process_gps_data(parsed_data)
            if queued:
                logger.info(f"    ✅ GPS data queued to Redis for device {parsed_data.get('device_id')}")
            else:
                logger.warning(f"    ⚠️ GPS data not queued - device {parsed_data.get('device_id')} may not be registered")
        except Exception as e:
            logger.error(f"Error processing location data: {e}")
    
    def connection_lost(self, exc):
        """Log connection closure"""
        # Skip verbose logging for localhost
        if hasattr(self, 'is_localhost') and self.is_localhost:
            logger.debug(f"Health check disconnected from {self.peername}")
        else:
            logger.info("=" * 60)
            logger.info(f"🔌 CONNECTION CLOSED from {self.peername}")
            logger.info(f"  Reason: {exc if exc else 'Normal closure'}")
            logger.info(f"  Duration: {time.time() - self.last_activity:.2f} seconds")
            logger.info(f"  Messages received: {self.message_count}")
            logger.info("=" * 60)
        
        # Call parent implementation
        super().connection_lost(exc)


class StandaloneGPSServer(GPSTrackerTCPServer):
    """Extended GPS server with raw data logging and database/Redis integration"""
    
    def __init__(self, host='0.0.0.0', port=None):
        super().__init__(host, port or settings.GPS_TCP_PORT)
        self.redis_queue = None
        self.db_connected = False
        self.raw_data_file = None
        
    async def initialize_connections(self):
        """Initialize database and Redis connections"""
        # Check database connection
        is_connected, message = test_db_connection(max_retries=5)
        if not is_connected:
            logger.error(f"Failed to connect to database: {message}")
            raise RuntimeError(f"Database connection failed: {message}")
        
        logger.info(f"Database connection successful: {message}")
        self.db_connected = True
        
        # Initialize Redis connection (optional - for debugging we can run without it)
        try:
            # Log Redis URL for debugging
            redis_url = settings.get_redis_url()
            logger.info(f"Attempting to connect to Redis at: {redis_url}")
            
            # Connect to Redis
            await redis_queue.connect()
            
            # Test the connection
            if redis_queue.redis_client:
                await redis_queue.redis_client.ping()
                logger.info("Redis connection successful")
                self.redis_queue = redis_queue
            else:
                logger.warning("Redis client not initialized - running without Redis queueing")
                self.redis_queue = None
        except Exception as e:
            logger.warning(f"Redis connection failed: {e}")
            logger.warning("Running without Redis queueing - data will only be logged")
            self.redis_queue = None
    
    async def queue_gps_data_to_redis(self, device_id: str, parsed_data: dict):
        """Log GPS data with enhanced debugging"""
        logger.info("=" * 60)
        logger.info(f"🗺️  PARSED GPS DATA")
        logger.info(f"  Device ID: {device_id}")
        logger.info(f"  Timestamp: {datetime.now().isoformat()}")
        logger.info(f"  Parsed data:")
        for key, value in parsed_data.items():
            logger.info(f"    {key}: {value}")
        logger.info("=" * 60)
        
        # Save to raw data file
        if self.raw_data_file:
            self.raw_data_file.write(f"{datetime.now().isoformat()} | Device: {device_id} | Data: {parsed_data}\n")
            self.raw_data_file.flush()
        
        # Redis queueing disabled for debugging
        # TODO: Implement Redis queueing when ready
    
    async def start(self):
        """Start the GPS TCP server with raw logging protocol"""
        await self.initialize_connections()
        
        # Open raw data file for logging
        self.raw_data_file = open('gps_raw_data.txt', 'a')
        logger.info(f"Raw data logging to: gps_raw_data.txt")
        
        # Override the protocol factory to use our enhanced logging version
        loop = asyncio.get_running_loop()
        
        # Create the server with our custom protocol
        server = await loop.create_server(
            lambda: RawLoggingProtocol(self),
            self.host,
            self.port,
            reuse_address=True,
            reuse_port=True
        )
        
        self.server = server
        
        # Log server startup
        logger.info("=" * 60)
        logger.info(f"🚀 GPS TCP SERVER STARTED")
        logger.info(f"  Host: {self.host}")
        logger.info(f"  Port: {self.port}")
        logger.info(f"  Protocol: Enhanced with raw logging")
        logger.info(f"  Accepting: ANY data format")
        logger.info(f"  Log files:")
        logger.info(f"    - Console: STDOUT")
        logger.info(f"    - Raw logs: gps_tcp_raw.log")
        logger.info(f"    - GPS data: gps_tcp_data.log")
        logger.info(f"    - Raw data: gps_raw_data.txt")
        logger.info("=" * 60)
        
        # Hook up the queue method
        original_queue_method = RawLoggingProtocol.queue_gps_data
        
        async def enhanced_queue_gps_data(client_self, parsed):
            # Call original logging method
            await original_queue_method(client_self, parsed)
            
            # Add our enhanced logging
            if client_self.device_id:
                await self.queue_gps_data_to_redis(client_self.device_id, parsed)
        
        # Monkey patch the method
        RawLoggingProtocol.queue_gps_data = enhanced_queue_gps_data
        
        # Keep server running
        async with server:
            await server.serve_forever()
    
    async def shutdown(self):
        """Clean shutdown"""
        logger.info("Shutting down GPS TCP server...")
        if self.raw_data_file:
            self.raw_data_file.close()
        await super().shutdown()


async def main():
    """Main entry point for standalone GPS TCP server"""
    server = None
    
    try:
        # Create and start server
        server = StandaloneGPSServer(
            host=os.getenv('GPS_TCP_HOST', '0.0.0.0'),
            port=int(os.getenv('GPS_TCP_PORT', settings.GPS_TCP_PORT))
        )
        
        logger.info("\n" + "=" * 60)
        logger.info("🚀 INITIALIZING STANDALONE GPS TCP SERVER")
        logger.info(f"  Configuration:")
        logger.info(f"    Host: {server.host}")
        logger.info(f"    Port: {server.port}")
        logger.info(f"    Database: {os.getenv('DATABASE_URL', 'Not configured')}")
        logger.info(f"    Redis: {settings.get_redis_url()}")
        logger.info(f"    Raw logging: ENABLED")
        logger.info("=" * 60 + "\n")
        
        # Setup signal handlers for graceful shutdown
        loop = asyncio.get_running_loop()
        
        async def shutdown_handler():
            logger.info("Received shutdown signal")
            if server:
                await server.shutdown()
            loop.stop()
        
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(
                sig,
                lambda: asyncio.create_task(shutdown_handler())
            )
        
        # Start server
        await server.start()
        
    except Exception as e:
        logger.error(f"Failed to start GPS TCP server: {e}")
        sys.exit(1)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Server crashed: {e}")
        sys.exit(1)