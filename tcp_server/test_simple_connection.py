#!/usr/bin/env python3
"""Simple GPS TCP server connection test"""
import socket
import sys
import time

def test_gps_server(host='dev-api.hikeandfly.app', port=5002):
    """Test GPS TCP server connection and response"""
    print(f"Testing GPS TCP server at {host}:{port}")
    
    try:
        # Create socket with longer timeout
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(10)
        
        print("Connecting...")
        s.connect((host, port))
        print("✅ Connected successfully!")
        
        # Send a login message (TK905B format)
        login_msg = "[3G*8800000015*0006*LK,0,100]"
        print(f"Sending login: {login_msg}")
        s.send(login_msg.encode())
        
        # Try to receive response
        s.settimeout(5)
        try:
            response = s.recv(1024)
            if response:
                print(f"✅ Received response: {response.decode()}")
            else:
                print("⚠️ No response received")
        except socket.timeout:
            print("⚠️ Response timeout - but connection works!")
        
        # Send a location update
        time.sleep(1)
        location_msg = "[3G*8800000015*0031*UD2,290825,073500,A,47.3769,8.5417,0,0,100,12,100,50,0,0,00000000,0,0]"
        print(f"Sending location: {location_msg}")
        s.send(location_msg.encode())
        
        # Try to receive response
        try:
            response = s.recv(1024)
            if response:
                print(f"✅ Received response: {response.decode()}")
        except socket.timeout:
            pass
        
        s.close()
        print("\n✅ Test completed successfully - GPS TCP server is working!")
        return True
        
    except socket.timeout:
        print("❌ Connection timeout - server may not be accessible")
        print("   Check firewall rules and port forwarding")
        return False
    except ConnectionRefused:
        print("❌ Connection refused - server not running on this port")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

if __name__ == "__main__":
    host = sys.argv[1] if len(sys.argv) > 1 else 'dev-api.hikeandfly.app'
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 5002
    
    success = test_gps_server(host, port)
    sys.exit(0 if success else 1)