"""
Base protocol handler for GPS trackers
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class BaseProtocolHandler(ABC):
    """Base class for GPS tracker protocol handlers"""
    
    def __init__(self, device_id: str = None):
        self.device_id = device_id
        self.last_message_time = None
        self.message_count = 0
    
    @abstractmethod
    def parse_message(self, data: str) -> Optional[Dict[str, Any]]:
        """Parse a raw message from the device"""
        pass
    
    @abstractmethod  
    def create_response(self, parsed_data: Dict[str, Any], success: bool = True) -> str:
        """Create a response message for the device"""
        pass
    
    @abstractmethod
    def get_protocol_name(self) -> str:
        """Get the name of this protocol"""
        pass
    
    @abstractmethod
    def can_handle(self, data: str) -> bool:
        """Check if this handler can process the given message"""
        pass
    
    def validate_coordinates(self, lat: float, lon: float) -> bool:
        """Validate GPS coordinates"""
        return -90 <= lat <= 90 and -180 <= lon <= 180
    
    def parse_nmea_coordinate(self, coord_str: str, is_longitude: bool = False) -> float:
        """
        Parse NMEA format coordinate (DDMM.MMMM or DDDMM.MMMM)
        Args:
            coord_str: Coordinate string in NMEA format
            is_longitude: True if parsing longitude (3 digits for degrees)
        Returns:
            Decimal degrees
        """
        try:
            if is_longitude:
                # Longitude: DDDMM.MMMM
                deg_digits = 3 if len(coord_str) > 5 else 2
            else:
                # Latitude: DDMM.MMMM
                deg_digits = 2
                
            degrees = float(coord_str[:deg_digits])
            minutes = float(coord_str[deg_digits:])
            return degrees + (minutes / 60.0)
        except (ValueError, IndexError):
            raise ValueError(f"Invalid NMEA coordinate: {coord_str}")
    
    def process_batch(self, points: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Process a batch of GPS points
        Override this for custom batch processing
        """
        processed = []
        for point in points:
            if self.validate_point(point):
                processed.append(point)
        return processed
    
    def validate_point(self, point: Dict[str, Any]) -> bool:
        """Validate a single GPS point"""
        # Check required fields
        required = ['latitude', 'longitude', 'timestamp']
        if not all(field in point for field in required):
            return False
            
        # Validate coordinates
        if not self.validate_coordinates(point['latitude'], point['longitude']):
            return False
            
        # Validate timestamp (not too far in past or future)
        if isinstance(point['timestamp'], datetime):
            delta = abs((datetime.now() - point['timestamp']).days)
            if delta > 365:
                logger.warning(f"Suspicious timestamp: {point['timestamp']}")
                return False
                
        return True