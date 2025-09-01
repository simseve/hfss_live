#!/usr/bin/env python3
"""
Test the production JT808 handler with real tracker data
"""
import sys
sys.path.insert(0, '/Users/simone/Apps/hfss_live')

from tcp_server.protocols.jt808_production import JT808ProductionHandler

def test_messages():
    handler = JT808ProductionHandler()
    
    # Your actual messages
    messages = [
        ("Registration 1", "7e010000210095900468630005002c012f373031313145472d30350000003030303030303001d4c14238383838386f7e"),
        ("Registration 2", "7e01000021009590046863000e002c012f373031313145472d30350000003030303030303001d4c1423838383838647e"),
    ]
    
    print("Testing JT808 Production Handler")
    print("=" * 80)
    
    for name, hex_msg in messages:
        print(f"\n{name}:")
        print("-" * 40)
        
        # Test can_handle
        can_handle = handler.can_handle(hex_msg)
        print(f"Can handle: {can_handle}")
        
        if can_handle:
            # Parse message
            parsed = handler.parse_message(hex_msg)
            if parsed:
                print(f"Parsed successfully!")
                print(f"  Message Type: {parsed.get('message')}")
                print(f"  Message ID: {parsed.get('msg_id_hex')}")
                print(f"  Device ID: {parsed.get('device_id')}")
                print(f"  Terminal Phone: {parsed.get('terminal_phone')}")
                print(f"  Serial No: {parsed.get('serial_no')}")
                print(f"  Version: {parsed.get('version')}")
                
                # Additional fields for registration
                if parsed.get('manufacturer'):
                    print(f"  Manufacturer: {parsed.get('manufacturer')}")
                if parsed.get('terminal_model'):
                    print(f"  Model: {parsed.get('terminal_model')}")
                if parsed.get('terminal_id'):
                    print(f"  Terminal ID: {parsed.get('terminal_id')}")
                
                # GPS fields if present
                if parsed.get('latitude') is not None:
                    print(f"  🌍 GPS Location: {parsed['latitude']:.6f}, {parsed['longitude']:.6f}")
                    print(f"  Speed: {parsed.get('speed')} km/h")
                    print(f"  Altitude: {parsed.get('altitude')} m")
                
                # Create response
                response = handler.create_response(parsed, success=True)
                print(f"\nServer Response:")
                print(f"  Hex: {response}")
                print(f"  Bytes: {bytes.fromhex(response)}")
                
                # Format for display
                print(f"\nFormatted Output:")
                print(handler.format_parsed_data(parsed))
            else:
                print("Failed to parse message")
    
    # Test with a fake location message to show GPS parsing
    print("\n" + "=" * 80)
    print("Testing Location Message Parsing (simulated):")
    print("-" * 40)
    
    # Create a simple 0x0200 location message
    # This is a simplified example - real message would have proper formatting
    location_hex = "7e0200001c0123456789120001" + \
                  "00000000" + \
                  "00000000" + \
                  "016f9ed8" + \
                  "06c23ac0" + \
                  "01f4" + \
                  "0064" + \
                  "005a" + \
                  "241201123045" + \
                  "7e"
    
    print("Simulated location message (0x0200)")
    parsed = handler.parse_message(location_hex)
    if parsed and parsed.get('latitude'):
        print(f"  🌍 Location parsed: {parsed['latitude']:.6f}, {parsed['longitude']:.6f}")
        print(f"  Speed: {parsed.get('speed')} km/h")
    else:
        print("  Note: Real location messages from your tracker will be parsed when received")

if __name__ == '__main__':
    test_messages()