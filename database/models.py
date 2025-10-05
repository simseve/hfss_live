from sqlalchemy import Column, String, Float, DateTime, MetaData, CHAR, BigInteger, Index, Integer, JSON, ForeignKey, UniqueConstraint, text, Boolean
from sqlalchemy.dialects.postgresql import JSONB
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

    # Flight closure tracking
    closed_at = Column(DateTime(timezone=True), nullable=True)
    closed_by = Column(String, nullable=True)  # 'manual', 'inactivity', 'race_end', etc.

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
    barometric_altitude = Column(Float(precision=53), nullable=True)
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
    barometric_altitude = Column(Float(precision=53), nullable=True)
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


class ScoringTracks(Base):
    __tablename__ = 'scoring_tracks'

    # Composite primary key: (flight_uuid, date_time, lat, lon) together form the PK
    flight_uuid = Column(UUID(as_uuid=True), primary_key=True, nullable=False)
    date_time = Column(DateTime(timezone=True), primary_key=True, nullable=False)
    lat = Column(Float(precision=53), primary_key=True, nullable=False)
    lon = Column(Float(precision=53), primary_key=True, nullable=False)
    gps_alt = Column(Float(precision=53), nullable=False)

    # Optional fields for flight metrics
    time = Column(String, nullable=True)
    rounded_time = Column(DateTime(timezone=True), nullable=True)
    validity = Column(String, nullable=True)
    pressure_alt = Column(Float(precision=53), nullable=True)
    LAD = Column(Integer, nullable=True)
    LOD = Column(Integer, nullable=True)
    speed = Column(Float(precision=53), nullable=True)
    elevation = Column(Float(precision=53), nullable=True)
    altitude_diff = Column(Float(precision=53), nullable=True)
    altitude_diff_smooth = Column(Float(precision=53), nullable=True)
    speed_smooth = Column(Float(precision=53), nullable=True)
    takeoff_condition = Column(Boolean, nullable=True)
    in_flight = Column(Boolean, nullable=True)

    # Spatial geometry column
    geom = Column(Geometry('POINT', srid=4326))

    __table_args__ = (
        # Time-based indices
        Index('idx_scoring_tracks_datetime', 'date_time'),

        # Composite index for time + flight
        Index('idx_scoring_tracks_datetime_flight', 'date_time', 'flight_uuid'),

        # Add a unique constraint to prevent duplicate track points
        UniqueConstraint('flight_uuid', 'date_time', 'lat', 'lon',
                         name='scoring_tracks_unique_constraint'),

        # Spatial indices
        Index('idx_scoring_tracks_geom', 'geom', postgresql_using='gist'),

        # Functional index on transformed geometry for Web Mercator (EPSG:3857)
        Index('idx_scoring_tracks_transformed_geom',
              text('ST_Transform(geom, 3857)'), postgresql_using='gist'),

        # Table comment for TimescaleDB
        {'comment': 'hypertable:timescaledb:date_time'}
    )

    def __repr__(self):
        return f"<ScoringTrack(datetime={self.date_time}, lat={self.lat}, lon={self.lon})>"


# Flymaster table removed - data now goes directly to live_track_points
# Flymaster devices are tracked through the flights table with source='flymaster'


class DeviceRegistration(Base):
    __tablename__ = 'device_registrations'

    id = Column(UUID(as_uuid=True), primary_key=True,
                nullable=False, default=uuid.uuid4)
    serial_number = Column(String, nullable=False)
    device_type = Column(String, nullable=False, default='flymaster')  # flymaster, skytraxx, etc.
    pilot_token = Column(String, nullable=False)  # Raw JWT token
    race_uuid = Column(UUID(as_uuid=True), ForeignKey(
        'races.id', ondelete='CASCADE'), nullable=False)
    race_id = Column(String, nullable=False)  # Extracted for convenience
    pilot_id = Column(String, nullable=False)  # Extracted for convenience
    pilot_name = Column(String, nullable=False)  # Extracted for convenience
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False,
                        default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False,
                        default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))
    
    # Relationships
    race = relationship("Race", backref="device_registrations")
    
    __table_args__ = (
        Index('idx_device_serial', 'serial_number'),
        Index('idx_device_serial_active', 'serial_number', 'is_active'),
        Index('idx_device_race', 'race_uuid'),
        Index('idx_device_type', 'device_type'),
        # Ensure only one active serial number across all races
        Index('idx_device_unique_active_serial', 'serial_number',
              unique=True,
              postgresql_where=text('is_active = true')),
    )

    def __repr__(self):
        return f"<DeviceRegistration(serial={self.serial_number}, type={self.device_type}, pilot={self.pilot_name}, race={self.race_id})>"


class SentNotification(Base):
    __tablename__ = 'sent_notifications'

    id = Column(UUID(as_uuid=True), primary_key=True,
                nullable=False, default=uuid.uuid4)
    race_id = Column(String, nullable=False)
    title = Column(String, nullable=False)
    body = Column(String, nullable=False)
    # Additional data sent with notification
    data = Column(JSONB, nullable=True)

    # Statistics about the send
    total_recipients = Column(Integer, nullable=False, default=0)
    successful_sends = Column(Integer, nullable=False, default=0)
    failed_sends = Column(Integer, nullable=False, default=0)

    # Token distribution breakdown
    expo_recipients = Column(Integer, nullable=False, default=0)
    fcm_recipients = Column(Integer, nullable=False, default=0)

    # Send details
    sent_at = Column(DateTime(timezone=True), nullable=False,
                     default=lambda: datetime.now(timezone.utc))
    # JWT token subject for audit trail
    sender_token_subject = Column(String, nullable=True)

    # Optional error details (JSON array of errors)
    error_details = Column(JSONB, nullable=True)

    # Status flags
    batch_processing = Column(Boolean, nullable=False, default=True)

    __table_args__ = (
        Index('idx_sent_notifications_race_id', 'race_id'),
        Index('idx_sent_notifications_sent_at', 'sent_at'),
        Index('idx_sent_notifications_race_sent_at', 'race_id', 'sent_at'),
    )

    def __repr__(self):
        return f"<SentNotification(id={self.id}, race_id={self.race_id}, title={self.title[:30]}...)>"
