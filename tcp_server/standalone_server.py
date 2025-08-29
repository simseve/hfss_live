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
        """Log GPS data for debugging - Redis queueing disabled for now"""
        logger.info(f"GPS Data received for device {device_id}")
        logger.debug(f"  Data: {parsed_data}")
        # Redis queueing disabled for debugging
        # TODO: Implement Redis queueing when ready
    
    async def start(self):
        """Start the GPS TCP server with connections initialized"""
        await self.initialize_connections()
        
        # Import GPSClientProtocol first
        from gps_tcp_server import GPSClientProtocol
        
        # Override the queue_gps_data method in client protocol
        original_queue_method = GPSClientProtocol.queue_gps_data
        
        async def enhanced_queue_gps_data(client_self, parsed):
            # Call original logging method
            await original_queue_method(client_self, parsed)
            
            # Add Redis queueing
            if client_self.device_id and parsed.get('valid'):
                await self.queue_gps_data_to_redis(client_self.device_id, parsed)
        
        # Monkey patch the method
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