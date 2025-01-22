import logging
from logging.config import dictConfig
from logging.handlers import RotatingFileHandler
from config import settings
# Assuming settings is a module where PROD is defined

def configure_logging(session_id_run, enable_db_logging=False):
    # Set the default logging level
    log_level = logging.INFO if settings.PROD else logging.DEBUG

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
                'backupCount': 10,  # Keep up to 5 backup logs
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
