from sqlalchemy import Column, String, Float, DateTime, MetaData, CHAR, BigInteger, Index, Integer, JSON, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
import uuid

metadata = MetaData()
Base = declarative_base(metadata=metadata)



class Flight(Base):
    __tablename__ = 'flights'
    
    id = Column(UUID(as_uuid=True), primary_key=True, nullable=False, default=uuid.uuid4)
    flight_id = Column(String, nullable=False)
    race_id = Column(String, nullable=False)
    pilot_id = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)
    source = Column(String, nullable=False)  # 'live' or 'upload'
    
    # Metadata fields for uploaded flights
    start_time = Column(DateTime(timezone=True))
    end_time = Column(DateTime(timezone=True))
    total_points = Column(Integer)
    flight_metadata = Column(JSON)

    live_track_points = relationship("LiveTrackPoint", backref="flight")
    uploaded_track_points = relationship("UploadedTrackPoint", backref="flight")
    
    __table_args__ = (
        Index('idx_flight_ids', 'race_id', 'pilot_id'),
        Index('uq_flight_id_source', 'flight_id', 'source', unique=True),
    )
    
    def __repr__(self):
        return f"<Flight(flight_id={self.flight_id}, source={self.source})>"
    
    
class LiveTrackPoint(Base):
    __tablename__ = 'live_track_points'
    
    datetime = Column(DateTime(timezone=True), primary_key=True, nullable=False)
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    flight_uuid = Column(UUID(as_uuid=True), ForeignKey('flights.id'), nullable=False)  # Changed from flight_id
    flight_id = Column(String, nullable=False)
    lat = Column(Float(precision=53), nullable=False)
    lon = Column(Float(precision=53), nullable=False)
    elevation = Column(Float(precision=53))
    speed = Column(Float(precision=53))
    
    __table_args__ = (
        Index('idx_live_track_points_datetime_flight', 'datetime', 'flight_uuid'),
    )
    
    def __repr__(self):
        return f"<LiveTrackPoint(id={self.id}, datetime={self.datetime}, flight_uuid={self.flight_uuid})>"


class UploadedTrackPoint(Base):
    __tablename__ = 'uploaded_track_points'
    
    datetime = Column(DateTime(timezone=True), primary_key=True, nullable=False)
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    flight_uuid = Column(UUID(as_uuid=True), ForeignKey('flights.id'), nullable=False)  # Changed from flight_id
    flight_id = Column(CHAR(100), nullable=False)
    lat = Column(Float(precision=53), nullable=False)
    lon = Column(Float(precision=53), nullable=False)
    elevation = Column(Float(precision=53))
    speed = Column(Float(precision=53))
    
    __table_args__ = (
        Index('idx_uploaded_track_points_datetime_flight', 'datetime', 'flight_uuid'),
    )
    
    def __repr__(self):
        return f"<UploadedTrackPoint(id={self.id}, datetime={self.datetime}, flight_uuid={self.flight_uuid})>"
