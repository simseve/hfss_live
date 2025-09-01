#!/usr/bin/env python3
"""Trigger a flight change by simulating a 3+ hour gap"""

import socket
import struct
from datetime import datetime, timedelta
import time

def send_jt808_location(device_id="9590046863", hours_offset=4):
    """Send a JT808 location message with timestamp offset to trigger new flight"""
    
    print(f"🚀 Triggering flight change for device {device_id}")
    print(f"   Simulating {hours_offset} hour gap")
    print("=" * 60)
    
    # Connect to TCP server
    HOST = 'localhost'
    PORT = 5002
    
    try:
        # Create TCP socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((HOST, PORT))
        print(f"✅ Connected to {HOST}:{PORT}")
        
        # Build JT808 location message (0x0200)
        # Message structure:
        # - Start marker: 0x7E
        # - Message ID: 0x0200 (location report)
        # - Properties: 0x0000
        # - Device ID: 6 bytes BCD
        # - Sequence: 2 bytes
        # - Message body: location data
        # - Checksum: 1 byte
        # - End marker: 0x7E
        
        message = bytearray()
        message.append(0x7E)  # Start marker
        
        # Message ID (0x0200 = location report)
        message.extend(struct.pack('>H', 0x0200))
        
        # Properties (body length, etc)
        message.extend(struct.pack('>H', 0x001C))  # 28 bytes body
        
        # Device ID (6 bytes BCD) - convert "9590046863" to BCD
        device_bcd = bytes([0x95, 0x90, 0x04, 0x68, 0x63, 0x00])
        message.extend(device_bcd)
        
        # Sequence number
        message.extend(struct.pack('>H', 1))
        
        # Location data body
        # Status (4 bytes)
        message.extend(struct.pack('>I', 0x00000000))
        
        # Latitude (4 bytes) - Example: 45.973288 * 1000000
        lat = int(45.973288 * 1000000)
        message.extend(struct.pack('>I', lat))
        
        # Longitude (4 bytes) - Example: 8.875027 * 1000000
        lon = int(8.875027 * 1000000)
        message.extend(struct.pack('>I', lon))
        
        # Altitude (2 bytes)
        message.extend(struct.pack('>H', 350))
        
        # Speed (2 bytes)
        message.extend(struct.pack('>H', 0))
        
        # Direction (2 bytes)
        message.extend(struct.pack('>H', 0))
        
        # Timestamp (6 bytes BCD) - FUTURE TIME to simulate gap
        future_time = datetime.utcnow() + timedelta(hours=hours_offset)
        year = future_time.year % 100
        month = future_time.month
        day = future_time.day
        hour = future_time.hour
        minute = future_time.minute
        second = future_time.second
        
        # Convert to BCD
        def to_bcd(val):
            return ((val // 10) << 4) | (val % 10)
        
        message.append(to_bcd(year))
        message.append(to_bcd(month))
        message.append(to_bcd(day))
        message.append(to_bcd(hour))
        message.append(to_bcd(minute))
        message.append(to_bcd(second))
        
        # Calculate checksum (XOR of all bytes except markers)
        checksum = 0
        for b in message[1:]:
            checksum ^= b
        message.append(checksum)
        
        # End marker
        message.append(0x7E)
        
        # Send the message
        sock.sendall(bytes(message))
        print(f"📤 Sent location message with timestamp: {future_time.strftime('%Y-%m-%d %H:%M:%S')} UTC")
        print(f"   This is {hours_offset} hours in the future")
        
        # Wait for response
        sock.settimeout(2)
        try:
            response = sock.recv(1024)
            if response:
                print(f"📥 Received response: {response.hex()}")
                if b'\x80\x01' in response:
                    print("✅ Server acknowledged (0x8001)")
        except socket.timeout:
            print("⏱️ No response received (timeout)")
        
        sock.close()
        print("\n✅ Message sent! Check the monitor to see if a new flight was created.")
        
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    import sys
    
    # Default to 4 hour gap to trigger new flight
    hours = 4
    if len(sys.argv) > 1:
        try:
            hours = float(sys.argv[1])
        except:
            pass
    
    print("JT808 Flight Change Trigger")
    print("=" * 60)
    print(f"Simulating a {hours} hour gap to trigger flight separation")
    print()
    
    # First show current status
    from database.db_conf import get_db
    from database.models import Flight
    
    db = next(get_db())
    try:
        current = db.query(Flight).filter(
            Flight.device_id == "9590046863",
            Flight.source == "tk905b_live"
        ).order_by(Flight.created_at.desc()).first()
        
        if current:
            print(f"Current flight: {current.flight_id}")
            if current.last_fix:
                print(f"Last fix: {current.last_fix.get('datetime', 'N/A')}")
    finally:
        db.close()
    
    print()
    input("Press Enter to send the location message...")
    
    send_jt808_location(hours_offset=hours)