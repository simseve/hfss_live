#!/usr/bin/env python3
"""
Test Firebase initialization without starting the full app
"""

import os
import sys
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def test_firebase_initialization():
    """Test Firebase initialization"""
    try:
        from api.send_notifications import initialize_firebase
        from config import settings

        print("🔥 Testing Firebase initialization...")
        print("=" * 50)

        # Check environment variables using settings
        firebase_creds = settings.FIREBASE_CREDENTIALS
        firebase_key_path = settings.FIREBASE_KEY_PATH

        print("Environment check:")
        print(
            f"  FIREBASE_CREDENTIALS: {'✅ Set' if firebase_creds else '❌ Not set'}")
        print(
            f"  FIREBASE_KEY_PATH: {'✅ Set' if firebase_key_path else '❌ Not set'}")

        if firebase_key_path:
            file_exists = os.path.exists(firebase_key_path)
            print(f"  Key file exists: {'✅ Yes' if file_exists else '❌ No'}")

        print("\nAttempting Firebase initialization...")
        initialize_firebase()

        # Test if Firebase is properly initialized
        import firebase_admin
        try:
            app = firebase_admin.get_app()
            print("✅ Firebase Admin SDK initialized successfully!")
            print(f"   App name: {app.name}")
            return True
        except ValueError:
            print("❌ Firebase Admin SDK not initialized")
            return False

    except ImportError as e:
        print(f"❌ Import error: {e}")
        return False
    except Exception as e:
        print(f"❌ Firebase initialization failed: {e}")
        return False


def show_setup_instructions():
    """Show setup instructions for Firebase"""
    print("\n" + "=" * 50)
    print("🔧 FIREBASE SETUP INSTRUCTIONS")
    print("=" * 50)
    print()
    print("To enable FCM notifications, you need to set up Firebase:")
    print()
    print("1. Go to Firebase Console (https://console.firebase.google.com/)")
    print("2. Select your project (or create one)")
    print("3. Go to Project Settings > Service Accounts")
    print("4. Click 'Generate new private key'")
    print("5. Download the JSON file")
    print()
    print("Then set ONE of these environment variables:")
    print()
    print("Option A - JSON credentials as environment variable (recommended):")
    print("  export FIREBASE_CREDENTIALS='$(cat path/to/your-firebase-key.json)'")
    print()
    print("Option B - Path to the JSON file:")
    print("  export FIREBASE_KEY_PATH='/path/to/your-firebase-key.json'")
    print()
    print("Option C - Use Google Cloud Application Default Credentials")
    print("  (automatically works if running on Google Cloud)")
    print()
    print("After setting the environment variable, restart your application.")


if __name__ == "__main__":
    print("🧪 Firebase Configuration Test")
    success = test_firebase_initialization()

    if not success:
        show_setup_instructions()
        sys.exit(1)
    else:
        print("\n🎉 Firebase is ready for FCM notifications!")
        sys.exit(0)
