#!/usr/bin/env python3
"""
Simple JT808 test - send and exit
"""
import socket
import binascii
import struct

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

def test_simple():
    device_id = "009590046863"  # Registered device
    
    print(f"Testing JT808 device: {device_id}")
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(2)  # 2 second timeout
    sock.connect(('localhost', 5002))
    print("✅ Connected")
    
    # Send registration
    reg_body = b'\x00\x2c\x01/70111EG-05\x00\x00\x000000000\x01\xd4\xc1B88888'
    reg_msg = create_jt808_message(0x0100, device_id, 1, reg_body)
    sock.send(reg_msg)
    print(f"Sent registration: {binascii.hexlify(reg_msg).decode()[:60]}...")
    
    # Send location with GPS data
    alarm = 0x00000000
    status = 0x00000003  # ACC on, GPS positioned
    latitude = int(46.5197 * 1000000)
    longitude = int(6.6323 * 1000000)
    altitude = 375
    speed = 120  # 12 km/h
    direction = 45
    time_bcd = bytes.fromhex('250901133500')  # 2025-09-01 13:35:00
    
    location_body = struct.pack('>I', alarm)
    location_body += struct.pack('>I', status)
    location_body += struct.pack('>I', latitude)
    location_body += struct.pack('>I', longitude)
    location_body += struct.pack('>H', altitude)
    location_body += struct.pack('>H', speed)
    location_body += struct.pack('>H', direction)
    location_body += time_bcd
    
    location_msg = create_jt808_message(0x0200, device_id, 2, location_body)
    sock.send(location_msg)
    print(f"Sent location: lat={latitude/1000000:.6f}, lon={longitude/1000000:.6f}, speed={speed/10}km/h")
    
    sock.close()
    print("✅ Test data sent - check server logs for processing")

if __name__ == '__main__':
    test_simple()