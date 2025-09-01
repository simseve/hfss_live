#!/usr/bin/env python3
"""Test replica database connection"""

from database.db_replica import test_replica_connection, replica_engine, primary_engine
from sqlalchemy import text
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

print("Testing replica database connection...")
print("=" * 60)

# Test using the built-in function
success, message = test_replica_connection(max_retries=3)
print(f"Test result: {success}")
print(f"Message: {message}")

print("\n" + "=" * 60)
print("Direct connection test:")

# Try a direct connection to replica
try:
    with replica_engine.connect() as conn:
        result = conn.execute(text("SELECT current_database(), version()"))
        row = result.fetchone()
        print(f"✅ Replica connected to database: {row[0]}")
        print(f"   PostgreSQL version: {row[1][:50]}...")
except Exception as e:
    print(f"❌ Replica connection failed: {e}")

print("\n" + "=" * 60)
print("Primary connection test:")

# Compare with primary
try:
    with primary_engine.connect() as conn:
        result = conn.execute(text("SELECT current_database(), inet_server_addr()"))
        row = result.fetchone()
        print(f"✅ Primary connected to database: {row[0]}")
        print(f"   Server address: {row[1]}")
except Exception as e:
    print(f"❌ Primary connection failed: {e}")

print("\n" + "=" * 60)
print("Connection URLs (masked):")
from database.db_replica import primary_database_uri, replica_database_uri

def mask_url(url):
    if '@' in url:
        parts = url.split('@')
        return f"***@{parts[1]}"
    return url

print(f"Primary: {mask_url(primary_database_uri)}")
print(f"Replica: {mask_url(replica_database_uri)}")
print(f"Same endpoint: {primary_database_uri == replica_database_uri}")