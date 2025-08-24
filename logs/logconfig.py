import logging
from logging.config import dictConfig
from logging.handlers import RotatingFileHandler
from config import settings
from logs.async_logging import AsyncLoggingManager, create_async_rotating_file_handler, create_async_stream_handler
# Assuming settings is a module where PROD is defined

def configure_logging(session_id_run, enable_db_logging=False, use_async=True):
    # Set the default logging level
    log_level = logging.INFO if settings.PROD else logging.DEBUG
    
    # Create formatter
    formatter = logging.Formatter(
        f'%(asctime)s %(name)-12s %(levelname)-8s [SESSION_ID: {session_id_run}] %(message)s'
    )
    
    if use_async and settings.PROD:
        # Use async logging in production for better performance
        async_manager = AsyncLoggingManager()
        
        # Create the actual handlers
        actual_handlers = []
        
        # Always add stream handler
        stream_handler = create_async_stream_handler(formatter=formatter)
        stream_handler.setLevel(log_level)
        actual_handlers.append(stream_handler)
        
        # Add file handler in production
        if settings.PROD:
            file_handler = create_async_rotating_file_handler(
                filename='./logs/logs.log',
                max_bytes=1024 * 1024 * 5,  # 5 MB
                backup_count=10,
                formatter=formatter
            )
            file_handler.setLevel(log_level)
            actual_handlers.append(file_handler)
        
        # Add database handler if enabled
        if enable_db_logging:
            from logs.logconfig_db import DatabaseHandler
            db_handler = DatabaseHandler(session_id_run)
            db_handler.setFormatter(formatter)
            db_handler.setLevel(log_level)
            actual_handlers.append(db_handler)
        
        # Set up async logging and get the queue handler
        queue_handler = async_manager.setup_async_logging(actual_handlers)
        
        # Configure logging to use only the queue handler
        LOGGING_CONFIG = dict(
            version=1,
            disable_existing_loggers=False,
            handlers={
                'queue': {
                    'class': 'logging.handlers.QueueHandler',
                    'queue': async_manager.log_queue,
                },
            },
            root={
                'handlers': ['queue'],
                'level': log_level,
            },
        )
    else:
        # Use synchronous logging (original configuration)
        handlers = ['h', 'file'] if settings.PROD else ['h']
        if enable_db_logging:
            handlers.append('db')

        LOGGING_CONFIG = dict(
            version=1,
            disable_existing_loggers=False,
            formatters={
                'f': {
                    'format': f'%(asctime)s %(name)-12s %(levelname)-8s [SESSION_ID: {session_id_run}] %(message)s',
                },
            },
            handlers={
                'h': {
                    'class': 'logging.StreamHandler',
                    'formatter': 'f',
                    'level': log_level,
                },
                'file': {
                    'class': 'logging.handlers.RotatingFileHandler',  # Use RotatingFileHandler
                    'filename': './logs/logs.log',
                    'formatter': 'f',
                    'level': log_level,
                    'maxBytes': 1024 * 1024 * 5,  # 5 MB
                    'backupCount': 10,  # Keep up to 10 backup logs
                }
            },
            root={
                'handlers': handlers,
                'level': log_level,
            },
        )

        if enable_db_logging:
            LOGGING_CONFIG['handlers']['db'] = {
                'class': 'logs.logconfig_db.DatabaseHandler',
                'formatter': 'f',
                'level': log_level,
                'session_id_run': session_id_run
            }

    dictConfig(LOGGING_CONFIG)
