#!/usr/bin/env python3
"""
Cleanup script to remove invalid notification tokens from the database
"""

from database.db_conf import get_db
from database.models import NotificationTokenDB
from api.send_notifications import validate_expo_token, validate_fcm_token, detect_token_type, TokenType
from sqlalchemy.orm import Session


def cleanup_invalid_tokens():
    """Remove invalid tokens from the database"""
    db: Session = next(get_db())

    try:
        # Get all tokens
        all_tokens = db.query(NotificationTokenDB).all()

        print(f"Checking {len(all_tokens)} tokens for validity...")
        print("=" * 60)

        invalid_tokens = []
        jwt_tokens = []

        # Find invalid tokens
        for token_record in all_tokens:
            token = token_record.token
            token_type = detect_token_type(token)

            # Check if it's a JWT token (major issue)
            if token.startswith("eyJ") and len(token) > 200:
                jwt_tokens.append(token_record)
                continue

            # Validate based on detected type
            is_valid = False
            if token_type == TokenType.EXPO:
                is_valid = validate_expo_token(token)
            else:  # FCM
                is_valid = validate_fcm_token(token)

            if not is_valid:
                invalid_tokens.append(token_record)

        print(f"Found {len(jwt_tokens)} JWT tokens (serious issue)")
        print(f"Found {len(invalid_tokens)} other invalid tokens")
        print(f"Total invalid tokens: {len(jwt_tokens) + len(invalid_tokens)}")

        if jwt_tokens:
            print("\n🚨 JWT TOKENS FOUND (should not be in notification tokens table):")
            for token_record in jwt_tokens:
                print(f"  ID: {token_record.id}")
                print(f"  Race ID: {token_record.race_id}")
                print(f"  Token: {token_record.token[:50]}...")
                print(f"  Created: {token_record.created_at}")
                print()

        if invalid_tokens:
            print("\n❌ OTHER INVALID TOKENS:")
            for token_record in invalid_tokens:
                print(f"  ID: {token_record.id}")
                print(f"  Race ID: {token_record.race_id}")
                print(f"  Token: {token_record.token[:30]}...")
                print()

        all_invalid = jwt_tokens + invalid_tokens

        if all_invalid:
            response = input(
                f"\nDo you want to DELETE {len(all_invalid)} invalid tokens? (y/N): ")

            if response.lower() == 'y':
                # Delete invalid tokens
                for token_record in all_invalid:
                    db.delete(token_record)

                db.commit()
                print(
                    f"✅ Successfully deleted {len(all_invalid)} invalid tokens!")

                # Verify cleanup
                remaining_tokens = db.query(NotificationTokenDB).count()
                print(f"📊 Remaining tokens in database: {remaining_tokens}")

            else:
                print("❌ No tokens were deleted.")
        else:
            print("✅ No invalid tokens found! Database is clean.")

    except Exception as e:
        print(f"❌ Error during cleanup: {e}")
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    print("🧹 Cleaning up invalid notification tokens...")
    cleanup_invalid_tokens()
