import json
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
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc))


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
    barometric_altitude: Optional[float] = None


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
                "device_id": "device_456",
                "track_points": [
                    {
                        "lat": 45.5231,
                        "lon": -122.6765,
                        "elevation": 1200.5,
                        "barometric_altitude": 1185.2,
                        "datetime": "2024-03-20T14:23:45.123Z"
                    },
                    {
                        "lat": 45.5233,
                        "lon": -122.6768,
                        "elevation": 1205.0,
                        "barometric_altitude": 1190.1,
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
    source: Literal['live', 'upload', 'flymaster']


class FlightCreate(FlightBase):
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc))
    first_fix: Optional[Dict[str, Any]] = None
    last_fix: Optional[Dict[str, Any]] = None
    total_points: Optional[int] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    flight_metadata: Optional[Dict[str, Any]] = None


class TrackMetadata(BaseModel):
    # Changed from Optional[float] to str to accept "00:00:04.521" format
    duration: str
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
                "device_id": "device_456",
                "track_points": [
                    {
                        "datetime": "2024-03-20T14:23:45.123Z",
                        "lat": 45.5231,
                        "lon": -122.6765,
                        "elevation": 1200.5,
                        "barometric_altitude": 1185.2
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


class FlightState(BaseModel):
    state: str = Field(..., description="Current flight state (flying, walking, stationary, launch, landing, unknown)")
    confidence: str = Field(
        ..., description="Confidence level of the state detection (high, medium, low)")
    avg_speed: Optional[float] = Field(
        None, description="Average speed in m/s")
    max_speed: Optional[float] = Field(
        None, description="Maximum speed in m/s")
    altitude_change: Optional[float] = Field(
        None, description="Recent altitude change in meters")
    last_updated: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc))


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
    flight_state: Optional[FlightState] = None
    race: RaceResponse

    model_config = {
        "from_attributes": True,
        "json_encoders": {
            datetime: lambda dt: dt.isoformat(),
            UUID: str
        }
    }

    @classmethod
    def model_validate_from_orm(cls, obj):
        # Ensure the metadata is a dict if it exists
        if hasattr(obj, 'flight_metadata') and obj.flight_metadata is not None:
            if isinstance(obj.flight_metadata, str):
                obj.flight_metadata = json.loads(obj.flight_metadata)
        return cls.model_validate(obj)
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
    type: str = Field(
        "notification", description="Type of command, defaults to 'notification'")
    priority: NotificationPriority = Field(
        default=NotificationPriority.INFO, description="Priority level of the notification")
    message: str = Field(...,
                         description="Content of the notification message")

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


class NotificationAction(BaseModel):
    label: str
    type: str  # open_url, call_phone, show_map, emergency_contact, download_file
    url: Optional[str] = None
    phone: Optional[str] = None
    coordinates: Optional[str] = None  # "lat,lng" format
    file_url: Optional[str] = None


class NotificationRequest(BaseModel):
    raceId: str
    title: str
    body: str
    data: Optional[Dict[str, Any]] = {}


class SentNotificationResponse(BaseModel):
    id: str
    race_id: str
    title: str
    body: str
    data: Optional[Dict[str, Any]] = None
    total_recipients: int
    successful_sends: int
    failed_sends: int
    expo_recipients: int
    fcm_recipients: int
    sent_at: str
    sender_token_subject: Optional[str] = None
    batch_processing: bool

    class Config:
        from_attributes = True


# ScoringTracks schemas
class ScoringTrackBase(BaseModel):
    date_time: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp of the track point (UTC)"
    )
    lat: float = Field(..., description="Latitude coordinate")
    lon: float = Field(..., description="Longitude coordinate")
    gps_alt: float = Field(..., description="GPS altitude in meters")
    flight_uuid: Optional[UUID] = Field(
        None,
        description="UUID of the flight associated with this track point"
    )

    # Optional fields
    time: Optional[str] = Field(None, description="Time string representation")
    rounded_time: Optional[datetime] = Field(
        None, description="Rounded time for analysis")
    validity: Optional[str] = Field(
        None, description="Validity status of the track point")
    pressure_alt: Optional[float] = Field(
        None, description="Pressure altitude in meters")
    LAD: Optional[int] = Field(None, description="LAD value")
    LOD: Optional[int] = Field(None, description="LOD value")
    speed: Optional[float] = Field(None, description="Speed in m/s")
    elevation: Optional[float] = Field(
        None, description="Ground elevation in meters")
    altitude_diff: Optional[float] = Field(
        None, description="Difference between GPS altitude and ground elevation")
    altitude_diff_smooth: Optional[float] = Field(
        None, description="Smoothed altitude difference")
    speed_smooth: Optional[float] = Field(
        None, description="Smoothed speed value")
    takeoff_condition: Optional[bool] = Field(
        None, description="Flag indicating takeoff conditions")
    in_flight: Optional[bool] = Field(
        None, description="Flag indicating if point is in flight")


class ScoringTrackBatchCreate(BaseModel):
    """Schema for creating multiple scoring track points in a single request"""
    tracks: List[ScoringTrackBase] = Field(
        ...,
        description="List of track points to insert",
        min_items=1
    )
    flight_uuid: Optional[UUID] = Field(
        None,
        description="Optional flight UUID for migration. If not provided, a new UUID will be generated"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "tracks": [
                    {
                        "lat": 45.5231,
                        "lon": -122.6765,
                        "gps_alt": 1200.5,
                        "time": "2024-05-16T14:23:45.123Z",
                        "speed": 12.5
                    },
                    {
                        "lat": 45.5233,
                        "lon": -122.6768,
                        "gps_alt": 1205.0,
                        "time": "2024-05-16T14:23:46.123Z",
                        "speed": 13.2
                    }
                ]
            }
        }


class ScoringTrackBatchResponse(BaseModel):
    """Schema for returning information about a batch insertion"""
    flight_uuid: UUID = Field(...,
                              description="UUID of the flight the points were added to")
    points_added: int = Field(...,
                              description="Number of track points successfully added")
    points_skipped: int = Field(0,
                                description="Number of duplicate track points that were skipped")
    queued: bool = Field(False,
                        description="Whether points were queued for background processing")

    model_config = {
        "from_attributes": True
    }


class GeoJSONTrackPoint(BaseModel):
    """Schema for a single track point with optional GeoJSON formatting"""
    date_time: datetime = Field(...,
                                description="Timestamp of the track point (UTC)")
    lat: float = Field(..., description="Latitude coordinate")
    lon: float = Field(..., description="Longitude coordinate")
    gps_alt: float = Field(..., description="GPS altitude in meters")

    # Optional fields
    time: Optional[str] = Field(None, description="Time string representation")
    speed: Optional[float] = Field(None, description="Speed in m/s")
    elevation: Optional[float] = Field(
        None, description="Ground elevation in meters")
    altitude_diff: Optional[float] = Field(
        None, description="Difference between GPS altitude and ground elevation")
    pressure_alt: Optional[float] = Field(
        None, description="Pressure altitude in meters")

    # Additional optional fields
    speed_smooth: Optional[float] = Field(
        None, description="Smoothed speed value")
    altitude_diff_smooth: Optional[float] = Field(
        None, description="Smoothed altitude difference")
    takeoff_condition: Optional[bool] = Field(
        None, description="Flag indicating takeoff conditions")
    in_flight: Optional[bool] = Field(
        None, description="Flag indicating if point is in flight")

    model_config = {
        "from_attributes": True
    }


class FlightPointsResponse(BaseModel):
    """Schema for returning all track points of a flight"""
    flight_uuid: UUID = Field(..., description="UUID of the flight")
    points_count: int = Field(...,
                              description="Number of track points in the response")
    track_points: List[GeoJSONTrackPoint] = Field(
        ..., description="List of track points")

    model_config = {
        "from_attributes": True,
        "json_encoders": {
            datetime: lambda dt: dt.isoformat(),
            UUID: str
        }
    }


class GeoJSONFeatureCollection(BaseModel):
    """Schema for returning track points as a GeoJSON FeatureCollection"""
    type: str = Field(default="FeatureCollection", description="GeoJSON type")
    features: List[Dict[str, Any]] = Field(..., description="GeoJSON features")
    properties: Dict[str, Any] = Field(
        default_factory=dict, description="Additional properties")

    model_config = {
        "from_attributes": True
    }


class FlightDeleteResponse(BaseModel):
    """Schema for returning information about deleted flight tracks"""
    flight_uuid: str = Field(...,
                             description="UUID of the flight whose tracks were deleted")
    points_deleted: int = Field(...,
                                description="Number of track points successfully deleted")

    model_config = {
        "from_attributes": True
    }


class MVTRequest(BaseModel):
    """Schema for requesting Map Vector Tiles with a list of flight UUIDs"""
    flight_uuids: List[UUID] = Field(...,
                                     description="List of flight UUIDs to include in the MVT")

    model_config = {
        "json_schema_extra": {
            "example": {
                "flight_uuids": [
                    "3d96fa37-37bc-4340-a6a0-6fe3c74279ed",
                    "211971e5-7ab5-475f-b763-480ce0533d90"
                ]
            }
        }
    }


# Flymaster schemas removed - data now goes directly to live_track_points
# Flymaster devices are tracked through the flights table with source='flymaster'


class TrackingTokenRequest(BaseModel):
    """Schema for generating a tracking token"""
    pilot_id: int = Field(..., description="Pilot ID from the race")
    race_id: str = Field(..., description="Race ID")
    pilot_name: str = Field(..., description="Full name of the pilot")
    race_name: str = Field(..., description="Name of the race")
    race_date: str = Field(..., description="Race start date in YYYY-MM-DD format")
    race_end_date: str = Field(..., description="Race end date in YYYY-MM-DD format")
    race_timezone: str = Field(..., description="Race timezone (e.g., 'Europe/Rome')")
    race_location: str = Field(..., description="Race location")

    model_config = {
        "json_schema_extra": {
            "example": {
                "pilot_id": 1,
                "race_id": "68aadbb85da525060edaaebf",
                "pilot_name": "Simone Severini",
                "race_name": "HFSS App Testing",
                "race_date": "2025-01-01",
                "race_end_date": "2026-12-01",
                "race_timezone": "Europe/Rome",
                "race_location": "Laveno"
            }
        }
    }


class TrackingTokenResponse(BaseModel):
    """Schema for tracking token response"""
    token: str = Field(..., description="JWT tracking token")
    expires_at: datetime = Field(..., description="Token expiration timestamp")
    endpoints: Dict[str, str] = Field(..., description="Available endpoints for this token")

    model_config = {
        "json_schema_extra": {
            "example": {
                "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                "expires_at": "2026-12-01T23:59:59Z",
                "endpoints": {
                    "live": "/tracking/live",
                    "upload": "/tracking/upload"
                }
            }
        }
    }
