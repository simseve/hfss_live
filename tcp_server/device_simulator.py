#!/usr/bin/env python3
"""
Realistic GPS Device Simulator
Simulates a genuine TK905B device sending location updates every 10 seconds
"""
import asyncio
import logging
import random
import math
from datetime import datetime
import signal
import sys

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class GPSDeviceSimulator:
    """Simulates a real GPS tracker device with realistic movement"""
    
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
        self.target_speed = 0.0
        self.acceleration = 2.0  # km/h per second
        self.turn_rate = 0.0  # degrees per second
        
        # Device state
        self.message_count = 0
        self.last_message_time = None
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
            self.last_message_time = datetime.now()
            
            logger.debug(f"Device {self.device_id} TX: {message}")
            
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
    
    async def send_location(self):
        """Send GPS location update"""
        # Update position based on movement
        self.update_position()
        
        # Format time and date
        now = datetime.now()
        date_str = now.strftime("%d%m%y")
        time_str = now.strftime("%H%M%S")
        
        # GPS status (A=valid, V=invalid)
        gps_status = "A" if self.satellites >= 4 else "V"
        
        # Format coordinates
        lat_deg = int(abs(self.lat))
        lat_min = (abs(self.lat) - lat_deg) * 60
        lat_str = f"{lat_deg:02d}{lat_min:07.4f}"
        lat_dir = "N" if self.lat >= 0 else "S"
        
        lon_deg = int(abs(self.lon))
        lon_min = (abs(self.lon) - lon_deg) * 60
        lon_str = f"{lon_deg:03d}{lon_min:07.4f}"
        lon_dir = "E" if self.lon >= 0 else "W"
        
        # Build location message (watch protocol UD2 format)
        message = (
            f"[3G*{self.device_id}*0079*UD2,"
            f"{date_str},{time_str},{gps_status},"
            f"{lat_str},{lat_dir},{lon_str},{lon_dir},"
            f"{self.speed:.1f},{self.heading:.1f},{self.altitude:.1f},"
            f"{self.satellites},{self.gsm_signal},{self.battery},"
            f"0,0,00000008,2,0,268,3,3010,51042,146,3010,51043,132]"
        )
        
        response = await self.send_message(message)
        
        logger.info(
            f"Device {self.device_id}: Sent location "
            f"({self.lat:.6f}, {self.lon:.6f}) "
            f"alt={self.altitude:.1f}m speed={self.speed:.1f}km/h "
            f"heading={self.heading:.1f}° sats={self.satellites}"
        )
        
        return response
    
    def update_position(self):
        """Update device position with realistic movement"""
        # Randomly change target speed (simulate acceleration/deceleration)
        if random.random() < 0.1:  # 10% chance to change behavior
            if self.speed < 5:
                # Start moving or speed up
                self.target_speed = random.uniform(10, 50)
                self.turn_rate = random.uniform(-5, 5)
            elif self.speed > 40:
                # Slow down
                self.target_speed = random.uniform(20, 35)
            else:
                # Random speed change
                self.target_speed = self.speed + random.uniform(-10, 10)
                self.target_speed = max(0, min(60, self.target_speed))
        
        # Update speed towards target
        if abs(self.speed - self.target_speed) > 0.1:
            if self.speed < self.target_speed:
                self.speed = min(self.speed + self.acceleration, self.target_speed)
            else:
                self.speed = max(self.speed - self.acceleration * 2, self.target_speed)
        
        # Update heading
        if abs(self.turn_rate) > 0.1:
            self.heading += self.turn_rate
            self.heading = self.heading % 360
            # Gradually reduce turn rate
            self.turn_rate *= 0.95
        
        # Calculate position change (10 seconds of movement)
        if self.speed > 0:
            # Convert speed from km/h to m/s and calculate distance
            distance = (self.speed * 1000 / 3600) * 10  # meters in 10 seconds
            
            # Convert to lat/lon change
            lat_change = (distance * math.cos(math.radians(self.heading))) / 111111.0
            lon_change = (distance * math.sin(math.radians(self.heading))) / (111111.0 * math.cos(math.radians(self.lat)))
            
            self.lat += lat_change
            self.lon += lon_change
            
            # Add some noise for realism
            self.lat += random.uniform(-0.00001, 0.00001)
            self.lon += random.uniform(-0.00001, 0.00001)
        
        # Update altitude with small variations
        self.altitude += random.uniform(-2, 2)
        self.altitude = max(0, self.altitude)
        
        # Update satellites and signal
        self.satellites = max(4, min(12, self.satellites + random.randint(-1, 1)))
        self.gsm_signal = max(50, min(100, self.gsm_signal + random.randint(-5, 5)))
        
        # Battery drain (very slow)
        if random.random() < 0.01:  # 1% chance per update
            self.battery = max(10, self.battery - 1)
    
    async def run(self, duration: int = None):
        """Run the simulator for specified duration (seconds) or forever"""
        start_time = datetime.now()
        heartbeat_counter = 0
        
        try:
            await self.connect()
            
            while self.connected:
                # Check duration
                if duration and (datetime.now() - start_time).total_seconds() > duration:
                    logger.info(f"Device {self.device_id}: Simulation duration reached")
                    break
                
                # Send location update
                await self.send_location()
                
                # Send heartbeat every 6 location updates (every minute)
                heartbeat_counter += 1
                if heartbeat_counter >= 6:
                    await self.send_login()
                    heartbeat_counter = 0
                
                # Wait 10 seconds before next update
                await asyncio.sleep(10)
                
        except KeyboardInterrupt:
            logger.info(f"Device {self.device_id}: Interrupted by user")
        except Exception as e:
            logger.error(f"Device {self.device_id}: Simulation error - {e}")
        finally:
            await self.disconnect()
            
            # Print statistics
            if self.session_start:
                session_duration = (datetime.now() - self.session_start).total_seconds()
                logger.info(f"Device {self.device_id}: Session statistics:")
                logger.info(f"  - Duration: {session_duration:.1f} seconds")
                logger.info(f"  - Messages sent: {self.message_count}")
                logger.info(f"  - Final position: ({self.lat:.6f}, {self.lon:.6f})")
                logger.info(f"  - Distance traveled: ~{self.calculate_distance():.2f} km")
    
    def calculate_distance(self):
        """Estimate distance traveled (rough calculation)"""
        # This is a simplified calculation
        start_lat, start_lon = 47.3769, 8.5417
        lat_dist = abs(self.lat - start_lat) * 111.0  # km per degree
        lon_dist = abs(self.lon - start_lon) * 111.0 * math.cos(math.radians(self.lat))
        return math.sqrt(lat_dist**2 + lon_dist**2)


async def run_multiple_devices(num_devices: int = 3, host: str = "89.47.162.7", port: int = 5002):
    """Run multiple device simulators concurrently"""
    devices = []
    
    # Create devices with unique IDs
    for i in range(num_devices):
        device_id = f"88251{i:05d}"  # e.g., 8825100000, 8825100001, etc.
        device = GPSDeviceSimulator(device_id, host, port)
        devices.append(device)
    
    # Run all devices concurrently
    tasks = [device.run() for device in devices]
    await asyncio.gather(*tasks)


def signal_handler(sig, frame):
    """Handle Ctrl+C gracefully"""
    logger.info("Shutting down simulators...")
    sys.exit(0)


async def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description='GPS Device Simulator')
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
    
    logger.info(f"Starting GPS device simulator(s)")
    logger.info(f"Server: {args.host}:{args.port}")
    logger.info(f"Devices: {args.devices}")
    
    if args.devices > 1:
        await run_multiple_devices(args.devices, args.host, args.port)
    else:
        simulator = GPSDeviceSimulator(args.device_id, args.host, args.port)
        await simulator.run(args.duration)


if __name__ == "__main__":
    asyncio.run(main())