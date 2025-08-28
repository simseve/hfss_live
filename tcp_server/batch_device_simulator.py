#!/usr/bin/env python3
"""
Realistic GPS Device Simulator with 1Hz collection and batched sending
Simulates a TK905B device that:
- Collects GPS points at 1Hz (every second)
- Sends batched updates every 10 seconds
"""
import asyncio
import logging
import random
import math
from datetime import datetime, timedelta
import signal
import sys
from typing import List, Dict, Any

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class BatchedGPSDevice:
    """Simulates a real GPS tracker with 1Hz collection and batch sending"""
    
    def __init__(self, device_id: str = "8825100456", host: str = "89.47.162.7", port: int = 5002):
        self.device_id = device_id
        self.host = host
        self.port = port
        self.reader = None
        self.writer = None
        self.connected = False
        
        # Starting position (Zurich area)
        self.lat = 47.3769 + random.uniform(-0.01, 0.01)  
        self.lon = 8.5417 + random.uniform(-0.01, 0.01)
        self.altitude = 408.0  # meters
        self.speed = 0.0  # km/h
        self.heading = random.uniform(0, 360)  # degrees
        self.battery = 95  # percentage
        self.satellites = 8
        self.gsm_signal = 85
        
        # Movement parameters
        self.target_speed = 30.0  # Target cruising speed
        self.acceleration = 0.5  # m/s^2
        self.turn_rate = 0.0  # degrees per second
        
        # Batch collection
        self.point_buffer: List[Dict[str, Any]] = []
        self.collection_interval = 1.0  # 1Hz collection
        self.batch_send_interval = 10.0  # Send every 10 seconds
        
        # Statistics
        self.message_count = 0
        self.points_sent = 0
        self.session_start = None
        
    async def connect(self):
        """Connect to the GPS TCP server"""
        try:
            logger.info(f"Device {self.device_id}: Connecting to {self.host}:{self.port}...")
            self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
            self.connected = True
            self.session_start = datetime.now()
            logger.info(f"Device {self.device_id}: Connected successfully")
            
            # Send initial login message
            await self.send_login()
            
        except Exception as e:
            logger.error(f"Device {self.device_id}: Connection failed - {e}")
            self.connected = False
            raise
    
    async def disconnect(self):
        """Disconnect from the server"""
        if self.writer:
            logger.info(f"Device {self.device_id}: Disconnecting...")
            self.writer.close()
            await self.writer.wait_closed()
            self.connected = False
            logger.info(f"Device {self.device_id}: Disconnected")
    
    async def send_message(self, message: str):
        """Send a message and wait for response"""
        if not self.connected:
            return None
            
        try:
            self.writer.write(message.encode('utf-8'))
            await self.writer.drain()
            self.message_count += 1
            
            logger.debug(f"Device {self.device_id} TX: {message[:100]}...")
            
            # Try to read response (with timeout)
            try:
                data = await asyncio.wait_for(self.reader.read(1024), timeout=1.0)
                response = data.decode('utf-8')
                logger.debug(f"Device {self.device_id} RX: {response}")
                return response
            except asyncio.TimeoutError:
                return None
                
        except Exception as e:
            logger.error(f"Device {self.device_id}: Send error - {e}")
            self.connected = False
            return None
    
    async def send_login(self):
        """Send login/heartbeat message"""
        message = f"[3G*{self.device_id}*0008*LK,0,0,{self.battery}]"
        response = await self.send_message(message)
        if response and "OK" in response:
            logger.info(f"Device {self.device_id}: Login successful")
        return response
    
    def collect_gps_point(self, timestamp: datetime) -> Dict[str, Any]:
        """Collect a single GPS point (called at 1Hz)"""
        # Update position for 1 second of movement
        self.update_position(1.0)
        
        # Create point data
        point = {
            'timestamp': timestamp,
            'lat': self.lat,
            'lon': self.lon,
            'altitude': self.altitude,
            'speed': self.speed,
            'heading': self.heading,
            'satellites': self.satellites,
            'valid': self.satellites >= 4
        }
        
        return point
    
    async def send_batch(self):
        """Send batched location updates using TK905B batch format"""
        if not self.point_buffer:
            return
            
        # TK905B can send multiple location records in one message
        # Format: [3G*ID*LENGTH*UD3,COUNT,RECORD1,RECORD2,...]
        # Each record: DATE,TIME,STATUS,LAT,LAT_DIR,LON,LON_DIR,SPEED,HEADING,ALT
        
        batch_size = len(self.point_buffer)
        records = []
        
        for point in self.point_buffer:
            # Format time and date
            dt = point['timestamp']
            date_str = dt.strftime("%d%m%y")
            time_str = dt.strftime("%H%M%S")
            
            # GPS status
            gps_status = "A" if point['valid'] else "V"
            
            # Format coordinates in DDMM.MMMM format
            lat = point['lat']
            lat_deg = int(abs(lat))
            lat_min = (abs(lat) - lat_deg) * 60
            lat_str = f"{lat_deg:02d}{lat_min:07.4f}"
            lat_dir = "N" if lat >= 0 else "S"
            
            lon = point['lon']
            lon_deg = int(abs(lon))
            lon_min = (abs(lon) - lon_deg) * 60
            lon_str = f"{lon_deg:03d}{lon_min:07.4f}"
            lon_dir = "E" if lon >= 0 else "W"
            
            # Build record
            record = (
                f"{date_str},{time_str},{gps_status},"
                f"{lat_str},{lat_dir},{lon_str},{lon_dir},"
                f"{point['speed']:.1f},{point['heading']:.1f},{point['altitude']:.1f}"
            )
            records.append(record)
        
        # Join all records with semicolon separator (batch format)
        batch_data = f"UD3,{batch_size}," + ";".join(records)
        
        # Calculate message length
        msg_length = len(batch_data)
        
        # Build complete message
        message = f"[3G*{self.device_id}*{msg_length:04X}*{batch_data}]"
        
        # For now, send individual messages since server might not support UD3 batch format
        # Fall back to sending individual UD2 messages
        for i, point in enumerate(self.point_buffer):
            dt = point['timestamp']
            date_str = dt.strftime("%d%m%y")
            time_str = dt.strftime("%H%M%S")
            
            gps_status = "A" if point['valid'] else "V"
            
            # Format coordinates
            lat = point['lat']
            lat_deg = int(abs(lat))
            lat_min = (abs(lat) - lat_deg) * 60
            lat_str = f"{lat_deg:02d}{lat_min:07.4f}"
            lat_dir = "N" if lat >= 0 else "S"
            
            lon = point['lon']
            lon_deg = int(abs(lon))
            lon_min = (abs(lon) - lon_deg) * 60
            lon_str = f"{lon_deg:03d}{lon_min:07.4f}"
            lon_dir = "E" if lon >= 0 else "W"
            
            # Send individual UD2 message
            message = (
                f"[3G*{self.device_id}*0079*UD2,"
                f"{date_str},{time_str},{gps_status},"
                f"{lat_str},{lat_dir},{lon_str},{lon_dir},"
                f"{point['speed']:.1f},{point['heading']:.1f},{point['altitude']:.1f},"
                f"{point['satellites']},{self.gsm_signal},{self.battery},"
                f"0,0,00000008,2,0,268,3,3010,51042,146,3010,51043,132]"
            )
            
            response = await self.send_message(message)
            
            # Add small delay between messages to respect rate limiting
            if i < len(self.point_buffer) - 1:
                await asyncio.sleep(0.5)  # 500ms between messages in batch
        
        self.points_sent += len(self.point_buffer)
        
        logger.info(
            f"Device {self.device_id}: Sent batch of {batch_size} points "
            f"(latest: {self.lat:.6f}, {self.lon:.6f} @ {self.speed:.1f}km/h)"
        )
        
        # Clear buffer after sending
        self.point_buffer.clear()
    
    def update_position(self, delta_time: float):
        """Update device position with realistic movement for delta_time seconds"""
        
        # Simulate realistic speed changes
        if random.random() < 0.05:  # 5% chance to change behavior
            if self.speed < 5:
                # Start moving or speed up
                self.target_speed = random.uniform(20, 60)
                self.turn_rate = random.uniform(-10, 10)
            elif self.speed > 50:
                # Slow down
                self.target_speed = random.uniform(25, 40)
                self.turn_rate *= 0.5
            else:
                # Minor speed adjustment
                self.target_speed += random.uniform(-5, 5)
                self.target_speed = max(0, min(80, self.target_speed))
                
                # Occasional turns
                if random.random() < 0.2:
                    self.turn_rate = random.uniform(-15, 15)
        
        # Update speed with realistic acceleration/deceleration
        if abs(self.speed - self.target_speed) > 0.1:
            # Convert acceleration to km/h per second
            accel_kmh = self.acceleration * 3.6 * delta_time
            
            if self.speed < self.target_speed:
                self.speed = min(self.speed + accel_kmh, self.target_speed)
            else:
                self.speed = max(self.speed - accel_kmh * 2, self.target_speed)
        
        # Update heading with turn rate
        if abs(self.turn_rate) > 0.1:
            self.heading += self.turn_rate * delta_time
            self.heading = self.heading % 360
            # Gradually reduce turn rate (simulate straightening out)
            self.turn_rate *= (1 - 0.1 * delta_time)
        
        # Calculate position change
        if self.speed > 0:
            # Convert speed from km/h to m/s
            speed_ms = self.speed * 1000 / 3600
            distance = speed_ms * delta_time  # meters
            
            # Convert to lat/lon change
            lat_change = (distance * math.cos(math.radians(self.heading))) / 111111.0
            lon_change = (distance * math.sin(math.radians(self.heading))) / (111111.0 * math.cos(math.radians(self.lat)))
            
            self.lat += lat_change
            self.lon += lon_change
            
            # Add GPS noise for realism (1-3 meter accuracy)
            gps_noise = random.uniform(1, 3) / 111111.0  # meters to degrees
            self.lat += random.uniform(-gps_noise, gps_noise)
            self.lon += random.uniform(-gps_noise, gps_noise)
        
        # Update altitude with terrain variations
        self.altitude += random.uniform(-0.5, 0.5) * delta_time
        self.altitude = max(0, self.altitude)
        
        # Update satellite count (affects GPS quality)
        if random.random() < 0.1:  # 10% chance to change
            self.satellites = max(4, min(12, self.satellites + random.randint(-2, 2)))
        
        # Update GSM signal strength
        self.gsm_signal = max(50, min(100, self.gsm_signal + random.randint(-3, 3)))
        
        # Slow battery drain
        if random.random() < 0.001 * delta_time:  # Very slow drain
            self.battery = max(10, self.battery - 1)
    
    async def collection_loop(self):
        """Collect GPS points at 1Hz"""
        while self.connected:
            try:
                # Collect point with current timestamp
                point = self.collect_gps_point(datetime.now())
                self.point_buffer.append(point)
                
                # Sleep for collection interval
                await asyncio.sleep(self.collection_interval)
                
            except Exception as e:
                logger.error(f"Device {self.device_id}: Collection error - {e}")
                break
    
    async def sending_loop(self):
        """Send batched points every 10 seconds"""
        while self.connected:
            try:
                # Wait for batch interval
                await asyncio.sleep(self.batch_send_interval)
                
                # Send the batch
                await self.send_batch()
                
                # Send heartbeat every 3rd batch (every 30 seconds)
                if self.message_count % 3 == 0:
                    await asyncio.sleep(0.5)  # Small delay before heartbeat
                    await self.send_login()
                
            except Exception as e:
                logger.error(f"Device {self.device_id}: Sending error - {e}")
                self.connected = False
                break
    
    async def run(self, duration: int = None):
        """Run the simulator for specified duration (seconds) or forever"""
        start_time = datetime.now()
        
        try:
            await self.connect()
            
            # Start collection and sending loops
            collection_task = asyncio.create_task(self.collection_loop())
            sending_task = asyncio.create_task(self.sending_loop())
            
            # Wait for duration or until disconnected
            if duration:
                await asyncio.sleep(duration)
                logger.info(f"Device {self.device_id}: Simulation duration reached")
                self.connected = False
            else:
                # Wait for tasks to complete (on disconnect)
                await asyncio.gather(collection_task, sending_task)
                
        except KeyboardInterrupt:
            logger.info(f"Device {self.device_id}: Interrupted by user")
        except Exception as e:
            logger.error(f"Device {self.device_id}: Simulation error - {e}")
        finally:
            self.connected = False
            await self.disconnect()
            
            # Print statistics
            if self.session_start:
                session_duration = (datetime.now() - self.session_start).total_seconds()
                logger.info(f"Device {self.device_id}: Session statistics:")
                logger.info(f"  - Duration: {session_duration:.1f} seconds")
                logger.info(f"  - Messages sent: {self.message_count}")
                logger.info(f"  - GPS points sent: {self.points_sent}")
                logger.info(f"  - Average points/message: {self.points_sent/max(1, self.message_count):.1f}")
                logger.info(f"  - Final position: ({self.lat:.6f}, {self.lon:.6f})")
                logger.info(f"  - Distance traveled: ~{self.calculate_distance():.2f} km")
    
    def calculate_distance(self):
        """Estimate distance traveled (rough calculation)"""
        start_lat, start_lon = 47.3769, 8.5417
        lat_dist = abs(self.lat - start_lat) * 111.0  # km per degree
        lon_dist = abs(self.lon - start_lon) * 111.0 * math.cos(math.radians(self.lat))
        return math.sqrt(lat_dist**2 + lon_dist**2)


async def run_multiple_devices(num_devices: int = 3, host: str = "89.47.162.7", port: int = 5002, duration: int = None):
    """Run multiple device simulators concurrently"""
    devices = []
    
    # Create devices with unique IDs
    for i in range(num_devices):
        device_id = f"88251{i:05d}"  # e.g., 8825100000, 8825100001, etc.
        device = BatchedGPSDevice(device_id, host, port)
        
        # Start devices with slight offset to avoid connection burst
        await asyncio.sleep(random.uniform(0.1, 0.5))
        
        devices.append(device)
    
    # Run all devices concurrently
    tasks = [device.run(duration) for device in devices]
    await asyncio.gather(*tasks)


def signal_handler(sig, frame):
    """Handle Ctrl+C gracefully"""
    logger.info("Shutting down simulators...")
    sys.exit(0)


async def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Batched GPS Device Simulator (1Hz collection)')
    parser.add_argument('--host', default='89.47.162.7', help='Server host')
    parser.add_argument('--port', type=int, default=5002, help='Server port')
    parser.add_argument('--device-id', default='8825100456', help='Device ID')
    parser.add_argument('--devices', type=int, default=1, help='Number of devices to simulate')
    parser.add_argument('--duration', type=int, help='Simulation duration in seconds')
    parser.add_argument('--local', action='store_true', help='Use localhost instead of production')
    
    args = parser.parse_args()
    
    if args.local:
        args.host = 'localhost'
        args.port = 5002
    
    # Set up signal handler for clean shutdown
    signal.signal(signal.SIGINT, signal_handler)
    
    logger.info(f"Starting batched GPS device simulator(s)")
    logger.info(f"Server: {args.host}:{args.port}")
    logger.info(f"Devices: {args.devices}")
    logger.info(f"Collection: 1Hz (1 point/second)")
    logger.info(f"Batch sending: Every 10 seconds")
    
    if args.devices > 1:
        await run_multiple_devices(args.devices, args.host, args.port, args.duration)
    else:
        simulator = BatchedGPSDevice(args.device_id, args.host, args.port)
        await simulator.run(args.duration)


if __name__ == "__main__":
    asyncio.run(main())