from sqlalchemy import Column, String, Float, DateTime, MetaData, CHAR, BigInteger, Index, Integer, JSON
from sqlalchemy.ext.declarative import declarative_base

metadata = MetaData()
Base = declarative_base(metadata=metadata)

class LiveTrackPoint(Base):
    __tablename__ = 'live_track_points'
    
    # Put datetime first in column order and primary key
    datetime = Column(DateTime(timezone=True), primary_key=True, nullable=False)
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    flight_id = Column(CHAR(100), nullable=False)
    lat = Column(Float(precision=53), nullable=False)
    lon = Column(Float(precision=53), nullable=False)
    elevation = Column(Float(precision=53))
    speed = Column(Float(precision=53))
    
    __table_args__ = (
        Index('idx_live_datetime_flight', 'datetime', 'flight_id'),
    )
    
    def __repr__(self):
        return f"<LiveTrackPoint(id={self.id}, datetime={self.datetime}, flight_id={self.flight_id})>"

class UploadedTrackPoint(Base):
    __tablename__ = 'uploaded_track_points'
    
    # Put datetime first in column order and primary key
    datetime = Column(DateTime(timezone=True), primary_key=True, nullable=False)
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    flight_id = Column(CHAR(100), nullable=False)
    lat = Column(Float(precision=53), nullable=False)
    lon = Column(Float(precision=53), nullable=False)
    elevation = Column(Float(precision=53))
    speed = Column(Float(precision=53))
    
    __table_args__ = (
        Index('idx_uploaded_datetime_flight', 'datetime', 'flight_id'),
    )
    
    def __repr__(self):
        return f"<UploadedTrackPoint(id={self.id}, datetime={self.datetime}, flight_id={self.flight_id})>"
    
class Flight(Base):
    __tablename__ = 'flights'
    
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    flight_id = Column(CHAR(100), unique=True, nullable=False)
    race_id = Column(String, nullable=False)
    pilot_id = Column(String, nullable=False)
    assignment_id = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)
    type = Column(String, nullable=False)  # 'live' or 'upload'
    
    # Metadata fields for uploaded flights
    start_time = Column(DateTime(timezone=True))
    end_time = Column(DateTime(timezone=True))
    total_points = Column(Integer)
    flight_metadata = Column(JSON)
    
    __table_args__ = (
        Index('idx_flight_ids', 'race_id', 'pilot_id'),
        Index('idx_flight_id', 'flight_id'),
    )
    
    def __repr__(self):
        return f"<Flight(flight_id={self.flight_id}, type={self.type})>"