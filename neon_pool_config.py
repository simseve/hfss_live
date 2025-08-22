# Neon DB Connection Pool Configuration
# Add this to your database connection setup

from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

# For Neon, use NullPool to avoid connection issues with serverless
engine = create_engine(
    DATABASE_URL,
    poolclass=NullPool,  # Important for Neon
    connect_args={
        "sslmode": "require",
        "connect_timeout": 10,
        "options": "-c statement_timeout=60000"  # 60 second timeout
    }
)

# For async connections with asyncpg
async_engine = create_async_engine(
    DATABASE_URL,
    poolclass=NullPool,
    connect_args={
        "ssl": "require",
        "timeout": 10,
        "command_timeout": 60
    }
)
