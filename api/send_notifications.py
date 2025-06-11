import firebase_admin
from firebase_admin import credentials, messaging
import re
from typing import List, Tuple, Dict, Any
from enum import Enum
import logging
import asyncio
import datetime
from exponent_server_sdk import (
    DeviceNotRegisteredError,
    PushClient,
    PushMessage,
    PushServerError,
)

logger = logging.getLogger(__name__)


class TokenType(Enum):
    EXPO = "expo"
    FCM = "fcm"


def serialize_fcm_data(data: dict) -> dict:
    """
    Convert all values in FCM data to strings as required by Firebase.
    FCM requires all data field values to be strings.
    """
    if not data:
        return {}

    import json
    serialized = {}
    for key, value in data.items():
        if isinstance(value, str):
            serialized[key] = value
        else:
            # Convert complex objects (lists, dicts, booleans, numbers) to JSON strings
            serialized[key] = json.dumps(value)

    return serialized


def detect_token_type(token: str) -> TokenType:
    """Detect whether a token is Expo or FCM format"""
    if token.startswith("ExponentPushToken[") and token.endswith("]"):
        return TokenType.EXPO
    elif re.match(r'^[a-zA-Z0-9_-]+:[a-zA-Z0-9_-]+$', token) and len(token) > 100:
        return TokenType.FCM
    elif token.startswith("expo-"):  # Another Expo format
        return TokenType.EXPO
    else:
        # Log unknown token format for debugging
        logger.warning(
            f"Unknown token format detected: {token[:20]}... (length: {len(token)})")
        # Check if it's a JWT token (common mistake)
        if token.startswith("eyJ") and len(token) > 200:
            logger.error(
                f"JWT token found in notification tokens table! This should not happen. Token ID should be investigated.")
        # Default to Expo for backward compatibility, but this might cause issues
        return TokenType.EXPO

# Initialize Firebase Admin SDK (do this once at startup)


def initialize_firebase():
    """Initialize Firebase Admin SDK - call this once when your app starts"""
    try:
        # Check if already initialized
        try:
            firebase_admin.get_app()
            logger.info("Firebase Admin SDK already initialized")
            return
        except ValueError:
            # Not initialized yet, continue with initialization
            pass

        # Option 1: Use service account key from environment variable (recommended)
        import os
        from config import settings
        firebase_credentials = settings.FIREBASE_CREDENTIALS
        project_id = None

        if firebase_credentials:
            # Parse JSON credentials from environment variable
            import json
            cred_dict = json.loads(firebase_credentials)
            project_id = cred_dict.get("project_id")
            cred = credentials.Certificate(cred_dict)
            logger.info("Using Firebase credentials from environment variable")
        else:
            # Option 2: Use service account key file path from environment
            firebase_key_path = settings.FIREBASE_KEY_PATH
            if firebase_key_path and os.path.exists(firebase_key_path):
                # Read the project_id from the service account file
                import json
                try:
                    with open(firebase_key_path, 'r') as f:
                        service_account_info = json.load(f)
                        project_id = service_account_info.get("project_id")
                except Exception as e:
                    logger.warning(
                        f"Could not read project_id from {firebase_key_path}: {e}")

                cred = credentials.Certificate(firebase_key_path)
                logger.info(
                    f"Using Firebase credentials from file: {firebase_key_path}")
            else:
                # Option 3: Use Application Default Credentials (for Google Cloud)
                try:
                    cred = credentials.ApplicationDefault()
                    logger.info(
                        "Using Firebase Application Default Credentials")
                except Exception as e:
                    logger.warning(
                        f"Firebase initialization skipped - no valid credentials found: {e}")
                    logger.warning(
                        "FCM notifications will not work. Set FIREBASE_CREDENTIALS or FIREBASE_KEY_PATH environment variable.")
                    return

        # Initialize Firebase with explicit project_id
        options = {}
        if project_id:
            options['projectId'] = project_id
            # Also set the environment variable as a fallback
            os.environ['GOOGLE_CLOUD_PROJECT'] = project_id
            os.environ['GCLOUD_PROJECT'] = project_id  # Alternative env var
            logger.info(f"Initializing Firebase with project ID: {project_id}")
        else:
            logger.error("No Firebase project ID found! FCM batch sending will fail.")
            logger.error("Please ensure your Firebase credentials include a 'project_id' field.")
            # Try to extract from environment as last resort
            env_project_id = os.environ.get('GOOGLE_CLOUD_PROJECT') or os.environ.get('GCLOUD_PROJECT')
            if env_project_id:
                options['projectId'] = env_project_id
                logger.info(f"Using project ID from environment: {env_project_id}")

        firebase_admin.initialize_app(cred, options)
        logger.info("Firebase Admin SDK initialized successfully")
        
        # Verify the app has project_id set
        app = firebase_admin.get_app()
        if hasattr(app, 'project_id') and app.project_id:
            logger.info(f"Firebase app initialized with project_id: {app.project_id}")
        else:
            logger.warning("Firebase app initialized but project_id not accessible - batch sending may fail")

    except Exception as e:
        logger.error(f"Failed to initialize Firebase Admin SDK: {e}")
        logger.warning(
            "FCM notifications will not work. Check Firebase configuration.")


async def send_fcm_message(token: str, title: str, body: str, extra_data: dict = None):
    """Send a data-only push notification using Firebase Cloud Messaging
    
    This sends a data-only message that:
    - Wakes up the app in the background to process data
    - Does not display a notification in the system tray
    - Allows the app to handle the notification display
    """
    try:
        # Check if Firebase is initialized
        try:
            firebase_admin.get_app()
        except ValueError:
            raise ValueError(
                "Firebase not initialized. FCM notifications unavailable.")

        # Prepare data payload with title and body
        fcm_data = {
            "title": title,
            "body": body,
            **(extra_data or {})
        }
        
        # Create data-only message (no notification payload)
        message = messaging.Message(
            # Data-only payload
            data=serialize_fcm_data(fcm_data),
            token=token,
            # Android configuration for background wake-up
            android=messaging.AndroidConfig(
                priority='high',  # Required for background wake-up
                # Set time-to-live (optional)
                ttl=datetime.timedelta(seconds=3600),
            ),
            # iOS configuration for background wake-up
            apns=messaging.APNSConfig(
                headers={
                    'apns-priority': '10',  # High priority
                    'apns-push-type': 'background',  # Background push type
                },
                payload=messaging.APNSPayload(
                    aps=messaging.Aps(
                        content_available=True,  # Required for background wake-up on iOS
                        # No alert, badge, or sound for data-only messages
                    )
                )
            )
        )

        # Send the message
        response = messaging.send(message)
        return {"success": True, "message_id": response}

    except messaging.UnregisteredError:
        raise ValueError("Device not registered")
    except messaging.SenderIdMismatchError:
        raise ValueError("Token sender ID mismatch")
    except messaging.QuotaExceededError:
        raise ValueError("FCM quota exceeded")
    except messaging.ThirdPartyAuthError:
        raise ValueError("FCM authentication error")
    except Exception as e:
        raise ValueError(f"Error sending FCM notification: {e}")


async def send_fcm_messages_batch(tokens: List[str], title: str, body: str, extra_data: dict = None):
    """Send multiple FCM notifications concurrently (send_all is deprecated)"""
    try:
        # Check if Firebase is initialized
        try:
            app = firebase_admin.get_app()
            # Log project info for debugging
            if hasattr(app, 'project_id'):
                logger.debug(f"FCM concurrent send using project_id: {app.project_id}")
        except ValueError:
            raise ValueError(
                "Firebase not initialized. FCM notifications unavailable.")

        # Process responses
        successful_responses = []
        failed_responses = []
        tokens_to_remove = []

        # Send messages concurrently using asyncio
        logger.debug(f"Sending {len(tokens)} FCM messages concurrently")
        
        # Create tasks for concurrent sending
        tasks = []
        for i, token in enumerate(tokens):
            task = send_fcm_message_with_index(token, title, body, extra_data, i)
            tasks.append(task)
        
        # Execute all tasks concurrently
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process results
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                error_message = str(result)
                
                # Check if token should be removed
                if ('Device not registered' in error_message or 
                    'not registered' in error_message.lower() or
                    'NOT_FOUND' in error_message or
                    'UNREGISTERED' in error_message):
                    tokens_to_remove.append(i)
                
                failed_responses.append({
                    "token": tokens[i][:10] + "...",
                    "error": error_message,
                    "error_code": "error"
                })
            elif isinstance(result, dict) and result.get('success'):
                successful_responses.append({
                    "message_id": result.get('message_id'),
                    "token_index": i
                })
            else:
                # Handle unexpected result format
                failed_responses.append({
                    "token": tokens[i][:10] + "...",
                    "error": "Unexpected response format",
                    "error_code": "unknown"
                })

        return successful_responses, failed_responses, tokens_to_remove

    except Exception as e:
        raise ValueError(f"Error sending FCM concurrent notifications: {e}")


async def send_fcm_message_with_index(token: str, title: str, body: str, extra_data: dict, index: int):
    """Helper function to send FCM message and preserve index for error tracking"""
    try:
        result = await send_fcm_message(token, title, body, extra_data)
        return result
    except Exception as e:
        # Re-raise the exception to be caught by gather()
        raise e

# Updated main notification functions


async def send_push_message_unified(token: str, title: str, message: str, extra_data: dict = None):
    """Unified function to send push notification via Expo or FCM based on token format"""
    token_type = detect_token_type(token)

    if token_type == TokenType.EXPO:
        if not validate_expo_token(token):
            raise ValueError(f"Invalid Expo token format: {token[:20]}...")
        return await send_push_message(token, title, message, extra_data)
    else:  # FCM
        if not validate_fcm_token(token):
            raise ValueError(f"Invalid FCM token format: {token[:20]}...")
        return await send_fcm_message(token, title, message, extra_data)


async def send_push_messages_batch_unified(tokens: list, token_records: list, title: str, message: str, extra_data: dict = None):
    """Unified batch sending that separates Expo and FCM tokens"""

    # Separate tokens by type and validate them
    expo_tokens = []
    expo_records = []
    fcm_tokens = []
    fcm_records = []
    invalid_records = []

    for i, token_record in enumerate(token_records):
        token = token_record.token
        token_type = detect_token_type(token)

        if token_type == TokenType.EXPO:
            if validate_expo_token(token):
                expo_tokens.append(token)
                expo_records.append(token_record)
            else:
                logger.warning(f"Invalid Expo token detected: {token[:20]}...")
                invalid_records.append(token_record)
        else:  # FCM
            if validate_fcm_token(token):
                fcm_tokens.append(token)
                fcm_records.append(token_record)
            else:
                logger.warning(f"Invalid FCM token detected: {token[:20]}...")
                invalid_records.append(token_record)

    all_tickets = []
    all_errors = []
    all_tokens_to_remove = []

    # Add invalid tokens to errors and mark for removal
    for record in invalid_records:
        all_errors.append({
            "token": record.token[:10] + "...",
            "error": "Invalid token format"
        })
        all_tokens_to_remove.append(record.id)

    # Send Expo notifications if any
    if expo_tokens:
        try:
            expo_tickets, expo_errors, expo_tokens_to_remove = await send_push_messages_batch(
                expo_tokens, expo_records, title, message, extra_data
            )
            all_tickets.extend(expo_tickets)
            all_errors.extend(expo_errors)
            all_tokens_to_remove.extend(expo_tokens_to_remove)
        except Exception as e:
            logger.error(f"Error sending Expo batch: {e}")
            # Log first 5 tokens for debugging
            logger.error(
                f"Expo tokens in failed batch: {[token[:20] + '...' for token in expo_tokens[:5]]}")
            # Add all expo tokens to errors
            for record in expo_records:
                all_errors.append({
                    "token": record.token[:10] + "...",
                    "error": f"Expo batch failed: {str(e)}"
                })

    # Send FCM notifications if any
    if fcm_tokens:
        try:
            # Use concurrent sending for FCM (since send_all is deprecated)
            fcm_tickets, fcm_errors, fcm_token_indices_to_remove = await send_fcm_messages_batch(
                fcm_tokens, title, message, extra_data
            )
            all_tickets.extend(fcm_tickets)
            all_errors.extend(fcm_errors)

            # Convert FCM token indices to record IDs
            for index in fcm_token_indices_to_remove:
                if index < len(fcm_records):
                    all_tokens_to_remove.append(fcm_records[index].id)

        except Exception as e:
            logger.error(f"Error sending FCM notifications: {e}")
            # Add all FCM tokens to errors if batch completely failed
            for record in fcm_records:
                all_errors.append({
                    "token": record.token[:10] + "...",
                    "error": f"FCM send failed: {str(e)}"
                })

    return all_tickets, all_errors, all_tokens_to_remove


# Keep your existing send_push_message function - just pass data through
async def send_push_message(token: str, title: str, message: str, extra_data: dict = None):
    """Send a push notification using Expo's push notification service"""
    try:
        message = PushMessage(
            to=token,
            title=title,
            body=message,
            data=extra_data or {},  # Mobile app will read priority, actions, etc. from here
        )
        response = PushClient().publish(message)
        return response
    except DeviceNotRegisteredError:
        raise ValueError("Device not registered")
    except PushServerError as e:
        raise ValueError(f"Push server error: {e}")
    except Exception as e:
        raise ValueError(f"Error sending push notification: {e}")


async def send_push_messages_batch(tokens: list, token_records: list, title: str, message: str, extra_data: dict = None):
    """Send multiple push notifications in a single batch using Expo's push notification service"""
    try:
        # Create batch of messages - tokens should already be validated by caller
        messages = []
        for token in tokens:
            messages.append(PushMessage(
                to=token,
                title=title,
                body=message,
                data=extra_data or {},
            ))

        # Send batch
        client = PushClient()
        responses = client.publish_multiple(messages)

        # Process responses
        tickets = []
        errors = []
        tokens_to_remove = []

        # Handle both list and single response cases
        if not isinstance(responses, list):
            responses = [responses]

        for i, response in enumerate(responses):
            if i >= len(token_records):
                # Safety check - more responses than expected
                break

            token_record = token_records[i]

            # Check if response indicates an error
            # Expo responses can be dict-like or have attributes
            if isinstance(response, dict):
                status = response.get('status')
                if status == 'error':
                    details = response.get('details', {})
                    message_text = response.get('message', 'Unknown error')

                    if details.get('error') == 'DeviceNotRegistered':
                        tokens_to_remove.append(token_record.id)

                    errors.append({
                        "token": token_record.token[:10] + "...",
                        "error": message_text
                    })
                else:
                    # Successful response
                    tickets.append(response)
            elif hasattr(response, 'status'):
                # Object-like response
                if response.status == 'error':
                    error_details = getattr(response, 'details', {})
                    error_message = getattr(
                        response, 'message', 'Unknown error')

                    # Check if it's a device not registered error
                    if (isinstance(error_details, dict) and
                            error_details.get('error') == 'DeviceNotRegistered'):
                        tokens_to_remove.append(token_record.id)

                    errors.append({
                        "token": token_record.token[:10] + "...",
                        "error": error_message
                    })
                else:
                    # Successful response
                    tickets.append(response)
            else:
                # Assume successful if we can't determine status
                tickets.append(response)

        return tickets, errors, tokens_to_remove

    except DeviceNotRegisteredError:
        raise ValueError("Device not registered")
    except PushServerError as e:
        raise ValueError(f"Push server error: {e}")
    except Exception as e:
        raise ValueError(f"Error sending batch push notifications: {e}")


def validate_expo_token(token: str) -> bool:
    """Validate if a token is a valid Expo push token format"""
    if not token or not isinstance(token, str):
        return False

    # Reject JWT tokens (common mistake)
    if token.startswith("eyJ") and len(token) > 200:
        return False

    # Standard Expo token format
    if token.startswith("ExponentPushToken[") and token.endswith("]"):
        # Extract the inner token and check if it's not empty
        inner_token = token[18:-1]  # Remove "ExponentPushToken[" and "]"
        return len(inner_token) > 10  # Should have some content

    # Alternative Expo token format
    if token.startswith("expo-"):
        return len(token) > 10

    return False


def validate_fcm_token(token: str) -> bool:
    """Validate if a token is a valid FCM push token format"""
    if not token or not isinstance(token, str):
        return False

    # Reject JWT tokens (common mistake)
    if token.startswith("eyJ") and len(token) > 200:
        return False

    # FCM tokens are typically longer and have a specific format
    if re.match(r'^[a-zA-Z0-9_-]+:[a-zA-Z0-9_-]+$', token) and len(token) > 100:
        return True

    return False
