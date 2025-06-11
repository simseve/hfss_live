#!/usr/bin/env python3
"""
Test script for data-only FCM notifications
"""
import asyncio
import sys
from api.send_notifications import initialize_firebase, send_fcm_message

async def test_fcm_data_only():
    """Test sending a data-only FCM notification"""
    
    # Initialize Firebase
    print("Initializing Firebase...")
    initialize_firebase()
    
    # Test FCM token (you'll need to replace this with a real token)
    test_token = input("Enter FCM token to test: ").strip()
    
    if not test_token:
        print("No token provided. Exiting.")
        return
    
    # Test data
    title = "Test Data-Only Notification"
    body = "This is a data-only message that should wake up the app"
    extra_data = {
        "type": "test",
        "timestamp": str(datetime.datetime.now()),
        "custom_field": "custom_value"
    }
    
    print(f"\nSending data-only notification to token: {test_token[:20]}...")
    print(f"Title: {title}")
    print(f"Body: {body}")
    print(f"Extra data: {extra_data}")
    
    try:
        result = await send_fcm_message(test_token, title, body, extra_data)
        print(f"\n✅ Success! Message ID: {result.get('message_id')}")
        print("\nThe notification was sent as a data-only message.")
        print("Expected behavior:")
        print("- App should wake up in the background")
        print("- No system notification should appear")
        print("- App can process the data and optionally show a custom notification")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    import datetime
    exit_code = asyncio.run(test_fcm_data_only())
    sys.exit(exit_code)