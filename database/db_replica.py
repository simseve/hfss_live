from config import settings
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool, QueuePool
from contextlib import contextmanager
import logging
import time
import os

logger = logging.getLogger(__name__)

# Get database URIs from environment
primary_database_uri = settings.DATABASE_URI

# Check if replica should be used based on USE_REPLICA flag
if settings.USE_REPLICA and settings.DATABASE_REPLICA_URI:
    replica_database_uri = settings.DATABASE_REPLICA_URI
    logger.info(f"Replica enabled via USE_REPLICA=True")
else:
    replica_database_uri = primary_database_uri
    if not settings.USE_REPLICA:
        logger.info("Replica disabled via USE_REPLICA=False, using primary for all operations")
    else:
        logger.info("No DATABASE_REPLICA_URI configured, using primary for all operations")

# Detect if using Neon DB
is_neon = 'neon.tech' in primary_database_uri or getattr(settings, 'USE_NEON', False)

def create_db_engine(database_uri, pool_size_override=None, max_overflow_override=None):
    """Create a database engine with appropriate configuration based on the database type"""
    
    if is_neon:
        # Neon-specific configuration for pooler endpoint
        using_pooler = '-pooler' in database_uri
        
        if using_pooler:
            # Neon pooler configuration - optimized for transaction pooling mode
            # Pooler endpoint can handle many connections but works best with moderate local pools
            return create_engine(
                database_uri,
                poolclass=QueuePool,
                pool_size=pool_size_override or 50,  # Moderate size for pooler
                max_overflow=max_overflow_override or 50,  # Total 100 connections per engine
                pool_pre_ping=True,
                pool_recycle=300,  # Recycle connections every 5 minutes
                pool_timeout=30,
                pool_use_lifo=True,  # Use LIFO to keep connections warm
                echo=False,
                connect_args={
                    'connect_timeout': 10,
                    'keepalives': 1,
                    'keepalives_idle': 30,
                    'keepalives_interval': 10,
                    'keepalives_count': 5,
                    'prepare_threshold': None  # Disable for transaction pooling
                    # Note: statement_timeout not supported in Neon pooler mode
                }
            )
        else:
            # Direct Neon connection (non-pooler)
            return create_engine(
                database_uri,
                poolclass=NullPool,
                pool_pre_ping=True,
                echo=False,
                connect_args={
                    'connect_timeout': 10,
                    'keepalives': 1,
                    'keepalives_idle': 30,
                    'keepalives_interval': 10,
                    'keepalives_count': 5,
                }
            )
    else:
        # Traditional PostgreSQL/TimescaleDB configuration
        return create_engine(
            database_uri,
            pool_size=pool_size_override or 75,  # Larger pool for reads
            max_overflow=max_overflow_override or 75,
            pool_pre_ping=True,
            pool_recycle=300,
            pool_timeout=60,
            pool_use_lifo=True,
            echo=False
        )

# Create engines for primary and replica
# For Neon pooler endpoints, use moderate pool sizes optimized for transaction pooling
primary_engine = create_db_engine(primary_database_uri, pool_size_override=40, max_overflow_override=40)
replica_engine = create_db_engine(replica_database_uri, pool_size_override=50, max_overflow_override=50)

# Log configuration
if primary_database_uri == replica_database_uri:
    if not settings.USE_REPLICA:
        logger.info("Replica disabled by USE_REPLICA=False setting")
    else:
        logger.info("No replica configured, using primary database for all operations")
else:
    logger.info("Primary/Replica configuration enabled")
    logger.info(f"Primary endpoint: {primary_database_uri.split('@')[1].split('/')[0] if '@' in primary_database_uri else 'configured'}")
    logger.info(f"Replica endpoint: {replica_database_uri.split('@')[1].split('/')[0] if '@' in replica_database_uri else 'configured'}")
    logger.info(f"USE_REPLICA setting: {settings.USE_REPLICA}")

# Create session makers
PrimarySession = sessionmaker(autocommit=False, autoflush=False, bind=primary_engine)
ReplicaSession = sessionmaker(autocommit=False, autoflush=False, bind=replica_engine)

def get_db():
    """Get primary database session for write operations"""
    from sqlalchemy.exc import OperationalError, DBAPIError, DisconnectionError
    
    max_retries = 3
    retry_delay = 0.5
    
    for attempt in range(max_retries):
        try:
            session = PrimarySession()
            # Pre-ping the connection
            session.execute(text("SELECT 1"))
            try:
                yield session
                session.commit()
            except Exception as error:
                session.rollback()
                raise error
            finally:
                session.close()
            return
            
        except (OperationalError, DBAPIError, DisconnectionError) as e:
            if "SSL connection has been closed unexpectedly" in str(e):
                logger.warning(f"SSL connection error in primary DB, attempt {attempt + 1}/{max_retries}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    retry_delay = min(retry_delay * 2, 5)
                    primary_engine.dispose()
                    continue
            raise
        except Exception:
            raise

def get_replica_db():
    """Get replica database session for read operations"""
    from sqlalchemy.exc import OperationalError, DBAPIError, DisconnectionError
    
    max_retries = 3
    retry_delay = 0.5
    
    for attempt in range(max_retries):
        try:
            session = ReplicaSession()
            # Pre-ping the connection
            session.execute(text("SELECT 1"))
            try:
                yield session
                # No commit needed for read-only operations
            except Exception as error:
                session.rollback()
                raise error
            finally:
                session.close()
            return
            
        except (OperationalError, DBAPIError, DisconnectionError) as e:
            if "SSL connection has been closed unexpectedly" in str(e):
                logger.warning(f"SSL connection error in replica DB, attempt {attempt + 1}/{max_retries}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    retry_delay = min(retry_delay * 2, 5)
                    replica_engine.dispose()
                    continue
            raise
        except Exception:
            raise

# Context managers for easier use
primary_db_context = contextmanager(get_db)
replica_db_context = contextmanager(get_replica_db)

# Export get_db as an alias for backwards compatibility
get_primary_db = get_db  # Alias in case anyone was using get_primary_db

def test_replica_connection(max_retries=3):
    """Test the replica database connection"""
    import time
    from sqlalchemy.exc import OperationalError, DisconnectionError, DBAPIError
    
    retry_count = 0
    backoff = 1
    
    while retry_count < max_retries:
        try:
            with replica_engine.connect() as connection:
                connection.execute(text("SELECT 1"))
                # Also check if it's actually a read-only replica
                try:
                    connection.execute(text("CREATE TEMP TABLE test_write (id int)"))
                    connection.execute(text("DROP TABLE test_write"))
                    logger.info("Replica appears to accept writes (might be same as primary)")
                except Exception:
                    logger.info("Replica is read-only (expected behavior)")
            return True, "Replica database connection successful"
        except (OperationalError, DisconnectionError, DBAPIError) as e:
            retry_count += 1
            error_msg = str(e)
            
            if "SSL connection has been closed unexpectedly" in error_msg:
                logger.warning(f"SSL connection error on replica attempt {retry_count}/{max_retries}")
                try:
                    replica_engine.dispose()
                    logger.info("Disposed stale replica connections from pool")
                except Exception:
                    pass
            
            if retry_count < max_retries:
                logger.info(f"Retrying replica connection in {backoff} seconds (attempt {retry_count}/{max_retries})")
                time.sleep(backoff)
                backoff = min(backoff * 2, 10)
            else:
                return False, f"Replica connection failed after {max_retries} attempts: {error_msg}"
        except Exception as e:
            return False, f"Unexpected error testing replica connection: {str(e)}"
    
    return False, "Replica connection failed with an unknown error"

# Backward compatibility - export Session for read operations that should use replica
Session = ReplicaSession