#!/usr/bin/env python3
"""
Flight separation logic for continuous tracking devices (Flymaster, TK905B)
"""

from datetime import datetime, timedelta, timezone, time
from typing import Optional, Dict
from zoneinfo import ZoneInfo
import logging

logger = logging.getLogger(__name__)

class FlightSeparator:
    """
    Determines when to create a new flight for continuous tracking devices
    """
    
    # Configuration
    DEFAULT_INACTIVITY_HOURS = 3  # Hours of inactivity before new flight
    MIN_SPEED_THRESHOLD_KMH = 5   # Below this speed considered stopped
    LANDING_DURATION_MINUTES = 10  # Minutes on ground to consider landed
    
    @staticmethod
    def should_create_new_flight(
        device_id: str,
        current_point: Dict,
        last_flight: Optional[Dict],
        race_timezone: str = "UTC"
    ) -> tuple[bool, str]:
        """
        Determine if a new flight should be created
        
        Args:
            device_id: Device identifier
            current_point: Current track point with datetime, lat, lon, elevation, speed
            last_flight: Last flight info with last_fix, created_at
            race_timezone: Race timezone for day boundary check
            
        Returns:
            (should_create_new, reason)
        """
        
        # If no previous flight, always create new
        if not last_flight:
            return True, "no_previous_flight"
        
        # Parse current point time
        current_time = current_point.get('datetime')
        if isinstance(current_time, str):
            current_time = datetime.fromisoformat(current_time.replace('Z', '+00:00'))
        elif not isinstance(current_time, datetime):
            current_time = datetime.now(timezone.utc)
        
        # Get last fix time from previous flight
        last_fix = last_flight.get('last_fix')
        if not last_fix:
            return True, "no_last_fix"
            
        last_fix_time = last_fix.get('datetime')
        if isinstance(last_fix_time, str):
            last_fix_time = datetime.fromisoformat(last_fix_time.replace('Z', '+00:00'))
        elif not isinstance(last_fix_time, datetime):
            # Fallback to flight creation time
            last_fix_time = last_flight.get('created_at')
            if not last_fix_time:
                return True, "invalid_last_fix_time"
        
        # Ensure times are timezone-aware
        if last_fix_time.tzinfo is None:
            last_fix_time = last_fix_time.replace(tzinfo=timezone.utc)
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=timezone.utc)
        
        # Check 1: New Day (in race timezone)
        try:
            tz = ZoneInfo(race_timezone)
        except:
            tz = timezone.utc
            
        last_local = last_fix_time.astimezone(tz)
        current_local = current_time.astimezone(tz)
        
        if last_local.date() != current_local.date():
            logger.info(f"New day detected for device {device_id}: {last_local.date()} -> {current_local.date()}")
            return True, "new_day"
        
        # Check 2: Inactivity Period (3+ hours)
        time_gap = current_time - last_fix_time
        if time_gap > timedelta(hours=FlightSeparator.DEFAULT_INACTIVITY_HOURS):
            hours_inactive = time_gap.total_seconds() / 3600
            logger.info(f"Long inactivity detected for device {device_id}: {hours_inactive:.1f} hours")
            return True, f"inactive_{int(hours_inactive)}h"
        
        # Check 3: Landing Detection (optional, advanced)
        # This would require analyzing the flight state from last_flight
        flight_state = last_flight.get('flight_state')
        if flight_state and isinstance(flight_state, dict):
            state = flight_state.get('state')
            if state == 'landed':
                # Check if landed for sufficient time
                landed_at = flight_state.get('landed_at')
                if landed_at:
                    if isinstance(landed_at, str):
                        landed_at = datetime.fromisoformat(landed_at.replace('Z', '+00:00'))
                    if landed_at.tzinfo is None:
                        landed_at = landed_at.replace(tzinfo=timezone.utc)
                    
                    landed_duration = current_time - landed_at
                    if landed_duration > timedelta(minutes=FlightSeparator.LANDING_DURATION_MINUTES):
                        logger.info(f"Flight ended after landing for device {device_id}")
                        return True, "landed"
        
        # Default: Continue with existing flight
        return False, "continue_existing"
    
    @staticmethod
    def detect_landing(
        recent_points: list[Dict],
        min_points: int = 5
    ) -> tuple[bool, Optional[datetime]]:
        """
        Detect if the device has landed based on recent track points
        
        Args:
            recent_points: List of recent track points (newest first)
            min_points: Minimum points needed for detection
            
        Returns:
            (is_landed, landing_time)
        """
        
        if len(recent_points) < min_points:
            return False, None
        
        # Check if all recent points are low speed and low altitude change
        speeds = []
        altitudes = []
        
        for point in recent_points[:min_points]:
            # Calculate speed if not provided
            speed = point.get('speed_kmh')
            if speed is not None:
                speeds.append(speed)
            
            altitude = point.get('elevation')
            if altitude is not None:
                altitudes.append(altitude)
        
        # Check speed criteria
        if speeds:
            avg_speed = sum(speeds) / len(speeds)
            if avg_speed < FlightSeparator.MIN_SPEED_THRESHOLD_KMH:
                # Check altitude variation
                if altitudes and len(altitudes) > 1:
                    altitude_variation = max(altitudes) - min(altitudes)
                    if altitude_variation < 10:  # Less than 10m altitude change
                        # Landed!
                        landing_time = recent_points[0].get('datetime')
                        if isinstance(landing_time, str):
                            landing_time = datetime.fromisoformat(landing_time.replace('Z', '+00:00'))
                        return True, landing_time
        
        return False, None
    
    @staticmethod
    def get_flight_id_suffix(reason: str) -> str:
        """
        Generate a suffix for the flight_id based on separation reason
        
        Args:
            reason: Reason for flight separation
            
        Returns:
            Suffix string for flight_id
        """
        
        # Generate timestamp-based suffix
        now = datetime.now(timezone.utc)
        
        if reason == "new_day":
            return now.strftime("%Y%m%d")
        elif reason.startswith("inactive"):
            return now.strftime("%H%M")
        elif reason == "landed":
            return f"L{now.strftime('%H%M')}"
        else:
            return now.strftime("%Y%m%d%H%M")