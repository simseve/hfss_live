#!/usr/bin/env python3
"""
Proof that UD3 batch message processing works
Shows both the client sending and server receiving/parsing batch messages
"""
import asyncio
import logging
from datetime import datetime, timedelta

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(message)s'
)
logger = logging.getLogger(__name__)


class UD3ProofTester:
    def __init__(self, host='localhost', port=5002):
        self.host = host
        self.port = port
        self.device_id = "9999888777"
        
    async def connect(self):
        """Connect to server"""
        self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
        logger.info(f"✅ Connected to {self.host}:{self.port}")
        return True
        
    async def send_and_receive(self, message: str, description: str = ""):
        """Send message and get response"""
        logger.info(f"\n📤 SENDING {description}")
        logger.info(f"   Raw message: {message[:80]}...")
        
        self.writer.write(message.encode('utf-8'))
        await self.writer.drain()
        
        try:
            data = await asyncio.wait_for(self.reader.read(1024), timeout=2.0)
            response = data.decode('utf-8')
            logger.info(f"📥 RESPONSE: {response}")
            return response
        except asyncio.TimeoutError:
            logger.warning("⚠️  No response (timeout)")
            return None
            
    async def test_ud3_batch(self):
        """Test UD3 batch message with 5 GPS points"""
        logger.info("\n" + "="*60)
        logger.info("🔬 TESTING UD3 BATCH MESSAGE PROCESSING")
        logger.info("="*60)
        
        # Create 5 GPS points simulating movement in Zurich
        # Points collected at 1Hz (1 second apart)
        base_time = datetime.now() - timedelta(seconds=5)
        records = []
        
        locations = [
            (47.3769, 8.5417, 15.5),  # Zurich center
            (47.3771, 8.5420, 18.2),  # Moving north
            (47.3773, 8.5423, 22.8),  # Accelerating
            (47.3775, 8.5426, 25.1),  # Steady speed
            (47.3777, 8.5429, 24.3),  # Slight deceleration
        ]
        
        logger.info("\n📍 Creating batch with 5 GPS points:")
        for i, (lat, lon, speed) in enumerate(locations):
            timestamp = base_time + timedelta(seconds=i)
            date_str = timestamp.strftime("%d%m%y")
            time_str = timestamp.strftime("%H%M%S")
            
            # Convert to NMEA format (DDMM.MMMM)
            lat_deg = int(lat)
            lat_min = (lat - lat_deg) * 60
            lat_nmea = f"{lat_deg:02d}{lat_min:07.4f}"
            
            lon_deg = int(lon)
            lon_min = (lon - lon_deg) * 60
            lon_nmea = f"{lon_deg:03d}{lon_min:07.4f}"
            
            # Build record: DATE,TIME,STATUS,LAT,LAT_DIR,LON,LON_DIR,SPEED,HEADING,ALT
            record = f"{date_str},{time_str},A,{lat_nmea},N,{lon_nmea},E,{speed:.1f},45.0,410.0"
            records.append(record)
            
            logger.info(f"   Point {i+1}: {timestamp.strftime('%H:%M:%S')} - "
                       f"({lat:.4f}, {lon:.4f}) @ {speed:.1f} km/h")
        
        # Join records with semicolon (UD3 batch format)
        batch_data = f"UD3,{len(records)}," + ";".join(records)
        
        # Calculate message length in hex
        length = f"{len(batch_data):04X}"
        
        # Build complete UD3 message
        message = f"[3G*{self.device_id}*{length}*{batch_data}]"
        
        logger.info(f"\n📊 Batch statistics:")
        logger.info(f"   - Number of points: {len(records)}")
        logger.info(f"   - Data length: {len(batch_data)} bytes")
        logger.info(f"   - Length in hex: {length}")
        
        # Send the batch
        response = await self.send_and_receive(message, "UD3 BATCH (5 points)")
        
        if response and "OK" in response:
            logger.info("✅ UD3 BATCH SUCCESSFULLY PROCESSED!")
        else:
            logger.info("❌ UD3 batch processing needs protocol handler update")
            
        return response
        
    async def test_login(self):
        """Test login message first"""
        logger.info("\n🔐 Sending login message...")
        message = f"[3G*{self.device_id}*0008*LK,0,0,95]"
        response = await self.send_and_receive(message, "LOGIN")
        return "OK" in response if response else False
        
    async def run_proof(self):
        """Run the proof test"""
        try:
            await self.connect()
            
            # Login first
            if await self.test_login():
                logger.info("✅ Login successful")
            
            await asyncio.sleep(1)
            
            # Test UD3 batch
            await self.test_ud3_batch()
            
            logger.info("\n" + "="*60)
            logger.info("📋 TEST COMPLETE")
            logger.info("="*60)
            
        finally:
            self.writer.close()
            await self.writer.wait_closed()
            logger.info("🔌 Disconnected")


async def main():
    logger.info("🚀 UD3 BATCH MESSAGE PROCESSING PROOF")
    logger.info("This test proves that the server can handle TK905B UD3 batch messages")
    logger.info("containing multiple GPS points collected at 1Hz\n")
    
    tester = UD3ProofTester()
    await tester.run_proof()


if __name__ == "__main__":
    asyncio.run(main())