from fastapi import Depends, HTTPException, Security, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from datetime import datetime, timezone, timedelta
import jwt
from typing import Dict, Optional
import logging
from config import settings
from fastapi.security import APIKeyQuery


logger = logging.getLogger(__name__)

security = HTTPBearer()

# Create query parameter security scheme
api_key_query = APIKeyQuery(name="token", auto_error=True)


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
    def __init__(self, secret_key: str = settings.SECRET_KEY):
        self.secret_key = secret_key
        self.algorithm = settings.ALGORITHM

    async def __call__(self, token: str = Security(api_key_query)) -> Dict:
        """Make the class callable as a dependency"""
        return await self.verify_token(token)

    async def verify_token(self, token: str) -> Dict:
        """Verify a raw token string"""
        try:
            payload = jwt.decode(
                token,
                self.secret_key,
                algorithms=[self.algorithm]
            )

            # Check for all required fields
            required_fields = [
                "pilot_id", 
                "race_id", 
                "pilot_name",
                "exp",
                "race",
                "endpoints"
            ]
            
            if not all(k in payload for k in required_fields):
                raise HTTPException(
                    status_code=401,
                    detail="Invalid token payload structure"
                )

            # Validate nested structures
            race_fields = ["name", "date", "timezone", "location", "end_date"]
            if not all(k in payload["race"] for k in race_fields):
                raise HTTPException(
                    status_code=401,
                    detail="Invalid race data structure in token"
                )

            endpoint_fields = ["live", "upload"]
            if not all(k in payload["endpoints"] for k in endpoint_fields):
                raise HTTPException(
                    status_code=401,
                    detail="Invalid endpoints structure in token"
                )

            return payload
            
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

# Create dependency
verify_tracking_token = TokenVerifier()