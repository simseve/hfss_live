from config import settings
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool, QueuePool
from contextlib import contextmanager
import logging
import time

logger = logging.getLogger(__name__)

database_uri = settings.DATABASE_URI

# Detect if using Neon DB
is_neon = 'neon.tech' in database_uri or getattr(settings, 'USE_NEON', False)

if is_neon:
    # Neon-specific configuration for pooler endpoint
    # Note: Neon pooler uses PgBouncer in transaction mode with up to 10,000 connections
    
    # Check if using pooler endpoint (recommended for high concurrency)
    using_pooler = '-pooler' in database_uri
    
    if using_pooler:
        # Neon pooler uses PgBouncer in TRANSACTION MODE
        # This means connections are returned to pool after each transaction
        # IMPORTANT: Cannot use prepared statements, LISTEN, or session-level features
        engine = create_engine(
            database_uri,
            poolclass=QueuePool,  # Local pool management (Neon handles the real pooling)
            pool_size=200,        # For 15k users: ~1500 req/sec needs 150-200 connections
            max_overflow=300,     # Total 500 - handles traffic spikes gracefully
            pool_pre_ping=True,   # CRITICAL: Check connection validity before using
            pool_recycle=300,     # Recycle every 5 minutes (longer is OK with pooler)
            pool_timeout=30,      # Timeout waiting for connection from pool
            pool_use_lifo=False,  # Use FIFO for better distribution with pooler
            echo=False,
            connect_args={
                'connect_timeout': 10,
                'keepalives': 1,
                'keepalives_idle': 30,
                'keepalives_interval': 10,
                'keepalives_count': 5,
                # Disable prepared statements for transaction pooling compatibility
                'prepare_threshold': None,
            }
        )
        logger.info("Using Neon pooler endpoint with QueuePool and aggressive keepalive settings")
    else:
        # For direct Neon connections (non-pooler) - use NullPool to avoid issues
        engine = create_engine(
            database_uri,
            poolclass=NullPool,  # NullPool for direct connections
            pool_pre_ping=True,  # Still check connections
            echo=False,
            connect_args={
                'connect_timeout': 10,
                'keepalives': 1,
                'keepalives_idle': 30,
                'keepalives_interval': 10,
                'keepalives_count': 5,
            }
        )
        logger.info("Using Neon direct connection with NullPool")
else:
    # Traditional PostgreSQL/TimescaleDB configuration
    engine = create_engine(
        database_uri,
        pool_size=100,       # Increased pool size to avoid false degraded alerts
        max_overflow=100,    # Double the overflow for traffic spikes
        pool_pre_ping=True,  # Check connection validity
        pool_recycle=300,    # Recycle every 5 minutes
        pool_timeout=60,     # Longer timeout acceptable
        pool_use_lifo=True,  # Use LIFO for connection reuse
        echo=False
    )
    logger.info("Using traditional PostgreSQL configuration")

# # Create the Session class
# Session = sessionmaker(bind=engine)

Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# # Create a session
# session = Session()


def get_db():
    """Get database session with retry logic for Neon connections"""
    from sqlalchemy.exc import OperationalError, DBAPIError, DisconnectionError
    
    max_retries = 3
    retry_delay = 0.5
    
    for attempt in range(max_retries):
        try:
            session = Session()
            # Pre-ping the connection to ensure it's alive
            session.execute(text("SELECT 1"))
            try:
                yield session
                session.commit()
            except Exception as error:
                session.rollback()
                raise error
            finally:
                session.close()
            return  # Successfully completed
            
        except (OperationalError, DBAPIError, DisconnectionError) as e:
            if "SSL connection has been closed unexpectedly" in str(e):
                logger.warning(f"SSL connection error in get_db, attempt {attempt + 1}/{max_retries}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    retry_delay = min(retry_delay * 2, 5)  # Exponential backoff
                    # Dispose of the pool to get fresh connections
                    engine.dispose()
                    continue
            raise
        except Exception:
            raise


db_context = contextmanager(get_db)


def test_db_connection(max_retries=3):
    """
    Tests the database connection and returns whether it's successful.
    Includes exponential backoff for retries.

    Args:
        max_retries: Maximum number of retries to attempt

    Returns:
        tuple: (success boolean, message string)
    """
    import time
    import logging
    from sqlalchemy.exc import OperationalError, DisconnectionError, DBAPIError

    logger = logging.getLogger(__name__)

    # Ensure max_retries is an integer
    try:
        max_retries = int(max_retries)
    except (ValueError, TypeError):
        logger.warning(
            f"Invalid max_retries value: {max_retries}, using default of 3")
        max_retries = 3

    retry_count = 0
    backoff = 1  # Start with 1 second

    while retry_count < max_retries:
        try:
            # Try to get a connection from the pool and execute a simple query
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return True, "Database connection successful"
        except (OperationalError, DisconnectionError, DBAPIError) as e:
            retry_count += 1
            error_msg = str(e)
            
            # Check for specific SSL errors
            if "SSL connection has been closed unexpectedly" in error_msg:
                logger.warning(f"SSL connection error on attempt {retry_count}/{max_retries}")
                # For SSL errors, recreate the pool
                try:
                    engine.dispose()
                    logger.info("Disposed stale connections from pool")
                except Exception:
                    pass
            
            if retry_count < max_retries:
                logger.info(f"Retrying connection in {backoff} seconds (attempt {retry_count}/{max_retries})")
                time.sleep(backoff)
                backoff = min(backoff * 2, 10)  # Exponential backoff, max 10 seconds
            else:
                return False, f"Database connection failed after {max_retries} attempts: {error_msg}"
        except Exception as e:
            return False, f"Unexpected error testing database connection: {str(e)}"

    return False, "Database connection failed with an unknown error"
