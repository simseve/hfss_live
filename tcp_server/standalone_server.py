#!/usr/bin/env python3
"""
Standalone GPS TCP Server with database and Redis integration
This runs as a separate Docker service but shares database and Redis with FastAPI
"""
import asyncio
import logging
import os
import sys
from pathlib import Path

# Add parent directory to path to import shared modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from gps_tcp_server import GPSTrackerTCPServer
from database.db_conf import engine, test_db_connection
from redis_queue_system.redis_queue import redis_queue
from config import settings
import signal

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class StandaloneGPSServer(GPSTrackerTCPServer):
    """Extended GPS server with database and Redis integration"""
    
    def __init__(self, host='0.0.0.0', port=None):
        super().__init__(host, port or settings.GPS_TCP_PORT)
        self.redis_queue = None
        self.db_connected = False
        
    async def initialize_connections(self):
        """Initialize database and Redis connections"""
        # Check database connection
        is_connected, message = test_db_connection(max_retries=5)
        if not is_connected:
            logger.error(f"Failed to connect to database: {message}")
            raise RuntimeError(f"Database connection failed: {message}")
        
        logger.info(f"Database connection successful: {message}")
        self.db_connected = True
        
        # Initialize Redis connection
        try:
            # Test Redis connection
            await redis_queue.ping()
            logger.info("Redis connection successful")
            self.redis_queue = redis_queue
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise RuntimeError(f"Redis connection failed: {e}")
    
    async def queue_gps_data_to_redis(self, device_id: str, parsed_data: dict):
        """Queue GPS data to Redis for processing by FastAPI workers"""
        if not self.redis_queue:
            logger.warning("Redis not connected, skipping data queue")
            return
            
        try:
            # Format data for Redis queue (matching FastAPI's expected format)
            queue_data = {
                'device_id': device_id,
                'timestamp': parsed_data.get('timestamp'),
                'latitude': parsed_data.get('latitude'),
                'longitude': parsed_data.get('longitude'),
                'altitude': parsed_data.get('altitude', 0),
                'speed': parsed_data.get('speed', 0),
                'heading': parsed_data.get('heading', 0),
                'satellites': parsed_data.get('satellites', 0),
                'battery': parsed_data.get('battery', 0),
                'valid': parsed_data.get('valid', False),
                'protocol': parsed_data.get('protocol', 'unknown'),
                'raw_data': parsed_data.get('raw_data', '')
            }
            
            # Add to Redis queue
            await self.redis_queue.add_track_points([queue_data])
            logger.debug(f"Queued GPS data for device {device_id}")
            
        except Exception as e:
            logger.error(f"Failed to queue GPS data: {e}")
    
    async def start(self):
        """Start the GPS TCP server with connections initialized"""
        await self.initialize_connections()
        
        # Override the queue_gps_data method in client protocol
        original_queue_method = GPSClientProtocol.queue_gps_data
        
        async def enhanced_queue_gps_data(client_self, parsed):
            # Call original logging method
            await original_queue_method(client_self, parsed)
            
            # Add Redis queueing
            if client_self.device_id and parsed.get('valid'):
                await self.queue_gps_data_to_redis(client_self.device_id, parsed)
        
        # Monkey patch the method
        from gps_tcp_server import GPSClientProtocol
        GPSClientProtocol.queue_gps_data = enhanced_queue_gps_data
        
        # Start the server
        await super().start()


async def main():
    """Main entry point for standalone GPS TCP server"""
    server = None
    
    try:
        # Create and start server
        server = StandaloneGPSServer(
            host=os.getenv('GPS_TCP_HOST', '0.0.0.0'),
            port=int(os.getenv('GPS_TCP_PORT', settings.GPS_TCP_PORT))
        )
        
        logger.info(f"Starting GPS TCP Server on {server.host}:{server.port}")
        
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