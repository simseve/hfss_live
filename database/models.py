from sqlalchemy import Column, String, Float, DateTime, MetaData, CHAR, BigInteger, Index
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