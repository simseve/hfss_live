#!/usr/bin/env python3
"""
Stress test with 1000 devices sending data randomly with some spam/malformed messages
Tests server performance under heavy load with realistic and problematic traffic
"""
import asyncio
import logging
import random
import string
from datetime import datetime, timedelta
import time
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(message)s'
)
logger = logging.getLogger(__name__)


class StressDeviceSimulator:
    """Simulates a single GPS device with realistic and problematic behavior"""
    
    def __init__(self, device_id: str, host: str = '89.47.162.7', port: int = 5002, chaos_mode: bool = False):
        self.device_id = device_id
        self.host = host
        self.port = port
        self.chaos_mode = chaos_mode  # Enable spam/malformed messages
        self.reader = None
        self.writer = None
        self.connected = False
        self.messages_sent = 0
        self.points_sent = 0
        self.errors = 0
        
        # Random starting position somewhere in Europe
        self.base_lat = random.uniform(45.0, 55.0)
        self.base_lon = random.uniform(5.0, 15.0)
        self.speed_base = random.uniform(10, 120)  # Variable speeds
        
        # Random behavior pattern
        self.send_interval = random.choice([5, 10, 15, 30, 60])  # Different update frequencies
        self.batch_size = random.choice([1, 5, 10, 20, 50])  # Different batch sizes
        self.reliability = random.uniform(0.7, 1.0)  # Some devices are flaky
        
    async def connect(self, retry: int = 3):
        """Connect to GPS TCP server with retry logic"""
        for attempt in range(retry):
            try:
                self.reader, self.writer = await asyncio.wait_for(
                    asyncio.open_connection(self.host, self.port),
                    timeout=5.0
                )
                self.connected = True
                
                # Send login
                login = f"[3G*{self.device_id}*0008*LK,0,0,{random.randint(50,100)}]"
                self.writer.write(login.encode())
                await self.writer.drain()
                
                # Try to read response (don't wait too long)
                try:
                    await asyncio.wait_for(self.reader.read(1024), timeout=0.5)
                except asyncio.TimeoutError:
                    pass
                
                self.messages_sent += 1
                return True
                
            except Exception as e:
                if attempt == retry - 1:
                    logger.debug(f"Device {self.device_id}: Connection failed after {retry} attempts")
                await asyncio.sleep(random.uniform(0.1, 0.5))
        
        return False
    
    async def send_spam(self):
        """Send various types of malformed/spam messages"""
        if not self.connected or not self.writer:
            return
            
        spam_types = [
            # Malformed protocols
            f"[INVALID*{self.device_id}*TEST]",
            f"[3G*{self.device_id}*",  # Incomplete message
            f"3G*{self.device_id}*0008*LK,0,0,95",  # Missing brackets
            f"[3G*BADID*0008*LK,0,0,95]",  # Invalid device ID
            f"[3G*{self.device_id}*XXXX*LK,0,0,95]",  # Invalid length
            
            # Garbage data
            "".join(random.choices(string.ascii_letters + string.digits, k=100)),
            bytes(random.randint(0, 255) for _ in range(50)).hex(),
            
            # Oversized messages
            f"[3G*{self.device_id}*9999*" + "X" * 10000 + "]",
            
            # Invalid GPS data
            f"[3G*{self.device_id}*0024*UD3,1,INVALID,GPS,DATA]",
            
            # SQL injection attempts (to test security)
            f"[3G*{self.device_id}*0020*'; DROP TABLE gps; --]",
            
            # Empty messages
            "",
            "\n\n\n",
            "\x00" * 10,
        ]
        
        try:
            spam = random.choice(spam_types)
            self.writer.write(spam.encode()[:1024])  # Limit size
            await self.writer.drain()
            self.messages_sent += 1
            logger.debug(f"Device {self.device_id}: Sent spam message")
        except:
            pass
    
    async def send_batch(self, num_points: Optional[int] = None):
        """Send a batch of GPS points using UD3 format"""
        if not self.connected or not self.writer:
            return False
        
        # Random failures based on reliability
        if random.random() > self.reliability:
            return False
        
        # Sometimes send spam instead of valid data
        if self.chaos_mode and random.random() < 0.1:  # 10% spam rate
            await self.send_spam()
            return False
            
        try:
            # Use configured batch size or override
            points_to_send = num_points or self.batch_size
            
            # Generate batch of points
            base_time = datetime.now() - timedelta(seconds=points_to_send)
            records = []
            
            for i in range(points_to_send):
                timestamp = base_time + timedelta(seconds=i)
                date_str = timestamp.strftime("%d%m%y")
                time_str = timestamp.strftime("%H%M%S")
                
                # Simulate movement with some randomness
                lat = self.base_lat + (i * 0.0001 * random.uniform(0.5, 1.5))
                lon = self.base_lon + (i * 0.0001 * random.uniform(0.5, 1.5))
                speed = self.speed_base + random.uniform(-20, 20)
                heading = random.uniform(0, 360)
                alt = random.uniform(0, 2000)
                
                # Convert to NMEA format
                lat_deg = int(abs(lat))
                lat_min = (abs(lat) - lat_deg) * 60
                lat_nmea = f"{lat_deg:02d}{lat_min:07.4f}"
                lat_dir = 'N' if lat >= 0 else 'S'
                
                lon_deg = int(abs(lon))
                lon_min = (abs(lon) - lon_deg) * 60
                lon_nmea = f"{lon_deg:03d}{lon_min:07.4f}"
                lon_dir = 'E' if lon >= 0 else 'W'
                
                record = f"{date_str},{time_str},A,{lat_nmea},{lat_dir},{lon_nmea},{lon_dir},{speed:.1f},{heading:.1f},{alt:.1f}"
                records.append(record)
            
            # Create UD3 batch message
            batch_data = f"UD3,{len(records)}," + ";".join(records)
            length = f"{len(batch_data):04X}"
            message = f"[3G*{self.device_id}*{length}*{batch_data}]"
            
            # Send message
            self.writer.write(message.encode())
            await self.writer.drain()
            self.messages_sent += 1
            self.points_sent += points_to_send
            
            return True
                
        except Exception as e:
            self.errors += 1
            return False
    
    async def disconnect(self):
        """Disconnect from server"""
        try:
            if self.writer:
                self.writer.close()
                await self.writer.wait_closed()
        except:
            pass
        finally:
            self.connected = False
    
    async def run_simulation(self, duration: int = 60):
        """Run device simulation with random behavior"""
        # Try to connect
        if not await self.connect():
            return 0
        
        start_time = time.time()
        batch_count = 0
        
        try:
            # Wait initial delay (respect rate limiting)
            await asyncio.sleep(random.uniform(2, 5))
            
            while time.time() - start_time < duration:
                # Random behavior
                action = random.choices(
                    ['send_batch', 'send_spam', 'disconnect', 'sleep'],
                    weights=[70, 10 if self.chaos_mode else 0, 5, 15]
                )[0]
                
                if action == 'send_batch':
                    if await self.send_batch():
                        batch_count += 1
                    # Wait for next batch
                    await asyncio.sleep(max(2.1, self.send_interval + random.uniform(-2, 2)))
                    
                elif action == 'send_spam' and self.chaos_mode:
                    await self.send_spam()
                    await asyncio.sleep(random.uniform(0.5, 2))
                    
                elif action == 'disconnect':
                    # Simulate connection drop and reconnect
                    await self.disconnect()
                    await asyncio.sleep(random.uniform(1, 5))
                    if not await self.connect():
                        break
                        
                else:  # sleep
                    await asyncio.sleep(random.uniform(5, 15))
                    
        except Exception as e:
            self.errors += 1
            logger.debug(f"Device {self.device_id}: Error - {e}")
        finally:
            await self.disconnect()
            
        return batch_count


async def run_stress_test(num_devices: int = 1000, duration: int = 60, chaos_percentage: float = 0.1, 
                         host: str = '89.47.162.7', port: int = 5002):
    """Run massive stress test with many devices"""
    logger.info("="*70)
    logger.info(f"🔥 MASSIVE STRESS TEST: {num_devices} DEVICES")
    logger.info("="*70)
    logger.info(f"Duration: {duration} seconds")
    logger.info(f"Chaos devices: {int(num_devices * chaos_percentage)} ({chaos_percentage*100:.0f}%)")
    logger.info(f"Target: {host}:{port}")
    logger.info("")
    
    # Create devices
    devices = []
    chaos_count = int(num_devices * chaos_percentage)
    
    for i in range(num_devices):
        # Use numeric IDs as required by server
        device_id = f"{10000 + i}"
        chaos_mode = i < chaos_count  # First N devices will be chaos devices
        device = StressDeviceSimulator(device_id, host=host, port=port, chaos_mode=chaos_mode)
        devices.append(device)
    
    logger.info(f"Created {num_devices} virtual devices")
    logger.info(f"- Normal devices: {num_devices - chaos_count}")
    logger.info(f"- Chaos devices (spam/malformed): {chaos_count}")
    logger.info("")
    logger.info("Starting simulation...")
    logger.info("(This will generate A LOT of traffic!)")
    logger.info("")
    
    # Track progress
    start_time = time.time()
    progress_task = asyncio.create_task(show_progress(devices, duration))
    
    # Start devices in batches to avoid overwhelming connection establishment
    tasks = []
    batch_size = 50  # Start 50 devices at a time
    
    for i in range(0, num_devices, batch_size):
        batch = devices[i:i+batch_size]
        batch_tasks = [
            asyncio.create_task(device.run_simulation(duration))
            for device in batch
        ]
        tasks.extend(batch_tasks)
        
        # Small delay between batches
        if i + batch_size < num_devices:
            await asyncio.sleep(0.5)
            logger.info(f"Started {min(i+batch_size, num_devices)}/{num_devices} devices...")
    
    logger.info(f"All {num_devices} devices started!")
    logger.info("")
    
    # Wait for completion
    results = await asyncio.gather(*tasks, return_exceptions=True)
    progress_task.cancel()
    
    # Calculate statistics
    elapsed = time.time() - start_time
    successful_devices = sum(1 for r in results if r and not isinstance(r, Exception))
    total_batches = sum(r for r in results if r and not isinstance(r, Exception))
    total_messages = sum(d.messages_sent for d in devices)
    total_points = sum(d.points_sent for d in devices)
    total_errors = sum(d.errors for d in devices)
    
    # Find best and worst performers
    devices_by_points = sorted(devices, key=lambda d: d.points_sent, reverse=True)
    
    logger.info("")
    logger.info("="*70)
    logger.info("📊 STRESS TEST RESULTS")
    logger.info("="*70)
    logger.info(f"Duration: {elapsed:.1f} seconds")
    logger.info(f"Total devices: {num_devices}")
    logger.info(f"Successful devices: {successful_devices}")
    logger.info(f"Failed devices: {num_devices - successful_devices}")
    logger.info("")
    logger.info(f"Total messages sent: {total_messages:,}")
    logger.info(f"Total GPS points: {total_points:,}")
    logger.info(f"Total batches: {total_batches:,}")
    logger.info(f"Total errors: {total_errors:,}")
    logger.info("")
    logger.info(f"Messages/second: {total_messages/elapsed:.1f}")
    logger.info(f"Points/second: {total_points/elapsed:.1f}")
    logger.info(f"Avg points/device: {total_points/num_devices:.1f}")
    logger.info("")
    
    # Top performers
    logger.info("Top 5 devices by GPS points sent:")
    for device in devices_by_points[:5]:
        logger.info(f"  {device.device_id}: {device.points_sent} points, {device.messages_sent} messages")
    
    # Chaos device stats
    chaos_devices = [d for d in devices if d.chaos_mode]
    if chaos_devices:
        chaos_messages = sum(d.messages_sent for d in chaos_devices)
        logger.info("")
        logger.info(f"Chaos devices sent {chaos_messages} messages (including spam)")
    
    logger.info("")
    logger.info("✅ Stress test completed!")
    

async def show_progress(devices, duration):
    """Show progress during the test"""
    start = time.time()
    try:
        while True:
            await asyncio.sleep(5)
            elapsed = time.time() - start
            remaining = max(0, duration - elapsed)
            active = sum(1 for d in devices if d.connected)
            points = sum(d.points_sent for d in devices)
            messages = sum(d.messages_sent for d in devices)
            logger.info(f"Progress: {elapsed:.0f}s / {duration}s | Active: {active} | Points: {points:,} | Messages: {messages:,}")
    except asyncio.CancelledError:
        pass


async def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Massive GPS stress test')
    parser.add_argument('--devices', type=int, default=1000, help='Number of devices')
    parser.add_argument('--duration', type=int, default=60, help='Test duration in seconds')
    parser.add_argument('--chaos', type=float, default=0.1, help='Percentage of chaos devices (0.0-1.0)')
    parser.add_argument('--host', default='89.47.162.7', help='Server host')
    parser.add_argument('--port', type=int, default=5002, help='Server port')
    
    args = parser.parse_args()
    
    logger.info("🚀 GPS TRACKER STRESS TEST")
    logger.info(f"Preparing to simulate {args.devices} devices for {args.duration} seconds")
    logger.info("")
    
    await run_stress_test(
        num_devices=args.devices,
        duration=args.duration,
        chaos_percentage=args.chaos,
        host=args.host,
        port=args.port
    )


if __name__ == "__main__":
    # Set up for high concurrency
    import sys
    if sys.platform == 'darwin':
        # macOS has lower default limits
        import resource
        resource.setrlimit(resource.RLIMIT_NOFILE, (8192, 8192))
    
    asyncio.run(main())