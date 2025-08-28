#!/usr/bin/env python3
"""
Test TK905B UD3 batch message format
"""
import asyncio
import logging
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class BatchTester:
    def __init__(self, host='localhost', port=5002):
        self.host = host
        self.port = port
        self.device_id = "8825100123"
        
    async def connect(self):
        """Connect to server"""
        self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
        logger.info(f"Connected to {self.host}:{self.port}")
        
    async def send_and_receive(self, message: str):
        """Send message and get response"""
        logger.info(f"Sending: {message[:100]}...")
        self.writer.write(message.encode('utf-8'))
        await self.writer.drain()
        
        try:
            data = await asyncio.wait_for(self.reader.read(1024), timeout=2.0)
            response = data.decode('utf-8')
            logger.info(f"Received: {response}")
            return response
        except asyncio.TimeoutError:
            logger.warning("No response (timeout)")
            return None
            
    async def test_single_ud2(self):
        """Test single UD2 message"""
        logger.info("\n=== Testing Single UD2 Message ===")
        
        now = datetime.now()
        date_str = now.strftime("%d%m%y")
        time_str = now.strftime("%H%M%S")
        
        # Single location message
        message = (
            f"[3G*{self.device_id}*0079*UD2,"
            f"{date_str},{time_str},A,"
            f"4722.6140,N,00832.5240,E,"
            f"25.5,180.0,410.0,"
            f"9,85,90,"
            f"0,0,00000008,2,0,268,3,3010,51042,146,3010,51043,132]"
        )
        
        await self.send_and_receive(message)
        
    async def test_batch_ud3(self):
        """Test UD3 batch message format"""
        logger.info("\n=== Testing UD3 Batch Message ===")
        
        # Create 10 points, 1 second apart
        base_time = datetime.now() - timedelta(seconds=10)
        records = []
        
        for i in range(10):
            timestamp = base_time + timedelta(seconds=i)
            date_str = timestamp.strftime("%d%m%y")
            time_str = timestamp.strftime("%H%M%S")
            
            # Simulate movement (slight position changes)
            lat = f"4722.{6140 + i:04d}"
            lon = f"00832.{5240 + i*2:04d}"
            speed = 20 + i * 0.5
            heading = 180 + i * 0.2
            alt = 410 + i * 0.1
            
            # Build record: DATE,TIME,STATUS,LAT,LAT_DIR,LON,LON_DIR,SPEED,HEADING,ALT
            record = f"{date_str},{time_str},A,{lat},N,{lon},E,{speed:.1f},{heading:.1f},{alt:.1f}"
            records.append(record)
        
        # Join records with semicolon
        batch_data = f"UD3,{len(records)}," + ";".join(records)
        
        # Calculate message length in hex
        length = f"{len(batch_data):04X}"
        
        # Build complete message
        message = f"[3G*{self.device_id}*{length}*{batch_data}]"
        
        logger.info(f"Batch message with {len(records)} points, length={len(batch_data)} bytes")
        await self.send_and_receive(message)
        
    async def test_login(self):
        """Test login message"""
        logger.info("\n=== Testing Login Message ===")
        message = f"[3G*{self.device_id}*0008*LK,0,0,95]"
        await self.send_and_receive(message)
        
    async def run_tests(self):
        """Run all tests"""
        try:
            await self.connect()
            
            # Login first
            await self.test_login()
            await asyncio.sleep(1)
            
            # Test single message
            await self.test_single_ud2()
            await asyncio.sleep(2)
            
            # Test batch message
            await self.test_batch_ud3()
            
        finally:
            self.writer.close()
            await self.writer.wait_closed()
            logger.info("Disconnected")


async def main():
    tester = BatchTester()
    await tester.run_tests()


if __name__ == "__main__":
    asyncio.run(main())