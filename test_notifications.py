#!/usr/bin/env python3
"""
Test script to verify both Expo and FCM notifications are working
"""
from database.models import NotificationTokenDB
from database.db_conf import get_db
from api.send_notifications import send_push_message_unified, initialize_firebase
import asyncio
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))


async def test_notifications():
    print("🧪 Testing Push Notifications")
    print("=" * 50)

    # Initialize Firebase for FCM support
    try:
        initialize_firebase()
        print("✅ Firebase initialized successfully")
    except Exception as e:
        print(f"⚠️ Firebase initialization failed: {e}")
        print("FCM notifications will not work")

    # Get database session
    db_gen = get_db()
    db = next(db_gen)

    try:
        # Get more tokens to test both Expo and FCM
        results = db.query(NotificationTokenDB).limit(15).all()

        if not results:
            print("❌ No tokens found in database")
            return

        print(f"📱 Found {len(results)} tokens to test with")

        # Test notification content
        title = "🧪 Test Notification"
        body = "This is a test notification to verify the system is working"
        extra_data = {
            "test": "true",
            "timestamp": "2025-01-27"
        }

        print(f"\n📨 Sending test notification to {len(results)} tokens...")
        print(f"Message: {title} - {body}")

        successful_sends = 0
        errors = []

        for token_record in results:
            token = token_record.token
            token_short = token[:20] + "..." if len(token) > 20 else token

            try:
                # Send individual notification to test
                result = await send_push_message_unified(token, title, body, extra_data)
                successful_sends += 1
                print(f"✅ Success: {token_short}")

            except Exception as e:
                error_msg = str(e)
                errors.append({"token": token_short, "error": error_msg})
                print(f"❌ Failed: {token_short} - {error_msg}")

        print(f"\n📊 Test Results:")
        print(f"  Successful sends: {successful_sends}/{len(results)}")
        print(f"  Errors: {len(errors)}")

        if errors:
            print(f"\n🔍 Error Details:")
            for error in errors:
                print(f"  - {error['token']}: {error['error']}")

        if successful_sends > 0:
            print(f"\n✅ Push notification system is working!")
        else:
            print(f"\n❌ Push notification system has issues!")

    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(test_notifications())
