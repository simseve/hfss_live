#!/usr/bin/env python3
"""
Test if JT808 ACK responses are being sent
"""
import socket
import time
import binascii

def test_registration_ack(host='localhost', port=9090):
    """Send registration and check for ACK"""
    
    # Your actual registration message
    registration_hex = "7e010000210095900468630005002c012f373031313145472d30350000003030303030303001d4c14238383838386f7e"
    registration_bytes = bytes.fromhex(registration_hex)
    
    print("JT808 ACK Response Test")
    print("=" * 60)
    print(f"Connecting to {host}:{port}...")
    
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)  # 5 second timeout
        sock.connect((host, port))
        print("✅ Connected")
        
        print(f"\nSending registration message (0x0100):")
        print(f"  Hex: {registration_hex[:50]}...")
        print(f"  Size: {len(registration_bytes)} bytes")
        
        # Send registration
        sock.send(registration_bytes)
        print("📤 Message sent")
        
        # Wait for response
        print("\nWaiting for server response...")
        start_time = time.time()
        
        try:
            response = sock.recv(1024)
            elapsed = time.time() - start_time
            
            if response:
                print(f"✅ RESPONSE RECEIVED in {elapsed:.3f} seconds!")
                print(f"  Size: {len(response)} bytes")
                print(f"  Raw: {response}")
                print(f"  Hex: {binascii.hexlify(response).decode('ascii')}")
                
                # Check if it's a JT808 response
                if response[0] == 0x7E and response[-1] == 0x7E:
                    print("  ✅ Valid JT808 frame (0x7E delimiters)")
                    
                    # Check message type
                    if len(response) > 3:
                        msg_id = (response[1] << 8) | response[2]
                        if msg_id == 0x8100:
                            print("  ✅ Registration ACK (0x8100)")
                        elif msg_id == 0x8001:
                            print("  ✅ General ACK (0x8001)")
                        else:
                            print(f"  Message ID: 0x{msg_id:04x}")
                else:
                    print("  ⚠️  Not a JT808 response")
                    
                return True
            else:
                print("❌ Empty response")
                return False
                
        except socket.timeout:
            print("❌ No response received (timeout)")
            return False
            
    except ConnectionRefusedError:
        print(f"❌ Connection refused. Is the server running on {host}:{port}?")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False
    finally:
        sock.close()
        print("\nConnection closed")

if __name__ == '__main__':
    import sys
    
    host = sys.argv[1] if len(sys.argv) > 1 else 'localhost'
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 9090
    
    success = test_registration_ack(host, port)
    
    if not success:
        print("\n⚠️  Server is NOT sending ACK responses!")
        print("This is why your tracker keeps retrying registration.")
    else:
        print("\n✅ Server is properly sending ACK responses!")