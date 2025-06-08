#!/usr/bin/env python3
"""
Test script to verify Flymaster endpoint compatibility with PHP curl post_as_file=1
This simulates how the PHP code sends data when post_as_file=1
"""

import hashlib
import requests
import time
from datetime import datetime, timezone

# Configuration
API_BASE_URL = "http://localhost:8000"
FLYMASTER_SECRET = "JijoHPvHXyHjajDK00V"  # Replace with actual secret from settings
DEVICE_ID = 123457

def create_auth_hash(device_id: int, secret: str) -> str:
    """Create SHA256 authentication hash"""
    combined = str(device_id) + secret
    return hashlib.sha256(combined.encode()).hexdigest()

def create_test_data():
    """Create test tracking data in the expected format"""
    current_time = int(time.time())
    
    # Create header line
    sha256key = create_auth_hash(DEVICE_ID, FLYMASTER_SECRET)
    header = f"{DEVICE_ID}, {sha256key}"
    
    # Create sample tracking points
    data_lines = [header]
    for i in range(3):
        # Format: uploaded_at, date_time (unix timestamp), lat, lon, gps_alt, speed, heading
        uploaded_at = current_time + i
        date_time = current_time + i * 10
        lat = 46.0 + (i * 0.001)  # Sample coordinates in Switzerland
        lon = 8.0 + (i * 0.001)
        gps_alt = 1000 + (i * 10)
        speed = 50 + i
        heading = 90 + (i * 10)
        
        line = f"{uploaded_at}, {date_time}, {lat}, {lon}, {gps_alt}, {speed}, {heading}"
        data_lines.append(line)
    
    # Add EOF marker
    data_lines.append("EOF")
    
    return "\n".join(data_lines)

def test_php_post_as_file():
    """Test the endpoint with PHP post_as_file=1 format (raw text/plain)"""
    print("Testing Flymaster endpoint with PHP post_as_file=1 format...")
    
    # Create test data
    test_data = create_test_data()
    print(f"Test data:\n{test_data}\n")
    
    # Simulate PHP curl with post_as_file=1 (sends raw data with text/plain content-type)
    headers = {
        'Content-Type': 'text/plain'
    }
    
    url = f"{API_BASE_URL}/tracking/flymaster/upload/file"
    print(f"Sending request to: {url}")
    print(f"Headers: {headers}")
    print(f"Body type: raw text data")
    
    try:
        response = requests.post(url, data=test_data, headers=headers)
        
        print(f"Response status: {response.status_code}")
        print(f"Response headers: {dict(response.headers)}")
        print(f"Response body: {response.text}")
        
        if response.status_code == 200 and response.text == "OK":
            print("✓ SUCCESS: Endpoint correctly handles PHP post_as_file=1 format!")
        else:
            print(f"✗ FAILED: Expected 200 status and 'OK' response")
            
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
    except Exception as e:
        print(f"Unexpected error: {e}")

def test_traditional_file_upload():
    """Test the endpoint with traditional file upload (multipart/form-data)"""
    print("\n" + "="*60)
    print("Testing traditional file upload format...")
    
    # Create test data
    test_data = create_test_data()
    
    # Create a file-like object
    files = {'file': ('test_data.txt', test_data, 'text/plain')}
    
    url = f"{API_BASE_URL}/tracking/flymaster/upload/file"
    print(f"Sending file upload to: {url}")
    
    try:
        response = requests.post(url, files=files)
        
        print(f"Response status: {response.status_code}")
        print(f"Response body: {response.text}")
        
        if response.status_code == 200 and response.text == "OK":
            print("✓ SUCCESS: Endpoint correctly handles file upload format!")
        else:
            print(f"✗ FAILED: Expected 200 status and 'OK' response")
            
    except Exception as e:
        print(f"Error: {e}")

def test_invalid_auth():
    """Test with invalid authentication"""
    print("\n" + "="*60)
    print("Testing invalid authentication...")
    
    # Create test data with invalid hash
    invalid_data = f"{DEVICE_ID}, invalid_hash_123\n"
    invalid_data += "1733659201,1733659201,47.123456,8.654321,1200.5,15.2,180.0\n"
    invalid_data += "EOF"
    
    headers = {'Content-Type': 'text/plain'}
    url = f"{API_BASE_URL}/tracking/flymaster/upload/file"
    
    try:
        response = requests.post(url, data=invalid_data, headers=headers)
        print(f"Response status: {response.status_code}")
        
        if response.status_code == 401:
            print("✓ Correctly rejected invalid authentication")
        else:
            print(f"Unexpected response: {response.text}")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    print("Flymaster PHP Compatibility Test")
    print("=" * 60)
    
    # Test PHP post_as_file=1 format (most important)
    test_php_post_as_file()
    
    # Test traditional file upload (backward compatibility)
    test_traditional_file_upload()
    
    # Test invalid authentication
    test_invalid_auth()
    
    print("\n" + "=" * 60)
    print("Test completed!")
    print("\nNote: Your PHP code with post_as_file=1 should work with this endpoint!")
