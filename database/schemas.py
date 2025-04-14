from datetime import datetime, timezone
from typing import Optional, Literal, Dict, Any, List
from uuid import UUID
from pydantic import BaseModel, Field
from enum import Enum

class RaceBase(BaseModel):
    race_id: str
    name: str
    date: datetime
    end_date: datetime
    timezone: str
    location: str

class RaceCreate(RaceBase):
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class RaceResponse(RaceBase):
    id: UUID
    created_at: datetime

    class Config:
        from_attributes = True
        
        
# Base schemas with common fields
class TrackPointBase(BaseModel):
    flight_id: str  # Changed from flight_id
    flight_uuid: UUID
    lat: float
    lon: float
    elevation: Optional[float] = None


class LiveTrackPointCreate(TrackPointBase):
    datetime: datetime

class UploadedTrackPointCreate(TrackPointBase):
    datetime: datetime

class LiveTrackingRequest(BaseModel):
    track_points: List[Dict[str, Any]]  # Raw track points data
    flight_id: Optional[str] = None
    device_id: Optional[str] = None

    class Config:
        json_schema_extra = {
            "example": {
                "flight_id": "flight_123",
                "track_points": [
                    {
                        "lat": 45.5231,
                        "lon": -122.6765,
                        "elevation": 1200.5,
                        "datetime": "2024-03-20T14:23:45.123Z"
                    },
                    {
                        "lat": 45.5233,
                        "lon": -122.6768,
                        "elevation": 1205.0,
                        "datetime": "2024-03-20T14:23:46.123Z"
                    }
                ]
            }
        }
        from_attributes = True
        
# Output schemas (for returning data)
class LiveTrackPointResponse(TrackPointBase):
    id: int
    datetime: datetime

    class Config:
        from_attributes = True

class UploadedTrackPointResponse(TrackPointBase):
    id: int
    datetime: datetime

    class Config:
        from_attributes = True
        
class FlightBase(BaseModel):
    flight_id: str = Field(..., max_length=100)
    race_id: str
    pilot_id: str
    pilot_name: str
    source: Literal['live', 'upload']

class FlightCreate(FlightBase):
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    first_fix: Optional[Dict[str, Any]] = None
    last_fix: Optional[Dict[str, Any]] = None
    total_points: Optional[int] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    flight_metadata: Optional[Dict[str, Any]] = None

class TrackMetadata(BaseModel):
    duration: str  # Changed from Optional[float] to str to accept "00:00:04.521" format
    distance: Optional[float] = None
    avg_speed: Optional[float] = None
    max_speed: Optional[float] = None
    max_altitude: Optional[float] = None
    total_points: Optional[int] = None

class TrackUploadRequest(BaseModel):
    pilot_id: Optional[str] = None
    race_id: Optional[str] = None
    flight_id: str = Field(..., max_length=100)
    device_id: Optional[str] = None
    track_points: List[Dict[str, Any]]

    class Config:
        json_schema_extra = {
            "example": {
                "pilot_id": "pilot123",
                "race_id": "race456",
                "flight_id": "flight_123",
                "track_points": [
                    {
                        "datetime": "2024-03-20T14:23:45.123Z",
                        "lat": 45.5231,
                        "lon": -122.6765,
                        "elevation": 1200.5
                    }
                ],
                "metadata": {
                    "duration": "00:00:04.521",
                    "distance": 50000,
                    "avg_speed": 45.5,
                    "max_speed": 65.3,
                    "max_altitude": 1500.0,
                    "total_points": 3600
                }
            }
        }
        
class FlightResponse(FlightBase):
    id: UUID
    race_uuid: UUID
    created_at: datetime
    first_fix: Optional[Dict[str, Any]]
    last_fix: Optional[Dict[str, Any]]
    total_points: Optional[int]
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    flight_metadata: Optional[Dict[str, Any]] = None
    race: RaceResponse


    class Config:
        from_attributes = True
        json_encoders = {
            datetime: lambda dt: dt.isoformat(),
            UUID: str
        }

    @classmethod
    def from_orm(cls, obj):
        # Ensure the metadata is a dict if it exists
        if hasattr(obj, 'flight_metadata') and obj.flight_metadata is not None:
            if isinstance(obj.flight_metadata, str):
                obj.flight_metadata = json.loads(obj.flight_metadata)
        return super().from_orm(obj)
        
class UpdatedLiveTrackingRequest(BaseModel):
    pilot_id: Optional[str] = None
    race_id: Optional[str] = None
    flight_id: str
    track_points: List[Dict[str, Any]]




class NotificationPriority(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ALERT = "alert"
    EMERGENCY = "emergency"

class NotificationCommand(BaseModel):
    type: str = Field("notification", description="Type of command, defaults to 'notification'")
    priority: NotificationPriority = Field(default=NotificationPriority.INFO, description="Priority level of the notification")
    message: str = Field(..., description="Content of the notification message")
    
    class Config:
        json_schema_extra = {
            "example": {
                "type": "notification",
                "priority": "warning",
                "message": "Weather conditions are deteriorating. Use caution."
            }
        }


# Database models - replace with your actual database solution
class NotificationToken(BaseModel):
    token: str
    raceId: str
    deviceId: Optional[str] = None
    platform: Optional[str] = None
    created_at: Optional[str] = None

# Request models
class SubscriptionRequest(BaseModel):
    token: str
    raceId: str
    deviceId: Optional[str] = None
    platform: Optional[str] = "android"  # Default to iOS

class UnsubscriptionRequest(BaseModel):
    token: str
    raceId: str

class NotificationRequest(BaseModel):
    raceId: str
    title: str
    body: str
    data: Optional[dict] = None