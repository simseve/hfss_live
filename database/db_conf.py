from config import settings
from sqlalchemy import create_engine
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