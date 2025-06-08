#!/usr/bin/env python3
"""
Test script to create a valid Flymaster upload file and test the authentication.
"""

import hashlib
import tempfile
import os
from datetime import datetime, timezone


def generate_flymaster_hash(device_id, secret):
    """Generate standard SHA256 hash for Flymaster authentication"""
    combined = str(device_id) + secret
    return hashlib.sha256(combined.encode()).hexdigest()


def create_test_flymaster_file():
    """Create a test Flymaster file with proper authentication"""

    # Test data
    device_id = 123457
    secret = "JijoHPvHXyHjajDK00V"  # This should match your FLYMASTER_SECRET

    # Generate the hash
    sha256_hash = generate_flymaster_hash(device_id, secret)

    print(f"Device ID: {device_id}")
    print(f"Secret: {secret}")
    print(f"Generated Hash: {sha256_hash}")
    print(f"Expected Hash:  64e1d390354e3869bbc0453886cd36a1d453b8776ff40443e75bffcf9b2d810a")
    print(f"Match: {'✅ YES' if sha256_hash == '64e1d390354e3869bbc0453886cd36a1d453b8776ff40443e75bffcf9b2d810a' else '❌ NO'}")
    print()

    # Create file content
    current_time = int(datetime.now(timezone.utc).timestamp())

    file_content = f"""{device_id},{sha256_hash}
{current_time},{current_time},46.1234,7.5678,1000.0,25.5,180.0
{current_time + 10},{current_time + 10},46.1244,7.5688,1010.0,26.0,185.0
{current_time + 20},{current_time + 20},46.1254,7.5698,1020.0,24.8,175.0
EOF"""

    # Write to temporary file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write(file_content)
        temp_file_path = f.name

    print(f"Created test file: {temp_file_path}")
    print("\nFile content:")
    print(file_content)

    return temp_file_path


def main():
    """Create test file and display information"""
    print("🚀 Creating Flymaster Test File")
    print("="*50)

    test_file = create_test_flymaster_file()

    print(f"\n📄 Test file created at: {test_file}")
    print("\nThis file can be used to test the /flymaster/upload/file endpoint")
    print("\nTo test manually:")
    print(f"curl -X POST http://localhost:8000/tracking/flymaster/upload/file \\")
    print(f"  -F 'file=@{test_file}'")

    # Don't delete the file automatically so it can be used for testing
    print(f"\nRemember to delete the test file when done: rm {test_file}")


if __name__ == "__main__":
    main()
