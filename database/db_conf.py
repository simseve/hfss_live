from config import settings
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from contextlib import contextmanager


database_uri = settings.DATABASE_URI

# Create the engine
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


def get_db():
    session = Session()
    try:
        yield session
    except Exception as error:
        session.rollback()
        raise error
    finally:
        session.close()

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
    import logging
    from sqlalchemy.exc import OperationalError, DisconnectionError

    logger = logging.getLogger(__name__)

    # Ensure max_retries is an integer
    try:
        max_retries = int(max_retries)
    except (ValueError, TypeError):
        logger.warning(
            f"Invalid max_retries value: {max_retries}, using default of 3")
        max_retries = 3

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