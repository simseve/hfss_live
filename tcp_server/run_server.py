#!/usr/bin/env python3
"""
Run the GPS TCP Server
Usage: python tcp_server/run_server.py [port]
"""
import sys
import os
import asyncio
import logging

# Add parent directory to path so imports work
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tcp_server.gps_tcp_server import GPSTrackerTCPServer

async def main():
    """Run the GPS TCP server"""
    
    # Get port from command line or use default
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9090
    
    # Configure logging
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),  # Console output
            logging.FileHandler('gps_tcp_server.log')  # File output
        ]
    )
    
    logger = logging.getLogger(__name__)
    
    # Start server
    server = GPSTrackerTCPServer(
        host='0.0.0.0',
        port=port
    )
    
    logger.info(f"Starting GPS TCP Server on port {port}")
    logger.info("Server will log all received data to:")
    logger.info("  - Console output")
    logger.info("  - gps_tcp_server.log (server logs)")
    logger.info("  - gps_tcp_data.log (parsed GPS data in JSON)")
    logger.info("Press Ctrl+C to stop")
    
    try:
        await server.start()
    except KeyboardInterrupt:
        logger.info("Shutting down GPS TCP Server...")
        await server.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nServer stopped")