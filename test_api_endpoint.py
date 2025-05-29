#!/usr/bin/env python3
"""
Test script for the complete notification API endpoint
Tests the /notifications/send endpoint via HTTP API
"""

import requests
import json
import os
import sys
from datetime import datetime

# Add the current directory to Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))


def test_notification_api():
    """Test the complete notification API endpoint"""

    # API configuration
    BASE_URL = "http://localhost:8000"
    ENDPOINT = f"{BASE_URL}/notifications/send"

    # Test JWT token (replace with a valid token for your system)
    # For testing, you might need to generate a valid JWT token
    TEST_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ0ZXN0X3VzZXIiLCJhdWQiOiJhcGkuaGlrZWFuZGZseS5hcHAiLCJpc3MiOiJoaWtlYW5kZmx5LmFwcCIsImV4cCI6OTk5OTk5OTk5OX0.placeholder"

    # Test notification payload
    notification_data = {
        "raceId": "test_race_123",
        "title": "🧪 API Test Notification",
        "body": "Testing the complete notification API endpoint functionality",
        "data": {
            "priority": "normal",
            "category": "test",
            "timestamp": datetime.now().isoformat(),
            "source": "api_test"
        }
    }

    # Request headers
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {TEST_TOKEN}"
    }

    print("🧪 Testing Notification API Endpoint")
    print("=" * 50)
    print(f"URL: {ENDPOINT}")
    print(f"Payload: {json.dumps(notification_data, indent=2)}")
    print()

    try:
        # Send the HTTP POST request
        response = requests.post(
            ENDPOINT,
            json=notification_data,
            headers=headers,
            timeout=30
        )

        print(f"📡 Response Status: {response.status_code}")
        print(f"📡 Response Headers: {dict(response.headers)}")
        print()

        if response.status_code == 200:
            result = response.json()
            print("✅ API Request Successful!")
            print(f"📊 Response: {json.dumps(result, indent=2)}")

            # Analyze the response
            if result.get("success"):
                print(
                    f"✅ Notifications sent: {result.get('sent', 0)}/{result.get('total', 0)}")
                if result.get('token_distribution'):
                    dist = result['token_distribution']
                    print(
                        f"📱 Token distribution: {dist.get('expo', 0)} Expo, {dist.get('fcm', 0)} FCM")
                if result.get('errors', 0) > 0:
                    print(f"⚠️  Errors: {result.get('errors', 0)}")
                    if result.get('error_details'):
                        for error in result['error_details'][:3]:  # Show first 3 errors
                            print(f"   - {error}")
            else:
                print(
                    f"❌ API returned success=false: {result.get('message', 'Unknown error')}")

        elif response.status_code == 401:
            print("🔒 Authentication Error - Invalid or expired token")
            print(f"Response: {response.text}")

        elif response.status_code == 500:
            print("💥 Server Error")
            try:
                error_detail = response.json()
                print(f"Error details: {json.dumps(error_detail, indent=2)}")
            except:
                print(f"Raw response: {response.text}")

        else:
            print(f"❌ Unexpected response code: {response.status_code}")
            print(f"Response: {response.text}")

    except requests.exceptions.ConnectionError:
        print("❌ Connection Error - Is the FastAPI server running on localhost:8000?")
        print("💡 Try running: python app.py")

    except requests.exceptions.Timeout:
        print("⏰ Request timeout - Server might be overloaded")

    except Exception as e:
        print(f"💥 Unexpected error: {str(e)}")
        import traceback
        traceback.print_exc()


def test_server_status():
    """Test if the server is running"""
    try:
        response = requests.get("http://localhost:8000/docs", timeout=5)
        if response.status_code == 200:
            print("✅ FastAPI server is running")
            return True
        else:
            print(f"⚠️  Server responded with status {response.status_code}")
            return False
    except requests.exceptions.ConnectionError:
        print("❌ FastAPI server is not running")
        return False
    except Exception as e:
        print(f"❌ Error checking server status: {e}")
        return False


if __name__ == "__main__":
    print("🚀 Notification API Test Suite")
    print("=" * 50)

    # First check if server is running
    if test_server_status():
        print()
        test_notification_api()
    else:
        print("💡 Please start the FastAPI server first:")
        print("   cd /Users/simone/Apps/hfss_live")
        print("   python app.py")
