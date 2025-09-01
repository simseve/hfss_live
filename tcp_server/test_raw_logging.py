#!/usr/bin/env python3
"""
Test script to verify raw logging in standalone GPS TCP server
Sends various data formats to test logging capabilities
"""
import socket
import time
import sys

def test_raw_logging(host='localhost', port=9090):
    """Send various test data to GPS TCP server"""
    
    test_messages = [
        # Raw binary data
        b'\x00\x01\x02\x03\x04\x05',
        
        # TK905B watch format
        b'[SG*8800000015*0002*LK]',
        b'[SG*8800000015*002C*UD,220414,134652,A,22.571707,N,113.8613968,E,0.1,0.0,100,7,60,90,1000,50,0000,4,1,460,01,2533,720,20,2533,721,12,2533,722,11,2533,723,10,0,0]',
        
        # TK103 format  
        b'(027028641389BR00160205A2934.0133N10627.2544E000.0141830309.6200000000L00000000)',
        
        # Mixed ASCII and binary
        b'Hello\x00World\x01\x02\x03',
        
        # Unicode test
        'GPS测试数据📍'.encode('utf-8'),
        
        # Malformed data
        b'[INCOMPLETE',
        b'RANDOM_DATA_12345',
        
        # Empty message
        b'',
        
        # Large message
        b'X' * 1000,
        
        # Control characters
        b'Test\r\nNew\tLine\x00Null',
        
        # Hex string
        b'48656c6c6f20576f726c64',
    ]
    
    print(f"Connecting to {host}:{port}...")
    
    try:
        # Create socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((host, port))
        print(f"✅ Connected to server")
        
        # Send test messages
        for i, msg in enumerate(test_messages, 1):
            print(f"\nSending test message #{i}:")
            print(f"  Size: {len(msg)} bytes")
            print(f"  Data: {msg[:50]}..." if len(msg) > 50 else f"  Data: {msg}")
            
            sock.send(msg)
            time.sleep(0.5)  # Small delay between messages
            
            # Try to receive response
            sock.settimeout(0.5)
            try:
                response = sock.recv(1024)
                if response:
                    print(f"  Response: {response}")
            except socket.timeout:
                print(f"  No response (timeout)")
            except Exception as e:
                print(f"  Error receiving: {e}")
        
        print("\n✅ All test messages sent")
        print("Check the server logs for raw data output:")
        print("  - Console output")
        print("  - gps_tcp_raw.log")
        print("  - gps_raw_data.txt")
        print("  - gps_tcp_data.log")
        
        # Keep connection open for a bit
        time.sleep(2)
        
    except ConnectionRefusedError:
        print(f"❌ Connection refused. Is the server running on {host}:{port}?")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)
    finally:
        sock.close()
        print("\nConnection closed")

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Test GPS TCP server raw logging')
    parser.add_argument('--host', default='localhost', help='Server host')
    parser.add_argument('--port', type=int, default=9090, help='Server port')
    
    args = parser.parse_args()
    test_raw_logging(args.host, args.port)