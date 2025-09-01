#!/usr/bin/env python3
"""
Analyze the binary GPS data from your tracker
Raw data: 7e010000210095900468630005002c012f373031313145472d30350000003030303030303001d4c14238383838386f7e
"""

def analyze_message():
    hex_data = "7e010000210095900468630005002c012f373031313145472d30350000003030303030303001d4c14238383838386f7e"
    raw = bytes.fromhex(hex_data)
    
    print("Binary GPS Protocol Analysis")
    print("=" * 60)
    print(f"Total length: {len(raw)} bytes")
    print(f"Hex: {hex_data}")
    print()
    
    # Frame structure
    print("Frame Structure:")
    print(f"  Start delimiter: 0x{raw[0]:02x} ('{chr(raw[0]) if 32 <= raw[0] < 127 else '?'}')")
    print(f"  End delimiter: 0x{raw[-1]:02x} ('{chr(raw[-1]) if 32 <= raw[-1] < 127 else '?'}')")
    print()
    
    # Remove delimiters
    payload = raw[1:-1]
    print(f"Payload ({len(payload)} bytes):")
    
    # Parse header based on JT808-like structure
    pos = 0
    
    # Message ID (2 bytes)
    msg_id = int.from_bytes(payload[pos:pos+2], 'big')
    print(f"  Message ID: 0x{msg_id:04x} ({msg_id})")
    pos += 2
    
    # Message properties (2 bytes)
    msg_props = int.from_bytes(payload[pos:pos+2], 'big')
    print(f"  Message Properties: 0x{msg_props:04x}")
    print(f"    Body length: {msg_props & 0x3FF}")
    print(f"    Encryption: {(msg_props >> 10) & 0x7}")
    print(f"    Fragmented: {(msg_props >> 13) & 0x1}")
    pos += 2
    
    # Try to find the device ID (appears to be "70111EG-05")
    # Looking at position after some binary data
    print()
    print("Searching for ASCII sequences:")
    
    ascii_start = -1
    for i in range(len(payload)):
        if 32 <= payload[i] <= 126:
            if ascii_start == -1:
                ascii_start = i
        else:
            if ascii_start != -1 and i - ascii_start >= 3:
                ascii_str = payload[ascii_start:i].decode('ascii', errors='ignore')
                print(f"  Position {ascii_start:02d}-{i-1:02d}: '{ascii_str}'")
            ascii_start = -1
    
    # Check final sequence
    if ascii_start != -1:
        ascii_str = payload[ascii_start:].decode('ascii', errors='ignore')
        print(f"  Position {ascii_start:02d}-end: '{ascii_str}'")
    
    print()
    print("Key findings:")
    print("  1. Device ID: 70111EG-05")
    print("  2. Message type: 0x0100 (likely registration/login)")
    print("  3. Contains status code: B88888")
    print("  4. Additional data: 0000000")
    print()
    
    # Hex dump of payload sections
    print("Payload sections:")
    sections = [
        (0, 4, "Header"),
        (4, 16, "Binary data"),
        (16, 27, "Device ID area"),
        (27, 35, "Zeros"),
        (35, 46, "Status/checksum area")
    ]
    
    for start, end, desc in sections:
        if start < len(payload):
            section = payload[start:min(end, len(payload))]
            hex_str = ' '.join(f'{b:02x}' for b in section)
            ascii_str = ''.join(chr(b) if 32 <= b < 127 else '.' for b in section)
            print(f"  {desc:20s}: {hex_str:35s} | {ascii_str}")

if __name__ == '__main__':
    analyze_message()