"""
Test client to simulate GPS tracker connections
"""
import asyncio
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class GPSTestClient:
    """Simulate a GPS tracker client"""
    
    def __init__(self, host='89.47.162.7', port=5002):  # Production server
        self.host = host
        self.port = port
        self.reader = None
        self.writer = None
        
    async def connect(self):
        """Connect to the GPS TCP server"""
        self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
        logger.info(f"Connected to {self.host}:{self.port}")
        
    async def disconnect(self):
        """Disconnect from the server"""
        if self.writer:
            self.writer.close()
            await self.writer.wait_closed()
            logger.info("Disconnected")
            
    async def send_message(self, message: str):
        """Send a message to the server"""
        self.writer.write(message.encode('utf-8'))
        await self.writer.drain()
        logger.info(f"Sent: {message}")
        
        # Try to read response
        try:
            data = await asyncio.wait_for(self.reader.read(1024), timeout=2.0)
            response = data.decode('utf-8')
            logger.info(f"Received: {response}")
            return response
        except asyncio.TimeoutError:
            logger.warning("No response received (timeout)")
            return None
            
    async def test_watch_protocol(self):
        """Test watch protocol messages (TK905B)"""
        logger.info("\n=== Testing Watch Protocol (TK905B) ===")
        
        # Login message
        await self.send_message("[3G*2256002206*0008*LK,0,0,100]")
        
        # GPS location message
        now = datetime.now()
        date_str = now.strftime("%d%m%y")
        time_str = now.strftime("%H%M%S")
        
        # Example location: San Francisco (37.7749, -122.4194)
        gps_message = f"[3G*2256002206*0079*UD2,{date_str},{time_str},A,37.7749,N,122.4194,W,5.5,180.0,100.0,8,90,85,0,0,00000008,2,0,268,3,3010,51042,146,3010,51043,132]"
        await self.send_message(gps_message)
        
        # Invalid GPS (no fix)
        invalid_gps = f"[3G*2256002206*0079*UD2,{date_str},{time_str},V,0.0000,N,0.0000,W,0.0,0.0,0.0,0,80,75,0,0,00000000,0,0,0,0,0,0,0,0,0,0]"
        await self.send_message(invalid_gps)
        
        # Alarm message
        await self.send_message("[3G*2256002206*0012*AL,01,100,90]")
        
    async def test_tk103_protocol(self):
        """Test TK103 protocol messages"""
        logger.info("\n=== Testing TK103 Protocol ===")
        
        # Login message
        await self.send_message("(013632651491,BP05,013632651491,101214,V,0000.0000N,00000.0000E,000.0,193148,000.0)")
        
        # GPS location message
        now = datetime.now()
        date_str = now.strftime("%d%m%y")
        time_str = now.strftime("%H%M%S")
        
        # Example location: New York (40.7128, -74.0060)
        gps_message = f"(013632651491,BR00,{date_str},A,4042.7680N,07400.3600W,005.2,{time_str},240.5)"
        await self.send_message(gps_message)
        
        # Invalid GPS
        invalid_gps = f"(013632651491,BR00,{date_str},V,0000.0000N,00000.0000E,000.0,{time_str},000.0)"
        await self.send_message(invalid_gps)
        
    async def run_tests(self):
        """Run all test scenarios"""
        try:
            await self.connect()
            
            # Test watch protocol
            await self.test_watch_protocol()
            await asyncio.sleep(1)
            
            # Test TK103 protocol
            await self.test_tk103_protocol()
            
        finally:
            await self.disconnect()


async def main():
    """Run the test client"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    client = GPSTestClient()
    await client.run_tests()


if __name__ == "__main__":
    asyncio.run(main())