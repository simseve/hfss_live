from config import settings
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from contextlib import contextmanager


database_uri = settings.DATABASE_URI

# # Create the engine with more resilient connection settings
# engine = create_engine(database_uri,
#                        pool_size=10,
#                        max_overflow=20,
#                        pool_pre_ping=True,  # Check connection validity before using it
#                        pool_recycle=60,     # Recycle connections after 1 minute to avoid SSL timeouts
#                        pool_timeout=30,     # Wait up to 30 seconds for a connection from the pool
#                        echo=False,
#                        connect_args={
#                            'connect_timeout': 10,  # Connection timeout in seconds
#                            'keepalives': 1,        # Enable TCP keepalives
#                            'keepalives_idle': 30,  # Time before sending keepalives
#                            'keepalives_interval': 10,  # How often to send keepalives
#                            'keepalives_count': 5,   # How many keepalives before giving up
#                            'sslmode': 'disable'    # Explicitly disable SSL
#                        })

# Create the engine with more resilient connection settings
engine = create_engine(database_uri,
                       pool_size=10,
                       max_overflow=20,
                       pool_pre_ping=True,  # Check connection validity before using it
                       pool_recycle=60,     # Recycle connections after 1 minute to avoid SSL timeouts
                       pool_timeout=30,     # Wait up to 30 seconds for a connection from the pool
                       echo=False)
# # Create the Session class
# Session = sessionmaker(bind=engine)

Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# # Create a session
# session = Session()


def get_db(max_retries=3, retry_delay=0.5):
    """
    Provides a database session with retry capability to handle transient connection issues.

    Args:
        max_retries: Maximum number of times to retry getting a session
        retry_delay: Delay between retries in seconds

    Yields:
        SQLAlchemy session
    """
    import time
    import logging
    from sqlalchemy.exc import OperationalError, DisconnectionError

    logger = logging.getLogger(__name__)
    retry_count = 0
    last_error = None

    while retry_count < max_retries:
        session = Session()
        try:
            # Test the connection with a simple query before yielding it
            session.execute(text("SELECT 1"))
            yield session
            break  # If we get here, the session was used successfully
        except (OperationalError, DisconnectionError) as error:
            session.rollback()
            last_error = error
            retry_count += 1

            if "SSL connection has been closed unexpectedly" in str(error) or "connection already closed" in str(error):
                logger.warning(
                    f"Database connection error (attempt {retry_count}/{max_retries}): {str(error)}")

                if retry_count < max_retries:
                    logger.info(
                        f"Retrying database connection in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                    # Let the loop continue to retry
                else:
                    logger.error(
                        f"Max retries reached. Database connection failed: {str(error)}")
                    raise
            else:
                # For other database errors, don't retry
                logger.error(f"Database error: {str(error)}")
                raise
        except Exception as error:
            session.rollback()
            logger.error(
                f"Unexpected error with database session: {str(error)}")
            raise
        finally:
            session.close()

    # If we've exhausted all retries
    if retry_count == max_retries and last_error is not None:
        logger.error(
            f"Failed to establish database connection after {max_retries} attempts")
        raise last_error


db_context = contextmanager(get_db)


def test_db_connection(max_retries=3):
    """
    Tests the database connection and returns whether it's successful.

    Args:
        max_retries: Maximum number of retries to attempt

    Returns:
        tuple: (success boolean, message string)
    """
    import time
    from sqlalchemy.exc import OperationalError, DisconnectionError

    retry_count = 0

    while retry_count < max_retries:
        try:
            # Try to get a connection from the pool and execute a simple query
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return True, "Database connection successful"
        except (OperationalError, DisconnectionError) as e:
            retry_count += 1
            if retry_count < max_retries:
                time.sleep(1)  # Wait 1 second before retrying
            else:
                return False, f"Database connection failed after {max_retries} attempts: {str(e)}"
        except Exception as e:
            return False, f"Unexpected error testing database connection: {str(e)}"

    return False, "Database connection failed with an unknown error"
