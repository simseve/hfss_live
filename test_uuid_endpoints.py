#!/usr/bin/env python3
"""
Test script for UUID-based device activation/deactivation endpoints.
"""

import requests
import json
from datetime import datetime, timedelta
import jwt
import sys

# Configuration
BASE_URL = "http://localhost:8000"
SECRET_KEY = "your-secret-key-here"  # Replace with actual secret key from .env

def create_admin_token():
    """Create a valid admin JWT token for testing"""
    payload = {
        "sub": "admin:test",
        "exp": datetime.utcnow() + timedelta(hours=1),
        "iat": datetime.utcnow(),
        "aud": "api.hikeandfly.app",
        "iss": "hikeandfly.app"
    }
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")

def test_activate_device_by_uuid(device_uuid, race_id, token):
    """Test the activation endpoint"""
    url = f"{BASE_URL}/tracking/api/devices/{device_uuid}/activate"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    params = {"race_id": race_id}
    
    print(f"\n🔧 Testing activation for device UUID: {device_uuid}")
    print(f"   Race ID: {race_id}")
    
    response = requests.patch(url, headers=headers, params=params)
    
    print(f"   Status: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"   ✅ Success: {data.get('message')}")
        print(f"   Device ID: {data['registration']['id']}")
        print(f"   Serial: {data['registration']['serial_number']}")
        print(f"   Active: {data['registration']['is_active']}")
    else:
        print(f"   ❌ Error: {response.text}")
    
    return response

def test_deactivate_device_by_uuid(device_uuid, token):
    """Test the deactivation endpoint"""
    url = f"{BASE_URL}/tracking/api/devices/{device_uuid}/deactivate"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    print(f"\n🔧 Testing deactivation for device UUID: {device_uuid}")
    
    response = requests.patch(url, headers=headers)
    
    print(f"   Status: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"   ✅ Success: {data.get('message')}")
        print(f"   Device ID: {data['registration']['id']}")
        print(f"   Serial: {data['registration']['serial_number']}")
        print(f"   Active: {data['registration']['is_active']}")
    else:
        print(f"   ❌ Error: {response.text}")
    
    return response

def main():
    """Main test function"""
    print("=" * 60)
    print("UUID-Based Device Endpoint Tests")
    print("=" * 60)
    
    # Create admin token
    try:
        token = create_admin_token()
        print(f"✅ Admin token created successfully")
    except Exception as e:
        print(f"❌ Failed to create token: {e}")
        print("\nPlease update the SECRET_KEY in this script with your actual secret key from .env")
        return
    
    # Test parameters - replace with actual values from your database
    device_uuid = "123e4567-e89b-12d3-a456-426614174000"  # Replace with actual device UUID
    race_id = "test-race-2024"  # Replace with actual race ID
    
    print("\n" + "=" * 60)
    print("NOTE: Replace device_uuid and race_id with actual values from your database")
    print("You can find these by querying: SELECT id, serial_number, race_id FROM device_registrations;")
    print("=" * 60)
    
    # Test activation
    test_activate_device_by_uuid(device_uuid, race_id, token)
    
    # Test deactivation
    test_deactivate_device_by_uuid(device_uuid, token)
    
    print("\n" + "=" * 60)
    print("Tests completed!")
    print("=" * 60)

if __name__ == "__main__":
    main()