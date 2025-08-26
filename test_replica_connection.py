#!/usr/bin/env python3
"""
Test script to verify primary/replica database configuration
"""

import sys
import os
import logging
from sqlalchemy import text

# Add the current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def test_replica_setup():
    """Test the primary/replica database setup"""
    
    try:
        # Import after path is set
        from database.db_replica import (
            primary_engine, replica_engine,
            test_replica_connection,
            PrimarySession, ReplicaSession
        )
        from config import settings
        
        print("\n" + "="*60)
        print("DATABASE REPLICA CONFIGURATION TEST")
        print("="*60)
        
        # Check if replica is configured
        primary_uri = settings.DATABASE_URI
        replica_uri = settings.DATABASE_REPLICA_URI if settings.DATABASE_REPLICA_URI else primary_uri
        
        if primary_uri == replica_uri:
            print("\n⚠️  WARNING: No separate replica configured")
            print("   DATABASE_REPLICA_URI environment variable not set")
            print("   All operations will use the primary database")
        else:
            print("\n✅ Replica configuration detected")
            print(f"   Primary host: {primary_uri.split('@')[1].split('/')[0] if '@' in primary_uri else 'configured'}")
            print(f"   Replica host: {replica_uri.split('@')[1].split('/')[0] if '@' in replica_uri else 'configured'}")
        
        # Test primary connection
        print("\n" + "-"*40)
        print("Testing PRIMARY database connection...")
        try:
            with primary_engine.connect() as conn:
                result = conn.execute(text("SELECT current_database(), pg_is_in_recovery()"))
                db_name, is_recovery = result.fetchone()
                print(f"✅ Primary connected to: {db_name}")
                print(f"   Is read-only replica: {'Yes' if is_recovery else 'No'}")
                
                # Test write capability
                try:
                    conn.execute(text("CREATE TEMP TABLE test_write (id int)"))
                    conn.execute(text("DROP TABLE test_write"))
                    print("   Write test: ✅ Can write (expected for primary)")
                except Exception as e:
                    print(f"   Write test: ❌ Cannot write - {str(e)}")
        except Exception as e:
            print(f"❌ Primary connection failed: {e}")
            
        # Test replica connection
        print("\n" + "-"*40)
        print("Testing REPLICA database connection...")
        success, message = test_replica_connection()
        if success:
            print(f"✅ {message}")
            
            # Additional replica tests
            try:
                with replica_engine.connect() as conn:
                    result = conn.execute(text("SELECT current_database(), pg_is_in_recovery()"))
                    db_name, is_recovery = result.fetchone()
                    print(f"   Connected to: {db_name}")
                    print(f"   Is read-only replica: {'Yes' if is_recovery else 'No'}")
                    
                    # Test read capability
                    result = conn.execute(text("SELECT COUNT(*) FROM pg_tables WHERE schemaname = 'public'"))
                    table_count = result.scalar()
                    print(f"   Read test: ✅ Can read ({table_count} tables in public schema)")
                    
            except Exception as e:
                print(f"   Additional tests failed: {e}")
        else:
            print(f"❌ {message}")
            
        # Test session makers
        print("\n" + "-"*40)
        print("Testing session makers...")
        
        try:
            # Test primary session (write)
            with PrimarySession() as session:
                result = session.execute(text("SELECT 'primary test'"))
                print("✅ PrimarySession works")
        except Exception as e:
            print(f"❌ PrimarySession failed: {e}")
            
        try:
            # Test replica session (read)
            with ReplicaSession() as session:
                result = session.execute(text("SELECT 'replica test'"))
                print("✅ ReplicaSession works")
        except Exception as e:
            print(f"❌ ReplicaSession failed: {e}")
            
        # Summary
        print("\n" + "="*60)
        if primary_uri != replica_uri:
            print("✅ Primary/Replica setup is configured and working!")
            print("\nTo use in your code:")
            print("  - For reads:  db: Session = Depends(get_replica_db)")
            print("  - For writes: db: Session = Depends(get_primary_db)")
        else:
            print("⚠️  Running without replica - all operations use primary")
            print("\nTo enable read replica:")
            print("  1. Set up a read-only replica in Neon")
            print("  2. Add to .env: DATABASE_REPLICA_URI=<replica_connection_string>")
        print("="*60 + "\n")
        
    except ImportError as e:
        print(f"❌ Import error: {e}")
        print("Make sure you're running this from the project root directory")
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_replica_setup()