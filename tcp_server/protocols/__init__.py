"""
GPS Tracker Protocol Handlers
"""
from typing import Dict, Any, Optional, Type, List
import logging
from .base import BaseProtocolHandler
from .tk905b import TK905BProtocolHandler
from .tk103 import TK103ProtocolHandler

logger = logging.getLogger(__name__)


class ProtocolFactory:
    """Factory for creating and managing protocol handlers"""
    
    # Register available protocol handlers
    HANDLERS: List[Type[BaseProtocolHandler]] = [
        TK905BProtocolHandler,
        TK103ProtocolHandler,
    ]
    
    def __init__(self):
        self.handlers_cache: Dict[str, BaseProtocolHandler] = {}
    
    def detect_protocol(self, data: str) -> Optional[BaseProtocolHandler]:
        """
        Detect and return the appropriate protocol handler for the message
        Uses caching to reuse handlers for the same device
        """
        # Try each registered handler
        for handler_class in self.HANDLERS:
            handler = handler_class()
            if handler.can_handle(data):
                logger.debug(f"Detected {handler.get_protocol_name()} protocol")
                return handler
                
        logger.warning(f"No handler found for message: {data[:100]}")
        return None
    
    def get_handler_for_device(self, device_id: str, protocol_name: str = None) -> Optional[BaseProtocolHandler]:
        """Get or create a handler for a specific device"""
        cache_key = f"{device_id}_{protocol_name}" if protocol_name else device_id
        
        if cache_key in self.handlers_cache:
            return self.handlers_cache[cache_key]
            
        # Create new handler if protocol is known
        if protocol_name:
            for handler_class in self.HANDLERS:
                handler = handler_class(device_id)
                if handler.get_protocol_name().lower() == protocol_name.lower():
                    self.handlers_cache[cache_key] = handler
                    return handler
                    
        return None
    
    def parse_message(self, data: str, device_id: str = None) -> Optional[Dict[str, Any]]:
        """
        Parse a message using the appropriate protocol handler
        Returns parsed data or None if parsing fails
        """
        # Try to get cached handler for device
        if device_id and device_id in self.handlers_cache:
            handler = self.handlers_cache[device_id]
            parsed = handler.parse_message(data)
            if parsed:
                return parsed
                
        # Detect protocol and parse
        handler = self.detect_protocol(data)
        if handler:
            parsed = handler.parse_message(data)
            
            # Cache the handler for this device
            if parsed and 'device_id' in parsed:
                device_id = parsed['device_id']
                self.handlers_cache[device_id] = handler
                
            return parsed
            
        return None
    
    def create_response(self, parsed_data: Dict[str, Any], success: bool = True) -> str:
        """Create appropriate response for parsed message"""
        if not parsed_data:
            return ""
            
        device_id = parsed_data.get('device_id')
        protocol = parsed_data.get('protocol')
        
        # Get handler from cache or create new one
        handler = None
        if device_id and device_id in self.handlers_cache:
            handler = self.handlers_cache[device_id]
        elif protocol:
            # Create handler based on protocol
            for handler_class in self.HANDLERS:
                h = handler_class()
                if h.get_protocol_name().lower() == protocol.lower() or \
                   (protocol == 'watch' and isinstance(h, TK905BProtocolHandler)) or \
                   (protocol == 'tk103' and isinstance(h, TK103ProtocolHandler)):
                    handler = h
                    break
                    
        if handler:
            return handler.create_response(parsed_data, success)
            
        return ""
    
    def get_supported_protocols(self) -> List[str]:
        """Get list of supported protocol names"""
        return [h().get_protocol_name() for h in self.HANDLERS]


# Global factory instance
protocol_factory = ProtocolFactory()

# Export main functions
def parse_message(data: str, device_id: str = None) -> Optional[Dict[str, Any]]:
    """Parse a GPS tracker message"""
    return protocol_factory.parse_message(data, device_id)

def create_response(parsed_data: Dict[str, Any], success: bool = True) -> str:
    """Create response for a parsed message"""
    return protocol_factory.create_response(parsed_data, success)

def get_supported_protocols() -> List[str]:
    """Get list of supported protocols"""
    return protocol_factory.get_supported_protocols()


__all__ = [
    'BaseProtocolHandler',
    'TK905BProtocolHandler', 
    'TK103ProtocolHandler',
    'ProtocolFactory',
    'protocol_factory',
    'parse_message',
    'create_response',
    'get_supported_protocols'
]