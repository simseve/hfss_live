#!/usr/bin/env python3
"""
Test 10 devices sending batches of GPS points concurrently
Simulates realistic GPS tracker fleet behavior
"""
import asyncio
import logging
import random
from datetime import datetime, timedelta
import time

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(message)s'
)
logger = logging.getLogger(__name__)


class GPSDeviceSimulator:
    """Simulates a single GPS device sending batches"""
    
    def __init__(self, device_id: str, host: str = '89.47.162.7', port: int = 5002):
        self.device_id = device_id
        self.host = host
        self.port = port
        self.reader = None
        self.writer = None
        self.connected = False
        self.messages_sent = 0
        self.points_sent = 0
        
        # Random starting position in Zurich area
        self.base_lat = 47.3769 + random.uniform(-0.05, 0.05)
        self.base_lon = 8.5417 + random.uniform(-0.05, 0.05)
        self.speed_base = random.uniform(15, 35)  # Base speed km/h
        
    async def connect(self):
        """Connect to GPS TCP server"""
        try:
            self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
            self.connected = True
            logger.info(f"Device {self.device_id}: Connected ✅")
            
            # Send login
            login = f"[3G*{self.device_id}*0008*LK,0,0,95]"
            self.writer.write(login.encode())
            await self.writer.drain()
            
            # Read response
            data = await asyncio.wait_for(self.reader.read(1024), timeout=2.0)
            response = data.decode('utf-8')
            if "OK" in response:
                logger.info(f"Device {self.device_id}: Login successful")
            self.messages_sent += 1
            
        except Exception as e:
            logger.error(f"Device {self.device_id}: Connection failed - {e}")
            self.connected = False
            
    async def send_batch(self, num_points: int = 10):
        """Send a batch of GPS points using UD3 format"""
        if not self.connected:
            return False
            
        try:
            # Generate batch of points (1Hz collection)
            base_time = datetime.now() - timedelta(seconds=num_points)
            records = []
            
            for i in range(num_points):
                timestamp = base_time + timedelta(seconds=i)
                date_str = timestamp.strftime("%d%m%y")
                time_str = timestamp.strftime("%H%M%S")
                
                # Simulate movement
                lat = self.base_lat + (i * 0.0001 * random.uniform(0.8, 1.2))
                lon = self.base_lon + (i * 0.0001 * random.uniform(0.8, 1.2))
                speed = self.speed_base + random.uniform(-5, 5)
                heading = 45 + random.uniform(-30, 30)
                alt = 410 + random.uniform(-5, 5)
                
                # Convert to NMEA format
                lat_deg = int(abs(lat))
                lat_min = (abs(lat) - lat_deg) * 60
                lat_nmea = f"{lat_deg:02d}{lat_min:07.4f}"
                
                lon_deg = int(abs(lon))
                lon_min = (abs(lon) - lon_deg) * 60
                lon_nmea = f"{lon_deg:03d}{lon_min:07.4f}"
                
                record = f"{date_str},{time_str},A,{lat_nmea},N,{lon_nmea},E,{speed:.1f},{heading:.1f},{alt:.1f}"
                records.append(record)
            
            # Create UD3 batch message
            batch_data = f"UD3,{len(records)}," + ";".join(records)
            length = f"{len(batch_data):04X}"
            message = f"[3G*{self.device_id}*{length}*{batch_data}]"
            
            # Send message
            self.writer.write(message.encode())
            await self.writer.drain()
            self.messages_sent += 1
            self.points_sent += num_points
            
            # Try to read response
            try:
                data = await asyncio.wait_for(self.reader.read(1024), timeout=1.0)
                response = data.decode('utf-8')
                if "OK" in response:
                    logger.info(f"Device {self.device_id}: Batch sent successfully ({num_points} points)")
                    return True
                else:
                    logger.warning(f"Device {self.device_id}: Batch failed - {response}")
                    return False
            except asyncio.TimeoutError:
                logger.warning(f"Device {self.device_id}: No response for batch")
                return False
                
        except Exception as e:
            logger.error(f"Device {self.device_id}: Error sending batch - {e}")
            return False
            
    async def disconnect(self):
        """Disconnect from server"""
        if self.writer:
            self.writer.close()
            await self.writer.wait_closed()
            self.connected = False
            logger.info(f"Device {self.device_id}: Disconnected. Sent {self.messages_sent} messages, {self.points_sent} GPS points")
            
    async def run_simulation(self, duration: int = 30, batch_size: int = 10, interval: int = 10):
        """
        Run device simulation
        Args:
            duration: Total simulation time in seconds
            batch_size: Number of points per batch
            interval: Seconds between batches
        """
        await self.connect()
        
        if not self.connected:
            return
            
        start_time = time.time()
        batch_count = 0
        
        try:
            while time.time() - start_time < duration:
                # Send batch
                success = await self.send_batch(batch_size)
                if success:
                    batch_count += 1
                
                # Wait for next batch (with some randomness)
                wait_time = interval + random.uniform(-2, 2)
                await asyncio.sleep(max(1, wait_time))
                
        except Exception as e:
            logger.error(f"Device {self.device_id}: Simulation error - {e}")
        finally:
            await self.disconnect()
            
        return batch_count


async def run_fleet_simulation(num_devices: int = 10, host: str = '89.47.162.7', port: int = 5002):
    """Run simulation with multiple devices"""
    logger.info("="*60)
    logger.info(f"🚀 STARTING FLEET SIMULATION WITH {num_devices} DEVICES")
    logger.info("="*60)
    
    # Create devices with unique IDs
    devices = []
    for i in range(num_devices):
        device_id = f"{1000 + i:04d}"  # 1000, 1001, etc. (numeric only)
        device = GPSDeviceSimulator(device_id, host=host, port=port)
        devices.append(device)
    
    logger.info(f"Created {num_devices} virtual GPS devices")
    logger.info("Each device will send batches of 10 GPS points every ~10 seconds")
    logger.info("")
    
    # Run all devices concurrently
    start_time = time.time()
    
    # Start devices with slight delays to avoid connection burst
    tasks = []
    for i, device in enumerate(devices):
        # Add small delay between device starts
        await asyncio.sleep(random.uniform(0.1, 0.5))
        task = asyncio.create_task(device.run_simulation(
            duration=30,      # Run for 30 seconds
            batch_size=10,    # 10 points per batch
            interval=10       # Send every 10 seconds
        ))
        tasks.append(task)
    
    logger.info("All devices started, running simulation...")
    
    # Wait for all devices to complete
    results = await asyncio.gather(*tasks)
    
    # Calculate statistics
    elapsed = time.time() - start_time
    total_batches = sum(r for r in results if r)
    total_messages = sum(d.messages_sent for d in devices)
    total_points = sum(d.points_sent for d in devices)
    
    logger.info("")
    logger.info("="*60)
    logger.info("📊 SIMULATION COMPLETE - STATISTICS")
    logger.info("="*60)
    logger.info(f"Duration: {elapsed:.1f} seconds")
    logger.info(f"Devices: {num_devices}")
    logger.info(f"Total batches sent: {total_batches}")
    logger.info(f"Total messages: {total_messages}")
    logger.info(f"Total GPS points: {total_points}")
    logger.info(f"Average points per device: {total_points/num_devices:.1f}")
    logger.info(f"Points per second: {total_points/elapsed:.1f}")
    logger.info("")
    
    # Per-device summary
    logger.info("Per-device summary:")
    for device in devices:
        logger.info(f"  {device.device_id}: {device.messages_sent} messages, {device.points_sent} points")
    
    logger.info("")
    logger.info("✅ Fleet simulation completed successfully!")
    

async def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Multi-device GPS batch simulator')
    parser.add_argument('--devices', type=int, default=10, help='Number of devices to simulate')
    parser.add_argument('--host', default='localhost', help='Server host')
    parser.add_argument('--port', type=int, default=5002, help='Server port')
    
    args = parser.parse_args()
    
    logger.info("🛰️  GPS FLEET BATCH SIMULATION")
    logger.info(f"Simulating {args.devices} GPS trackers sending batches of location data")
    logger.info(f"Server: {args.host}:{args.port}")
    logger.info("")
    
    await run_fleet_simulation(args.devices, host=args.host, port=args.port)


if __name__ == "__main__":
    asyncio.run(main())