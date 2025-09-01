#!/usr/bin/env python3
"""
Analyze the new GPS message
"""

def analyze_message(hex_data):
    raw = bytes.fromhex(hex_data)
    
    print("JT808 Message Analysis")
    print("=" * 60)
    print(f"Hex: {hex_data}")
    print(f"Total length: {len(raw)} bytes")
    print()
    
    # Frame check
    print(f"Start delimiter: 0x{raw[0]:02x}")
    print(f"End delimiter: 0x{raw[-1]:02x}")
    
    # Remove delimiters
    payload = raw[1:-1]
    print(f"\nPayload ({len(payload)} bytes):")
    
    # Parse header
    msg_id = int.from_bytes(payload[0:2], 'big')
    msg_props = int.from_bytes(payload[2:4], 'big')
    
    print(f"  Message ID: 0x{msg_id:04x}")
    
    # Message properties
    body_length = msg_props & 0x3FF
    encryption = (msg_props >> 10) & 0x7
    is_subpackage = (msg_props >> 13) & 0x1
    version = (msg_props >> 14) & 0x1
    
    print(f"  Message Properties: 0x{msg_props:04x}")
    print(f"    Body length: {body_length}")
    print(f"    Version: {'2019' if version else '2011/2013'}")
    
    # Compare with previous message
    print("\n🔍 Comparing messages:")
    old_hex = "7e010000210095900468630005002c012f373031313145472d30350000003030303030303001d4c14238383838386f7e"
    new_hex = hex_data
    
    old_raw = bytes.fromhex(old_hex)
    
    print(f"Old message: {old_hex[:50]}...")
    print(f"New message: {new_hex[:50]}...")
    
    # Find differences
    print("\nDifferences found:")
    for i in range(min(len(old_raw), len(raw))):
        if old_raw[i] != raw[i]:
            print(f"  Position {i}: 0x{old_raw[i]:02x} → 0x{raw[i]:02x}")
    
    # Extract ASCII sequences
    print("\nASCII content:")
    ascii_chars = []
    for i, byte in enumerate(payload):
        if 32 <= byte <= 126:
            ascii_chars.append(chr(byte))
        else:
            if ascii_chars:
                print(f"  Position {i-len(ascii_chars)}-{i-1}: '{''.join(ascii_chars)}'")
                ascii_chars = []
    if ascii_chars:
        print(f"  Position {len(payload)-len(ascii_chars)}-{len(payload)-1}: '{''.join(ascii_chars)}'")
    
    # Check for GPS data pattern (0x0200 message)
    if msg_id == 0x0200:
        print("\n🌍 LOCATION MESSAGE DETECTED!")
        print("This message contains GPS coordinates")
        # Would parse GPS here
    elif msg_id == 0x0100:
        print("\n📝 Registration message (no GPS data)")
    
    return msg_id

# Analyze both messages
print("NEW MESSAGE:")
print("=" * 60)
msg_id = analyze_message("7e01000021009590046863000e002c012f373031313145472d30350000003030303030303001d4c1423838383838647e")

print("\n\nPREVIOUS MESSAGE:")
print("=" * 60)
analyze_message("7e010000210095900468630005002c012f373031313145472d30350000003030303030303001d4c14238383838386f7e")