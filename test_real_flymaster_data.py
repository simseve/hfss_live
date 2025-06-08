#!/usr/bin/env python3
"""
Test script to verify Flymaster endpoint with real flymaster file data
This emulates PHP curl post_as_file=1 behavior using actual flymaster data
"""

import hashlib
import requests
import time
import os
from datetime import datetime, timezone

# Configuration
API_BASE_URL = "http://localhost:8000"
FLYMASTER_SECRET = "7JijoHPvHXyHjajDK00V"  # Secret from your .env file
FLYMASTER_FILE_PATH = "/Users/simone/Apps/hfss_live/flymaster"


def create_auth_hash(device_id: int, secret: str) -> str:
    """Create SHA256 authentication hash"""
    combined = str(device_id) + secret
    return hashlib.sha256(combined.encode()).hexdigest()


def read_flymaster_file():
    """Read the actual flymaster file content"""
    try:
        with open(FLYMASTER_FILE_PATH, 'r') as f:
            content = f.read().strip()
        return content
    except FileNotFoundError:
        print(f"Error: Flymaster file not found at {FLYMASTER_FILE_PATH}")
        return None
    except Exception as e:
        print(f"Error reading flymaster file: {e}")
        return None


def verify_auth_in_file(content: str):
    """Verify the authentication hash in the file is correct"""
    lines = content.split('\n')
    if not lines:
        return False, "No content in file"

    # First line should be device_id,hash
    header_line = lines[0].strip()
    try:
        device_id_str, provided_hash = header_line.split(',')
        device_id = int(device_id_str)

        # Calculate expected hash
        expected_hash = create_auth_hash(device_id, FLYMASTER_SECRET)

        if provided_hash == expected_hash:
            return True, f"Authentication valid for device {device_id}"
        else:
            return False, f"Hash mismatch: expected {expected_hash}, got {provided_hash}"
    except Exception as e:
        return False, f"Error parsing header: {e}"


def test_php_post_as_file_real_data():
    """Test the endpoint with real flymaster data using PHP post_as_file=1 format"""
    print("Testing Flymaster endpoint with REAL flymaster file data...")
    print("=" * 70)

    # Read the actual flymaster file
    flymaster_content = read_flymaster_file()
    if not flymaster_content:
        print("Cannot proceed without flymaster file content")
        return False

    print(f"Loaded flymaster file from: {FLYMASTER_FILE_PATH}")
    print(f"File content preview (first 200 chars):")
    print(flymaster_content[:200] +
          "..." if len(flymaster_content) > 200 else flymaster_content)
    print()

    # Verify authentication in the file
    auth_valid, auth_message = verify_auth_in_file(flymaster_content)
    print(f"Authentication check: {auth_message}")
    if not auth_valid:
        print("WARNING: Authentication may fail!")
    print()

    # Simulate PHP curl with post_as_file=1 (sends raw data with text/plain content-type)
    headers = {
        'Content-Type': 'text/plain',
        'User-Agent': 'PHP/cURL (simulated)'
    }

    url = f"{API_BASE_URL}/tracking/flymaster/upload/file"
    print(f"Sending POST request to: {url}")
    print(f"Headers: {headers}")
    print(f"Body: Raw flymaster file content ({len(flymaster_content)} bytes)")
    print()

    try:
        # Send the request exactly like PHP curl post_as_file=1 would
        response = requests.post(url, data=flymaster_content, headers=headers)

        print("Response received:")
        print(f"  Status Code: {response.status_code}")
        print(f"  Headers: {dict(response.headers)}")
        print(f"  Body: '{response.text}'")
        print()

        # Check if successful
        if response.status_code == 200:
            if response.text == "OK":
                print("✓ SUCCESS: Real flymaster data processed successfully!")
                print("✓ PHP curl post_as_file=1 format works correctly!")
                return True
            else:
                print(
                    f"✗ UNEXPECTED RESPONSE: Expected 'OK', got '{response.text}'")
                return False
        else:
            print(f"✗ HTTP ERROR: {response.status_code}")
            if response.text:
                print(f"  Error details: {response.text}")
            return False

    except requests.exceptions.ConnectionError:
        print("✗ CONNECTION ERROR: Is the server running on localhost:8000?")
        return False
    except requests.exceptions.RequestException as e:
        print(f"✗ REQUEST FAILED: {e}")
        return False
    except Exception as e:
        print(f"✗ UNEXPECTED ERROR: {e}")
        return False


def test_file_upload_real_data():
    """Test traditional file upload with real data for comparison"""
    print("\n" + "=" * 70)
    print("Testing traditional file upload with real data...")

    flymaster_content = read_flymaster_file()
    if not flymaster_content:
        return False

    # Create a file-like object with real data
    files = {'file': ('flymaster_data.txt', flymaster_content, 'text/plain')}

    url = f"{API_BASE_URL}/tracking/flymaster/upload/file"
    print(f"Sending multipart file upload to: {url}")

    try:
        response = requests.post(url, files=files)

        print(f"Response status: {response.status_code}")
        print(f"Response body: '{response.text}'")

        if response.status_code == 200 and response.text == "OK":
            print("✓ SUCCESS: Traditional file upload works!")
            return True
        else:
            print(f"✗ FAILED: Unexpected response")
            return False

    except Exception as e:
        print(f"✗ ERROR: {e}")
        return False


def test_with_modified_timestamps():
    """Test with current timestamps to simulate fresh data"""
    print("\n" + "=" * 70)
    print("Testing with current timestamps (simulating fresh data)...")

    flymaster_content = read_flymaster_file()
    if not flymaster_content:
        return False

    lines = flymaster_content.split('\n')

    # Keep the header (authentication) but update timestamps
    modified_lines = [lines[0]]  # Keep authentication header

    current_time = int(time.time())

    # Update data lines with current timestamps
    for i, line in enumerate(lines[1:], 1):
        if line.strip() and not line.strip().upper() == "EOF":
            parts = line.split(',')
            if len(parts) >= 7:
                # Update uploaded_at and date_time to current time + offset
                parts[0] = str(current_time + i)  # uploaded_at
                parts[1] = str(current_time + i)  # date_time
                modified_lines.append(','.join(parts))
            else:
                # Keep original if format unexpected
                modified_lines.append(line)
        else:
            modified_lines.append(line)  # Keep EOF and empty lines

    modified_content = '\n'.join(modified_lines)

    # Send with current timestamps
    headers = {'Content-Type': 'text/plain'}
    url = f"{API_BASE_URL}/tracking/flymaster/upload/file"

    print(f"Updated timestamps to current time ({current_time})")
    print("Sending modified data...")

    try:
        response = requests.post(url, data=modified_content, headers=headers)

        print(f"Response status: {response.status_code}")
        print(f"Response body: '{response.text}'")

        if response.status_code == 200 and response.text == "OK":
            print("✓ SUCCESS: Fresh timestamp data processed!")
            return True
        else:
            print(f"✗ FAILED: Unexpected response")
            return False

    except Exception as e:
        print(f"✗ ERROR: {e}")
        return False


def run_all_tests():
    """Run comprehensive tests"""
    print("FLYMASTER REAL DATA TESTING SUITE")
    print("=" * 70)
    print(f"Target API: {API_BASE_URL}")
    print(f"Flymaster file: {FLYMASTER_FILE_PATH}")
    print(f"Secret: {FLYMASTER_SECRET}")
    print()

    results = []

    # Test 1: PHP post_as_file=1 format with real data
    results.append(("PHP post_as_file=1 format",
                   test_php_post_as_file_real_data()))

    # Test 2: Traditional file upload
    results.append(("Traditional file upload", test_file_upload_real_data()))

    # Test 3: Fresh timestamps
    results.append(("Current timestamps", test_with_modified_timestamps()))

    # Summary
    print("\n" + "=" * 70)
    print("TEST RESULTS SUMMARY:")
    print("=" * 70)

    all_passed = True
    for test_name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{test_name:30} {status}")
        if not passed:
            all_passed = False

    print()
    if all_passed:
        print("🎉 ALL TESTS PASSED!")
        print("Your PHP code with post_as_file=1 should work perfectly!")
    else:
        print("⚠️  Some tests failed. Check the server logs for details.")

    print("\nTip: Check your FastAPI server logs to see background processing.")


if __name__ == "__main__":
    run_all_tests()
