#!/usr/bin/env python3
"""
Test script for local GPS TCP server (embedded mode)
"""
import socket
import time
import sys

def test_gps_connection(host='localhost', port=5002):
    """Test if GPS TCP server is accepting connections"""
    print(f"Testing GPS TCP server at {host}:{port}")
    
    try:
        # Create socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        
        # Try to connect
        print(f"Attempting to connect...")
        sock.connect((host, port))
        print(f"✓ Successfully connected to GPS TCP server!")
        
        # Send a test message (TK905B format)
        test_message = "[SG*1234567890*0006*LK,0,100]"
        print(f"Sending test message: {test_message}")
        sock.send(test_message.encode())
        
        # Wait for response
        sock.settimeout(2)
        try:
            response = sock.recv(1024)
            print(f"✓ Received response: {response.decode()}")
        except socket.timeout:
            print("⚠ No response received (timeout)")
        
        # Close connection
        sock.close()
        print("✓ Connection closed successfully")
        
        return True
        
    except ConnectionRefusedError:
        print(f"✗ Connection refused - GPS TCP server not running on {host}:{port}")
        print("\nTo start the server locally:")
        print("  uvicorn app:app --reload --port 8000")
        return False
        
    except socket.timeout:
        print(f"✗ Connection timeout - server not responding")
        return False
        
    except Exception as e:
        print(f"✗ Error: {e}")
        return False


def check_api_status(host='localhost', api_port=8000):
    """Check if FastAPI is running and GPS server status"""
    import requests
    
    print(f"\nChecking FastAPI status at {host}:{api_port}")
    
    try:
        # Check health endpoint
        response = requests.get(f"http://{host}:{api_port}/health", timeout=5)
        if response.status_code == 200:
            print("✓ FastAPI is running")
            
            data = response.json()
            if 'gps_tcp_server' in data:
                gps_status = data['gps_tcp_server']
                print(f"  GPS TCP Server: {gps_status.get('status', 'unknown')}")
                if gps_status.get('running'):
                    print(f"    - Active connections: {gps_status.get('active_connections', 0)}")
                    print(f"    - Messages received: {gps_status.get('messages_received', 0)}")
        else:
            print(f"⚠ FastAPI returned status {response.status_code}")
            
        # Check GPS TCP specific endpoint
        response = requests.get(f"http://{host}:{api_port}/gps-tcp/status", timeout=5)
        if response.status_code == 200:
            print("✓ GPS TCP status endpoint available")
        elif response.status_code == 404:
            print("⚠ GPS TCP server is disabled in configuration")
            
    except requests.ConnectionError:
        print(f"✗ Cannot connect to FastAPI at {host}:{api_port}")
        print("\nTo start FastAPI with embedded GPS server:")
        print("  export GPS_TCP_ENABLED=true")
        print("  uvicorn app:app --reload --port 8000")
    except Exception as e:
        print(f"✗ Error checking API: {e}")


if __name__ == "__main__":
    print("=== Local GPS TCP Server Test (Embedded Mode) ===\n")
    
    # Check if custom port provided
    port = 5002  # Default from .env
    if len(sys.argv) > 1:
        port = int(sys.argv[1])
    
    # First check API
    check_api_status()
    
    # Then test GPS TCP connection
    print("")
    if test_gps_connection(port=port):
        print("\n✅ GPS TCP server is working in embedded mode!")
    else:
        print("\n❌ GPS TCP server test failed")
        print("\nTroubleshooting:")
        print("1. Check .env file has GPS_TCP_ENABLED=true")
        print("2. Check GPS_TCP_PORT matches (currently set to 5002)")
        print("3. Make sure FastAPI is running:")
        print("   uvicorn app:app --reload --port 8000")