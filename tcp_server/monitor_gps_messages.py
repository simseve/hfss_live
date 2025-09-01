#!/usr/bin/env python3
"""
Monitor GPS messages and look for location data (0x0200)
"""
import sys
import time
from datetime import datetime

def parse_jt808_message(hex_string):
    """Parse JT808 message and identify type"""
    try:
        raw = bytes.fromhex(hex_string.strip())
        
        if len(raw) < 10 or raw[0] != 0x7E or raw[-1] != 0x7E:
            return None
            
        payload = raw[1:-1]
        msg_id = int.from_bytes(payload[0:2], 'big')
        
        result = {
            'timestamp': datetime.now().isoformat(),
            'msg_id': f'0x{msg_id:04x}',
            'hex': hex_string[:100] + '...' if len(hex_string) > 100 else hex_string
        }
        
        # Identify message type
        if msg_id == 0x0100:
            result['type'] = '📝 REGISTRATION (no GPS)'
            result['description'] = 'Device registering with server'
        elif msg_id == 0x0102:
            result['type'] = '🔐 AUTHENTICATION (no GPS)'
            result['description'] = 'Device authenticating'
        elif msg_id == 0x0200:
            result['type'] = '🌍 LOCATION REPORT (HAS GPS!)'
            result['description'] = 'GPS coordinates in this message!'
            result['gps'] = parse_location_data(payload)
        elif msg_id == 0x0002:
            result['type'] = '💓 HEARTBEAT (no GPS)'
            result['description'] = 'Keep-alive signal'
        elif msg_id == 0x0704:
            result['type'] = '📊 BATCH LOCATION (HAS GPS!)'
            result['description'] = 'Multiple GPS points'
        else:
            result['type'] = f'❓ UNKNOWN (0x{msg_id:04x})'
            result['description'] = 'Unknown message type'
            
        return result
    except Exception as e:
        return {'error': str(e)}

def parse_location_data(payload):
    """Extract GPS data from 0x0200 message"""
    try:
        # Approximate parsing - would need full spec
        # After header (varies by version), location data includes:
        # 4 bytes: Alarm flags
        # 4 bytes: Status  
        # 4 bytes: Latitude (degrees * 10^6)
        # 4 bytes: Longitude (degrees * 10^6)
        # 2 bytes: Altitude
        # 2 bytes: Speed
        # 2 bytes: Direction
        # 6 bytes: Time BCD
        
        # This is simplified - actual offset depends on header size
        if len(payload) > 40:
            # Try to find GPS pattern (large numbers that could be coordinates)
            for offset in [16, 20, 24, 28]:  # Try different offsets
                if len(payload) > offset + 8:
                    lat_candidate = int.from_bytes(payload[offset:offset+4], 'big')
                    lon_candidate = int.from_bytes(payload[offset+4:offset+8], 'big')
                    
                    # Check if these could be coordinates (rough check)
                    lat = lat_candidate / 1000000.0
                    lon = lon_candidate / 1000000.0
                    
                    if -90 <= lat <= 90 and -180 <= lon <= 180 and lat != 0:
                        return {
                            'latitude': lat,
                            'longitude': lon,
                            'offset_used': offset
                        }
        
        return {'status': 'Could not parse GPS coordinates'}
    except Exception as e:
        return {'error': str(e)}

def monitor_log_file(log_file='gps_tcp_raw.log'):
    """Monitor log file for GPS messages"""
    print("🔍 GPS Message Monitor")
    print("=" * 60)
    print(f"Monitoring for location messages (0x0200)")
    print(f"Reading from: {log_file}")
    print("=" * 60)
    print()
    
    seen_messages = set()
    location_count = 0
    
    print("Recent messages:")
    print("-" * 60)
    
    try:
        with open(log_file, 'r') as f:
            # Go to end of file
            f.seek(0, 2)
            
            while True:
                line = f.readline()
                if line:
                    # Look for hex data in the log
                    if 'Hex dump:' in line or 'hex=' in line:
                        # Extract hex string
                        if 'hex=' in line:
                            hex_part = line.split('hex=')[1].strip()
                        else:
                            hex_part = line.split('Hex dump:')[1].strip()
                        
                        if hex_part and hex_part not in seen_messages:
                            seen_messages.add(hex_part)
                            
                            parsed = parse_jt808_message(hex_part)
                            if parsed:
                                print(f"[{parsed['timestamp']}]")
                                print(f"  Type: {parsed['type']}")
                                print(f"  {parsed['description']}")
                                
                                if 'gps' in parsed:
                                    location_count += 1
                                    print(f"  🎯 GPS DATA: {parsed['gps']}")
                                    print(f"  >>> LOCATION MESSAGE #{location_count} FOUND! <<<")
                                
                                print(f"  Hex: {parsed['hex']}")
                                print("-" * 60)
                else:
                    time.sleep(0.5)
                    
    except FileNotFoundError:
        print(f"❌ Log file not found: {log_file}")
        print("Make sure the GPS TCP server is running")
    except KeyboardInterrupt:
        print("\n\nMonitoring stopped")
        print(f"Total location messages found: {location_count}")

if __name__ == '__main__':
    if len(sys.argv) > 1:
        # Test with provided hex string
        hex_msg = sys.argv[1]
        result = parse_jt808_message(hex_msg)
        print(result)
    else:
        # Monitor log file
        monitor_log_file()