"""
Database connection helper with backward compatibility
Supports both Neon DB and TimescaleDB
"""

import os
import re
from typing import Optional
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine
from sqlalchemy.pool import NullPool, QueuePool
from sqlalchemy.engine import Engine
from dotenv import load_dotenv

load_dotenv()

def get_database_url() -> str:
    """Get database URL from environment"""
    # Support both DATABASE_URL and DATABASE_URI for compatibility
    return os.getenv('DATABASE_URL') or os.getenv('DATABASE_URI')

def is_neon_db() -> bool:
    """Check if using Neon DB"""
    use_neon = os.getenv('USE_NEON', 'False').lower() == 'true'
    db_url = get_database_url()
    # Auto-detect Neon if URL contains neon.tech
    if db_url and 'neon.tech' in db_url:
        return True
    return use_neon

def prepare_async_url(url: str) -> str:
    """Convert sync URL to async URL with proper format"""
    # Replace postgresql:// with postgresql+asyncpg://
    async_url = re.sub(r'^postgresql://', 'postgresql+asyncpg://', url)
    
    # For Neon, we need to handle SSL differently for asyncpg
    if is_neon_db() and 'sslmode=' in async_url:
        # Remove sslmode parameter as asyncpg uses different SSL config
        async_url = re.sub(r'[?&]sslmode=\w+', '', async_url)
    
    return async_url

def get_sync_engine(**kwargs) -> Engine:
    """
    Create synchronous database engine with appropriate settings
    """
    db_url = get_database_url()
    if not db_url:
        raise ValueError("DATABASE_URL or DATABASE_URI not set")
    
    # Default settings
    engine_kwargs = {
        'echo': kwargs.get('echo', False),
        'pool_pre_ping': True,  # Check connections before using
    }
    
    if is_neon_db():
        # Neon-specific settings
        engine_kwargs.update({
            'poolclass': NullPool,  # Recommended for serverless
            'connect_args': {
                'connect_timeout': 10,
                # Note: statement_timeout not supported with Neon pooler
            }
        })
    else:
        # TimescaleDB/regular PostgreSQL settings
        engine_kwargs.update({
            'pool_size': kwargs.get('pool_size', 10),
            'max_overflow': kwargs.get('max_overflow', 20),
            'pool_timeout': 30,
            'pool_recycle': 3600,  # Recycle connections after 1 hour
        })
    
    # Override with any provided kwargs
    engine_kwargs.update(kwargs)
    
    return create_engine(db_url, **engine_kwargs)

def get_async_engine(**kwargs) -> AsyncEngine:
    """
    Create asynchronous database engine with appropriate settings
    """
    db_url = get_database_url()
    if not db_url:
        raise ValueError("DATABASE_URL or DATABASE_URI not set")
    
    # Convert to async URL
    async_url = prepare_async_url(db_url)
    
    # Default settings
    engine_kwargs = {
        'echo': kwargs.get('echo', False),
        'pool_pre_ping': True,
    }
    
    if is_neon_db():
        # Neon-specific settings for async
        engine_kwargs.update({
            'poolclass': NullPool,  # Recommended for serverless
            'connect_args': {
                'ssl': 'require',  # asyncpg uses 'ssl' not 'sslmode'
                'timeout': 10,
                'command_timeout': 60,
            }
        })
    else:
        # TimescaleDB/regular PostgreSQL settings
        engine_kwargs.update({
            'pool_size': kwargs.get('pool_size', 10),
            'max_overflow': kwargs.get('max_overflow', 20),
            'pool_timeout': 30,
            'pool_recycle': 3600,
        })
    
    # Override with any provided kwargs
    engine_kwargs.update(kwargs)
    
    return create_async_engine(async_url, **engine_kwargs)

# Convenience functions for backward compatibility
def create_sync_engine(**kwargs) -> Engine:
    """Backward compatible sync engine creation"""
    return get_sync_engine(**kwargs)

def create_async_db_engine(**kwargs) -> AsyncEngine:
    """Backward compatible async engine creation"""
    return get_async_engine(**kwargs)

# Example usage
if __name__ == "__main__":
    import asyncio
    from sqlalchemy import text
    
    async def test_async():
        """Test async connection"""
        engine = get_async_engine(echo=True)
        
        async with engine.connect() as conn:
            # Test basic query
            result = await conn.execute(text("SELECT 'hello world' as message"))
            row = result.fetchone()
            print(f"Async test: {row[0]}")
            
            # Test table query
            result = await conn.execute(text("SELECT COUNT(*) FROM races"))
            count = result.scalar()
            print(f"Found {count} races")
            
        await engine.dispose()
        print("✓ Async connection successful!")
    
    def test_sync():
        """Test sync connection"""
        engine = get_sync_engine(echo=False)
        
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 'hello world' as message"))
            row = result.fetchone()
            print(f"Sync test: {row[0]}")
            
            result = conn.execute(text("SELECT COUNT(*) FROM races"))
            count = result.scalar()
            print(f"Found {count} races")
            
        engine.dispose()
        print("✓ Sync connection successful!")
    
    # Run tests
    print(f"Testing database connections...")
    print(f"Using Neon DB: {is_neon_db()}")
    print(f"Database URL: {get_database_url()[:50]}...")
    print()
    
    # Test sync
    test_sync()
    print()
    
    # Test async
    asyncio.run(test_async())