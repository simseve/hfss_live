#!/usr/bin/env python3
"""
Test script to verify UUID serialization in the scoring endpoint.
"""

import asyncio
import aiohttp
import logging
import uuid
from datetime import datetime, timezone

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE_URL = "http://localhost:8000"

# Test data for scoring endpoint
TEST_SCORING_DATA = {
    "tracks": [
        {
            "date_time": "2024-01-15T12:00:00Z",
            "lat": 46.3234,
            "lon": 7.7678,
            "elevation": 1200,
            "flight_uuid": None  # Will be set by the endpoint
        },
        {
            "date_time": "2024-01-15T12:01:00Z",
            "lat": 46.3244,
            "lon": 7.7688,
            "elevation": 1210,
            "flight_uuid": None  # Will be set by the endpoint
        }
    ]
}


async def test_scoring_endpoint():
    """Test the scoring batch endpoint to verify UUID serialization"""
    logger.info("Testing scoring batch endpoint...")

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(
                f"{BASE_URL}/scoring/batch",
                json=TEST_SCORING_DATA,
                headers={"Content-Type": "application/json"}
            ) as response:

                response_text = await response.text()
                logger.info(f"Scoring response status: {response.status}")
                logger.info(f"Scoring response: {response_text}")

                if response.status == 201:  # 201 Created is the expected response
                    data = await response.json()
                    flight_uuid = data.get('flight_uuid')
                    points_added = data.get('points_added')

                    logger.info(
                        f"✅ Scoring test PASSED - Flight UUID: {flight_uuid}, Points: {points_added}")
                    return True
                else:
                    logger.error(
                        f"❌ Scoring test FAILED with status {response.status}")
                    return False

        except Exception as e:
            logger.error(f"❌ Scoring test FAILED with exception: {e}")
            return False


async def main():
    """Run scoring test"""
    logger.info("🚀 Starting scoring UUID serialization test...")

    result = await test_scoring_endpoint()

    # Wait for background processing
    logger.info("Waiting for background queue processing...")
    await asyncio.sleep(3)

    logger.info("\n" + "="*50)
    logger.info("SCORING TEST SUMMARY:")
    logger.info(f"Scoring endpoint: {'✅ PASSED' if result else '❌ FAILED'}")

    if result:
        logger.info("🎉 Scoring UUID serialization test PASSED!")
    else:
        logger.info("⚠️  Scoring test failed. Check logs for details.")

    logger.info("="*50)

if __name__ == "__main__":
    asyncio.run(main())
