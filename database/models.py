from sqlalchemy import Column, String, Float, DateTime, MetaData, CHAR, BigInteger, Index, Integer, JSON, ForeignKey, UniqueConstraint, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
from geoalchemy2 import Geometry
import uuid
from datetime import datetime, timezone
metadata = MetaData()
Base = declarative_base(metadata=metadata)


class Race(Base):
    __tablename__ = 'races'

    id = Column(UUID(as_uuid=True), primary_key=True,
                nullable=False, default=uuid.uuid4)
    race_id = Column(String, nullable=False, unique=True)
    name = Column(String, nullable=False)
    date = Column(DateTime(timezone=True), nullable=False)
    end_date = Column(DateTime(timezone=True), nullable=False)
    timezone = Column(String, nullable=False)
    location = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False,
                        default=lambda: datetime.now(timezone.utc))

    # Relationship with flights

    flights = relationship("Flight", back_populates="race",
                           cascade="all, delete-orphan")

    __table_args__ = (
        Index('idx_race_id', 'race_id'),
    )

    def __repr__(self):
        return f"<Race(race_id={self.race_id}, name={self.name})>"


class Flight(Base):
    __tablename__ = 'flights'

    id = Column(UUID(as_uuid=True), primary_key=True,
                nullable=False, default=uuid.uuid4)
    flight_id = Column(String, nullable=False)
    race_uuid = Column(UUID(as_uuid=True), ForeignKey(
        'races.id', ondelete='CASCADE'), nullable=False)
    race_id = Column(String, nullable=False)
    pilot_id = Column(String, nullable=False)
    pilot_name = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False,
                        default=lambda: datetime.now(timezone.utc))
    source = Column(String, nullable=False)  # 'live' or 'upload'

    # Tracking state
    first_fix = Column(JSON, nullable=True)  # {lat, lon, elevation, datetime}
    last_fix = Column(JSON, nullable=True)   # {lat, lon, elevation, datetime}
    total_points = Column(Integer, default=0)

    # Flight state
    # {state, confidence, avg_speed, max_speed, altitude_change, last_updated}
    flight_state = Column(JSON, nullable=True)

    # Relationships
    race = relationship("Race", back_populates="flights")
    live_track_points = relationship(
        "LiveTrackPoint", backref="flight", cascade="all, delete-orphan")
    uploaded_track_points = relationship(
        "UploadedTrackPoint", backref="flight", cascade="all, delete-orphan")
    # Optional device ID for the flight
    device_id = Column(String, nullable=True)

    __table_args__ = (
        Index('idx_flight_ids', 'race_id', 'pilot_id'),
        Index('idx_flight_source', 'flight_id', 'source', unique=True),
    )

    def __repr__(self):
        return f"<Flight(flight_id={self.flight_id}, pilot={self.pilot_name}, source={self.source})>"


class LiveTrackPoint(Base):
    __tablename__ = 'live_track_points'

    datetime = Column(DateTime(timezone=True),
                      primary_key=True, nullable=False)
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    # Optional device ID for the flight
    device_id = Column(String, nullable=True)
    flight_uuid = Column(UUID(as_uuid=True), ForeignKey(
        'flights.id', ondelete='CASCADE'), nullable=False)  # Added ondelete='CASCADE'
    flight_id = Column(String, nullable=False)
    lat = Column(Float(precision=53), nullable=False)
    lon = Column(Float(precision=53), nullable=False)
    elevation = Column(Float(precision=53))
    # Add a geometry column for the point location (SRID 4326 = WGS84)
    geom = Column(Geometry('POINT', srid=4326))

    __table_args__ = (
        Index('idx_live_track_points_datetime_flight',
              'datetime', 'flight_uuid'),
        UniqueConstraint('flight_id', 'lat', 'lon', 'datetime',
                         name='live_track_points_unique_parent'),
        # Add a spatial index
        Index('idx_live_track_points_geom', 'geom', postgresql_using='gist'),
        # Add functional index on transformed geometry for Web Mercator (EPSG:3857)
        Index('idx_live_track_points_transformed_geom',
              text('ST_Transform(geom, 3857)'), postgresql_using='gist'),
    )

    def __repr__(self):
        return f"<LiveTrackPoint(id={self.id}, datetime={self.datetime}, flight_uuid={self.flight_uuid})>"


class UploadedTrackPoint(Base):
    __tablename__ = 'uploaded_track_points'

    datetime = Column(DateTime(timezone=True),
                      primary_key=True, nullable=False)
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    # Optional device ID for the flight
    device_id = Column(String, nullable=True)
    flight_uuid = Column(UUID(as_uuid=True), ForeignKey(
        'flights.id', ondelete='CASCADE'), nullable=False)
    flight_id = Column(CHAR(100), nullable=False)
    lat = Column(Float(precision=53), nullable=False)
    lon = Column(Float(precision=53), nullable=False)
    elevation = Column(Float(precision=53))
    # Add a geometry column for the point location (SRID 4326 = WGS84)
    geom = Column(Geometry('POINT', srid=4326))

    __table_args__ = (
        Index('idx_uploaded_track_points_datetime_flight',
              'datetime', 'flight_uuid'),
        UniqueConstraint('flight_id', 'lat', 'lon', 'datetime',
                         name='uploaded_track_points_unique_parent'),
        # Add a spatial index
        Index('idx_uploaded_track_points_geom',
              'geom', postgresql_using='gist'),
        # Add functional index on transformed geometry for Web Mercator (EPSG:3857)
        Index('idx_uploaded_track_points_transformed_geom',
              text('ST_Transform(geom, 3857)'), postgresql_using='gist'),
    )

    def __repr__(self):
        return f"<UploadedTrackPoint(id={self.id}, datetime={self.datetime}, flight_uuid={self.flight_uuid})>"


class NotificationTokenDB(Base):
    __tablename__ = 'notification_tokens'

    id = Column(UUID(as_uuid=True), primary_key=True,
                nullable=False, default=uuid.uuid4)
    token = Column(String, nullable=False)
    race_id = Column(String, nullable=False)
    device_id = Column(String, nullable=True)
    platform = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False,
                        default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index('idx_notification_tokens_race', 'race_id'),
        UniqueConstraint('token', 'race_id', name='unique_token_race'),
    )

    def __repr__(self):
        return f"<NotificationTokenDB(id={self.id}, token={self.token[:10]}..., race_id={self.race_id})>"
