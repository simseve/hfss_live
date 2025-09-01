#!/usr/bin/env python3
"""
Test JT808 with multiple location updates
"""
import socket
import binascii
import struct
import time

def create_jt808_message(msg_id, terminal_phone, serial_no, body=b''):
    """Create a JT808 message with proper formatting"""
    msg_props = len(body) & 0x03FF
    header = struct.pack('>H', msg_id)
    header += struct.pack('>H', msg_props)
    phone_bytes = bytes.fromhex(terminal_phone.zfill(12))
    header += phone_bytes
    header += struct.pack('>H', serial_no)
    payload = header + body
    checksum = 0
    for byte in payload:
        checksum ^= byte
    payload += struct.pack('B', checksum)
    return bytes([0x7E]) + payload + bytes([0x7E])

def test_multiple_locations():
    device_id = "009590046863"  # Registered device
    
    print(f"Testing JT808 device: {device_id} with multiple locations")
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(2)
    sock.connect(('localhost', 5002))
    print("✅ Connected")
    
    # 1. Send registration
    reg_body = b'\x00\x2c\x01/70111EG-05\x00\x00\x000000000\x01\xd4\xc1B88888'
    reg_msg = create_jt808_message(0x0100, device_id, 1, reg_body)
    sock.send(reg_msg)
    print(f"Sent registration")
    time.sleep(0.5)
    
    # 2. Send authentication
    auth_msg = create_jt808_message(0x0102, device_id, 2, b'AUTH0001')
    sock.send(auth_msg)
    print(f"Sent authentication")
    time.sleep(0.5)
    
    # 3. Send multiple location updates
    base_lat = 46.5197
    base_lon = 6.6323
    
    for i in range(5):
        # Simulate movement
        lat = base_lat + (i * 0.001)  # Move north
        lon = base_lon + (i * 0.0005)  # Move east
        speed = 150 + (i * 50)  # Increasing speed (15-35 km/h)
        
        alarm = 0x00000000
        status = 0x00000003  # ACC on, GPS positioned
        latitude = int(lat * 1000000)
        longitude = int(lon * 1000000)
        altitude = 375 + (i * 10)
        direction = 45
        
        # Current time in BCD
        from datetime import datetime
        now = datetime.now()
        time_bcd = bytes.fromhex(f'{now.year%100:02x}{now.month:02x}{now.day:02x}{now.hour:02x}{now.minute:02x}{now.second:02x}')
        
        location_body = struct.pack('>I', alarm)
        location_body += struct.pack('>I', status)
        location_body += struct.pack('>I', latitude)
        location_body += struct.pack('>I', longitude)
        location_body += struct.pack('>H', altitude)
        location_body += struct.pack('>H', speed)
        location_body += struct.pack('>H', direction)
        location_body += time_bcd
        
        location_msg = create_jt808_message(0x0200, device_id, 3+i, location_body)
        sock.send(location_msg)
        print(f"  Location {i+1}: lat={lat:.6f}, lon={lon:.6f}, speed={speed/10:.1f}km/h, alt={altitude}m")
        
        time.sleep(1)  # Wait between updates
    
    sock.close()
    print("\n✅ Sent 5 location updates - check database for points")

if __name__ == '__main__':
    test_multiple_locations()