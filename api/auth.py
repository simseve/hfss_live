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


class TokenVerifier:
    def __init__(self):
        self.secret_key = settings.SECRET_KEY
        self.algorithm = "HS256"

    async def __call__(self, token: str) -> Dict:
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

            # Return a validated payload with explicit field structure
            return {
                "pilot_id": payload["pilot_id"],
                "race_id": payload["race_id"],
                "pilot_name": payload["pilot_name"],
                "exp": payload["exp"],
                "race": {
                    "name": payload["race"]["name"],
                    "date": payload["race"]["date"],
                    "timezone": payload["race"]["timezone"],
                    "location": payload["race"]["location"],
                    "end_date": payload["race"]["end_date"]
                },
                "endpoints": {
                    "live": payload["endpoints"]["live"],
                    "upload": payload["endpoints"]["upload"]
                }
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

# Create dependency
verify_tracking_token = TokenVerifier()