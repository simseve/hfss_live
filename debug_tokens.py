#!/usr/bin/env python3
"""
Debug script to check notification tokens in the database
"""

from database.db_conf import get_db
from database.models import NotificationTokenDB
from api.send_notifications import detect_token_type, validate_expo_token, validate_fcm_token, TokenType
from sqlalchemy.orm import Session


def analyze_tokens():
    """Analyze tokens in the database"""
    db: Session = next(get_db())

    try:
        # Get all tokens
        all_tokens = db.query(NotificationTokenDB).all()

        print(f"Total tokens in database: {len(all_tokens)}")
        print("=" * 60)

        expo_valid = 0
        expo_invalid = 0
        fcm_valid = 0
        fcm_invalid = 0
        unknown = 0

        # Analyze each token
        for i, token_record in enumerate(all_tokens):
            token = token_record.token
            token_type = detect_token_type(token)

            print(f"\nToken {i+1}:")
            print(f"  ID: {token_record.id}")
            print(f"  Race ID: {token_record.race_id}")
            print(f"  Token (first 30 chars): {token[:30]}...")
            print(f"  Token length: {len(token)}")
            print(f"  Detected type: {token_type.value}")

            if token_type == TokenType.EXPO:
                is_valid = validate_expo_token(token)
                print(
                    f"  Expo validation: {'✅ VALID' if is_valid else '❌ INVALID'}")
                if is_valid:
                    expo_valid += 1
                else:
                    expo_invalid += 1
            else:  # FCM
                is_valid = validate_fcm_token(token)
                print(
                    f"  FCM validation: {'✅ VALID' if is_valid else '❌ INVALID'}")
                if is_valid:
                    fcm_valid += 1
                else:
                    fcm_invalid += 1

            # Show first few characters to identify patterns
            if token.startswith("ExponentPushToken["):
                print(f"  Format: Standard Expo token")
            elif token.startswith("expo-"):
                print(f"  Format: Alternative Expo token")
            elif ":" in token:
                print(f"  Format: Possible FCM token")
            else:
                print(f"  Format: Unknown format")
                unknown += 1

        print("\n" + "=" * 60)
        print("SUMMARY:")
        print(f"  Expo tokens (valid): {expo_valid}")
        print(f"  Expo tokens (invalid): {expo_invalid}")
        print(f"  FCM tokens (valid): {fcm_valid}")
        print(f"  FCM tokens (invalid): {fcm_invalid}")
        print(f"  Unknown format: {unknown}")
        print(
            f"  Total invalid tokens: {expo_invalid + fcm_invalid + unknown}")

        if expo_invalid + fcm_invalid + unknown > 0:
            print("\n⚠️  WARNING: Invalid tokens found!")
            print("   These tokens will cause 'Invalid push token' errors.")
            print("   Consider cleaning them up from the database.")

    except Exception as e:
        print(f"Error analyzing tokens: {e}")
    finally:
        db.close()


if __name__ == "__main__":
    print("🔍 Analyzing notification tokens in database...")
    analyze_tokens()
