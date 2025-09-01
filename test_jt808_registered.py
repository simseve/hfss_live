#!/usr/bin/env python3
"""
Test JT808 with registered device
"""
import socket
import time
import binascii
import struct

def create_jt808_message(msg_id, terminal_phone, serial_no, body=b''):
    """Create a JT808 message with proper formatting"""
    # Message properties (body length, no encryption, no fragmentation)
    msg_props = len(body) & 0x03FF
    
    # Build header
    header = struct.pack('>H', msg_id)  # Message ID
    header += struct.pack('>H', msg_props)  # Message properties
    
    # Terminal phone (6 bytes BCD for 2013 version)
    phone_bytes = bytes.fromhex(terminal_phone.zfill(12))
    header += phone_bytes
    
    # Message serial number
    header += struct.pack('>H', serial_no)
    
    # Combine header and body
    payload = header + body
    
    # Calculate checksum (XOR)
    checksum = 0
    for byte in payload:
        checksum ^= byte
    payload += struct.pack('B', checksum)
    
    # Add frame delimiters
    return bytes([0x7E]) + payload + bytes([0x7E])

def test_registered_device():
    """Test with registered device 9590046863"""
    
    device_id = "009590046863"  # Terminal phone number with padding
    host = 'localhost'
    port = 5002
    
    print(f"Testing registered JT808 device: {device_id}")
    print(f"Connecting to {host}:{port}...")
    
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((host, port))
        print("✅ Connected to server")
        
        # Step 1: Send registration (0x0100)
        print("\n1. Sending registration...")
        reg_body = b'\x00\x2c\x01/70111EG-05\x00\x00\x000000000\x01\xd4\xc1B88888'
        reg_msg = create_jt808_message(0x0100, device_id, 1, reg_body)
        sock.send(reg_msg)
        print(f"   Sent: {binascii.hexlify(reg_msg).decode()}")
        
        # Wait for response
        time.sleep(0.5)
        try:
            response = sock.recv(1024)
            print(f"   Response: {binascii.hexlify(response).decode()}")
            
            # Extract auth code if registration successful
            if response[1:3] == b'\x81\x00':  # Registration response
                print("   ✅ Registration ACK received")
                # Extract auth code (simplified - would need proper parsing)
                auth_code = b'AUTH0001'
        except socket.timeout:
            print("   ⚠️ No response")
            auth_code = b'AUTH0001'
        
        # Step 2: Send authentication (0x0102)
        print("\n2. Sending authentication...")
        auth_msg = create_jt808_message(0x0102, device_id, 2, auth_code)
        sock.send(auth_msg)
        print(f"   Sent: {binascii.hexlify(auth_msg).decode()}")
        
        time.sleep(0.5)
        try:
            response = sock.recv(1024)
            print(f"   Response: {binascii.hexlify(response).decode()}")
            if response[1:3] == b'\x80\x01':  # General ACK
                print("   ✅ Authentication ACK received")
        except socket.timeout:
            print("   ⚠️ No response")
        
        # Step 3: Send location report (0x0200)
        print("\n3. Sending location report with GPS data...")
        
        # Build location body
        alarm = 0x00000000  # No alarm
        status = 0x00000003  # ACC on, GPS positioned
        
        # Real coordinates (example: somewhere in Europe)
        latitude = int(46.5197 * 1000000)  # 46.5197°N
        longitude = int(6.6323 * 1000000)   # 6.6323°E
        altitude = 375  # meters
        speed = 0  # km/h * 10
        direction = 0  # degrees
        
        # Time (BCD format: YY MM DD HH MM SS)
        time_bcd = bytes.fromhex('250901132300')  # 2025-09-01 13:23:00
        
        location_body = struct.pack('>I', alarm)
        location_body += struct.pack('>I', status)
        location_body += struct.pack('>I', latitude)
        location_body += struct.pack('>I', longitude)
        location_body += struct.pack('>H', altitude)
        location_body += struct.pack('>H', speed)
        location_body += struct.pack('>H', direction)
        location_body += time_bcd
        
        location_msg = create_jt808_message(0x0200, device_id, 3, location_body)
        sock.send(location_msg)
        print(f"   Sent location: lat={latitude/1000000:.6f}, lon={longitude/1000000:.6f}")
        print(f"   Hex: {binascii.hexlify(location_msg).decode()}")
        
        time.sleep(0.5)
        try:
            response = sock.recv(1024)
            print(f"   Response: {binascii.hexlify(response).decode()}")
            if response[1:3] == b'\x80\x01':  # General ACK
                print("   ✅ Location ACK received - GPS data should be queued!")
        except socket.timeout:
            print("   ⚠️ No response")
        
        # Send a few more location updates
        print("\n4. Sending multiple location updates...")
        for i in range(3):
            time.sleep(1)
            
            # Slightly modify coordinates to simulate movement
            latitude += 10  # Move slightly north
            longitude += 10  # Move slightly east
            
            location_body = struct.pack('>I', alarm)
            location_body += struct.pack('>I', status)
            location_body += struct.pack('>I', latitude)
            location_body += struct.pack('>I', longitude)
            location_body += struct.pack('>H', altitude)
            location_body += struct.pack('>H', speed)
            location_body += struct.pack('>H', direction)
            location_body += time_bcd
            
            location_msg = create_jt808_message(0x0200, device_id, 4+i, location_body)
            sock.send(location_msg)
            print(f"   Update {i+1}: lat={latitude/1000000:.6f}, lon={longitude/1000000:.6f}")
        
        print("\n✅ Test completed successfully!")
        print("Check the server logs to see if GPS data was queued to Redis")
        
        # Close connection properly
        sock.close()
        print("\nConnection closed")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        if 'sock' in locals():
            sock.close()
            print("\nConnection closed")

if __name__ == '__main__':
    test_registered_device()