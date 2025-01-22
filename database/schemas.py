from datetime import datetime, timezone
from typing import Optional, Literal, Dict, Any
from pydantic import BaseModel, Field

# Base schemas with common fields
class TrackPointBase(BaseModel):
    flight_id: str = Field(..., max_length=100)
    lat: float
    lon: float
    elevation: Optional[float] = None
    speed: Optional[float] = None

# Input schemas (for creating new points)
class LiveTrackPointCreate(TrackPointBase):
    datetime: datetime

class UploadedTrackPointCreate(TrackPointBase):
    datetime: datetime

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
    assignment_id: str
    type: Literal['live', 'upload']

class FlightCreate(FlightBase):
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    total_points: Optional[int] = None
    metadata: Optional[Dict[str, Any]] = None

class FlightResponse(FlightBase):
    id: int
    created_at: datetime
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    total_points: Optional[int] = None
    metadata: Optional[Dict[str, Any]] = None

    class Config:
        from_attributes = True