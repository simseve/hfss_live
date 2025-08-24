import logging
import queue
import threading
import atexit
from logging.handlers import QueueHandler, QueueListener, RotatingFileHandler
from typing import List, Optional


class AsyncLoggingManager:
    """
    Manages async logging using QueueHandler and QueueListener.
    This prevents logging from blocking the main application threads.
    """
    
    _instance: Optional['AsyncLoggingManager'] = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not hasattr(self, '_initialized'):
            self._initialized = True
            self.log_queue: Optional[queue.Queue] = None
            self.queue_listener: Optional[QueueListener] = None
            self.handlers: List[logging.Handler] = []
    
    def setup_async_logging(
        self,
        handlers: List[logging.Handler],
        respect_handler_level: bool = True
    ) -> QueueHandler:
        """
        Set up async logging with the provided handlers.
        
        Args:
            handlers: List of logging handlers to process logs asynchronously
            respect_handler_level: Whether to respect individual handler levels
            
        Returns:
            QueueHandler to be used by loggers
        """
        # Create a queue for log records
        self.log_queue = queue.Queue(maxsize=10000)  # Limit queue size to prevent memory issues
        
        # Store handlers for cleanup
        self.handlers = handlers
        
        # Create queue listener with all handlers
        self.queue_listener = QueueListener(
            self.log_queue,
            *handlers,
            respect_handler_level=respect_handler_level
        )
        
        # Start the listener thread
        self.queue_listener.start()
        
        # Register cleanup on exit
        atexit.register(self.stop)
        
        # Return the queue handler to be used by loggers
        return QueueHandler(self.log_queue)
    
    def stop(self):
        """Stop the queue listener and flush remaining logs."""
        if self.queue_listener:
            self.queue_listener.stop()
            self.queue_listener = None
        
        # Ensure all handlers are flushed
        for handler in self.handlers:
            if hasattr(handler, 'flush'):
                handler.flush()
            if hasattr(handler, 'close'):
                handler.close()
    
    def is_running(self) -> bool:
        """Check if async logging is currently running."""
        return self.queue_listener is not None


def create_async_rotating_file_handler(
    filename: str,
    max_bytes: int = 5 * 1024 * 1024,  # 5MB default
    backup_count: int = 10,
    formatter: logging.Formatter = None
) -> RotatingFileHandler:
    """
    Create a rotating file handler for use with async logging.
    
    Args:
        filename: Path to the log file
        max_bytes: Maximum size of each log file
        backup_count: Number of backup files to keep
        formatter: Log formatter to use
        
    Returns:
        Configured RotatingFileHandler
    """
    handler = RotatingFileHandler(
        filename=filename,
        maxBytes=max_bytes,
        backupCount=backup_count
    )
    
    if formatter:
        handler.setFormatter(formatter)
    
    return handler


def create_async_stream_handler(
    stream=None,
    formatter: logging.Formatter = None
) -> logging.StreamHandler:
    """
    Create a stream handler for use with async logging.
    
    Args:
        stream: Stream to write to (defaults to stderr)
        formatter: Log formatter to use
        
    Returns:
        Configured StreamHandler
    """
    handler = logging.StreamHandler(stream)
    
    if formatter:
        handler.setFormatter(formatter)
    
    return handler