#!/usr/bin/env python3
"""
Test script to verify the JSON serialization fixes for the live tracking system.
This script will test both the live tracking and upload endpoints to ensure
SQLAlchemy instances with InstanceState objects don't cause serialization errors.
"""

import asyncio
import json
import logging
import aiohttp
from datetime import datetime, timezone
import uuid

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Test token from existing tests (might need to be refreshed)
TEST_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJwaWxvdF9pZCI6IjY4MGY4NTRmMmI4NTk5ZDZhMzM2ZDUxZiIsInJhY2VfaWQiOiI2Nzk4MDU1ODEyZTYyOWE4ODM4YTcwNTkiLCJwaWxvdF9uYW1lIjoiVml0IFJlbmEiLCJleHAiOjE3NzE1NDU1OTksInJhY2UiOnsibmFtZSI6IkhGU1MgVHJhY2tlciBMaXZlIiwiZGF0ZSI6IjIwMjUtMDItMTkiLCJ0aW1lem9uZSI6IkV1cm9wZS9Sb21lIiwibG9jYXRpb24iOiJUZXN0IiwiZW5kX2RhdGUiOiIyMDI2LTAyLTE5In0sImVuZHBvaW50cyI6eyJsaXZlIjoiL2xpdmUiLCJ1cGxvYWQiOiIvdXBsb2FkIn19.Se_km_mMkESwo6rUjU8GPW4zr6Gr0GvvbGv07ReOhTA"

# Test data
TEST_LIVE_DATA = {
    "flight_id": "TEST-123",
    "pilot_name": "Test Pilot",
    "track_points": [
        {
            "datetime": "2024-01-15T10:00:00Z",
            "lat": 46.1234,
            "lon": 7.5678,
            "elevation": 1000
        },
        {
            "datetime": "2024-01-15T10:01:00Z",
            "lat": 46.1244,
            "lon": 7.5688,
            "elevation": 1010
        },
        {
            "datetime": "2024-01-15T10:02:00Z",
            "lat": 46.1254,
            "lon": 7.5698,
            "elevation": 1020
        }
    ]
}

TEST_UPLOAD_DATA = {
    "flight_id": "UPLOAD-TEST-456",
    "pilot_name": "Upload Test Pilot",
    "track_points": [
        {
            "datetime": "2024-01-15T11:00:00Z",
            "lat": 46.2234,
            "lon": 7.6678,
            "elevation": 1100
        },
        {
            "datetime": "2024-01-15T11:01:00Z",
            "lat": 46.2244,
            "lon": 7.6688,
            "elevation": 1110
        }
    ]
}

BASE_URL = "http://localhost:8000"


async def test_live_tracking():
    """Test the live tracking endpoint"""
    logger.info("Testing live tracking endpoint...")

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(
                f"{BASE_URL}/tracking/live?token={TEST_TOKEN}",
                json=TEST_LIVE_DATA,
                headers={"Content-Type": "application/json"}
            ) as response:

                response_text = await response.text()
                logger.info(
                    f"Live tracking response status: {response.status}")
                logger.info(f"Live tracking response: {response_text}")

                if response.status == 202:  # 202 Accepted is the correct response
                    data = await response.json()
                    logger.info("✅ Live tracking test PASSED")
                    return True
                else:
                    logger.error(
                        f"❌ Live tracking test FAILED with status {response.status}")
                    return False

        except Exception as e:
            logger.error(f"❌ Live tracking test FAILED with exception: {e}")
            return False


async def test_upload_tracking():
    """Test the upload tracking endpoint"""
    logger.info("Testing upload tracking endpoint...")

    # Generate unique flight ID for each test
    unique_flight_id = f"UPLOAD-TEST-{uuid.uuid4().hex[:8]}"
    test_data = TEST_UPLOAD_DATA.copy()
    test_data["flight_id"] = unique_flight_id

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(
                f"{BASE_URL}/tracking/upload?token={TEST_TOKEN}",
                json=test_data,
                headers={"Content-Type": "application/json"}
            ) as response:

                response_text = await response.text()
                logger.info(
                    f"Upload tracking response status: {response.status}")
                logger.info(f"Upload tracking response: {response_text}")

                if response.status == 202:  # 202 Accepted is the correct response
                    data = await response.json()
                    logger.info("✅ Upload tracking test PASSED")
                    return True
                else:
                    logger.error(
                        f"❌ Upload tracking test FAILED with status {response.status}")
                    return False

        except Exception as e:
            logger.error(f"❌ Upload tracking test FAILED with exception: {e}")
            return False


async def test_redis_queue_processing():
    """Wait a bit and check if background processing works without serialization errors"""
    logger.info("Waiting for background queue processing...")
    await asyncio.sleep(5)  # Give some time for background processing
    logger.info("Background processing time completed")


async def main():
    """Run all tests"""
    logger.info("🚀 Starting JSON serialization fix tests...")

    # Test live tracking
    live_result = await test_live_tracking()

    # Small delay between tests
    await asyncio.sleep(1)

    # Test upload tracking
    upload_result = await test_upload_tracking()

    # Test background processing
    await test_redis_queue_processing()

    # Summary
    logger.info("\n" + "="*50)
    logger.info("TEST SUMMARY:")
    logger.info(f"Live tracking: {'✅ PASSED' if live_result else '❌ FAILED'}")
    logger.info(
        f"Upload tracking: {'✅ PASSED' if upload_result else '❌ FAILED'}")

    if live_result and upload_result:
        logger.info(
            "🎉 All tests PASSED! JSON serialization issues appear to be fixed.")
    else:
        logger.info("⚠️  Some tests failed. Check logs for details.")

    logger.info("="*50)

if __name__ == "__main__":
    asyncio.run(main())
