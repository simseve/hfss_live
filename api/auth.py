from fastapi import Depends, HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from datetime import datetime, timezone, timedelta
import jwt
from typing import Dict
import logging

logger = logging.getLogger(__name__)

security = HTTPBearer()


def create_tracking_token(
    pilot_id: str,
    race_id: str,
    secret_key: str = "your-secret-key",  # Get from environment variables in production
    expiration_minutes: int = 60
) -> str:
    """
    Create a JWT token for tracking authentication
    """
    expiration = datetime.now(timezone.utc) + timedelta(minutes=expiration_minutes)
    
    payload = {
        "pilot_id": pilot_id,
        "race_id": race_id,
        "exp": expiration.timestamp()
    }
    
    token = jwt.encode(
        payload,
        secret_key,
        algorithm="HS256"
    )
    
    return token



class TokenVerifier:
    def __init__(self, secret_key: str = "your-secret-key"):  # Get from environment variables in production
        self.secret_key = secret_key

    async def __call__(
        self, 
        credentials: HTTPAuthorizationCredentials = Security(security)
    ) -> Dict:
        """
        Verify JWT token and return decoded payload
        
        Expected token payload structure:
        {
            "pilot_id": "123",
            "race_id": "456",
            "exp": 1234567890  # Expiration timestamp
        }
        """
        try:
            token = credentials.credentials
            payload = jwt.decode(
                token,
                self.secret_key,
                algorithms=["HS256"]
            )

            # Verify required claims
            if not all(k in payload for k in ["pilot_id", "race_id"]):
                raise HTTPException(
                    status_code=401,
                    detail="Invalid token payload structure"
                )

            return {
                "pilot_id": payload["pilot_id"],
                "race_id": payload["race_id"]
            }

        except jwt.ExpiredSignatureError:
            raise HTTPException(
                status_code=401,
                detail="Token has expired"
            )
        except jwt.InvalidTokenError as e:
            logger.error(f"Token validation error: {str(e)}")
            raise HTTPException(
                status_code=401,
                detail="Invalid token"
            )
        except Exception as e:
            logger.error(f"Unexpected error during token verification: {str(e)}")
            raise HTTPException(
                status_code=401,
                detail="Token verification failed"
            )

# Create dependency
verify_tracking_token = TokenVerifier()