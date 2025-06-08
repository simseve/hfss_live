#!/usr/bin/env python3
"""
Simple test script to verify Redis queue functionality
"""
import asyncio
import logging
from datetime import datetime, timezone
from redis_queue_system.redis_queue import redis_queue, QUEUE_NAMES
from redis_queue_system.point_processor import point_processor

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_redis_queue():
    """Test Redis queue functionality"""
    try:
        # Initialize Redis
        await redis_queue.initialize()
        logger.info("✓ Redis connected successfully")

        # Test queueing some sample points
        sample_points = [
            {
                "flight_id": "test_flight_123",
                "flight_uuid": "123e4567-e89b-12d3-a456-426614174000",
                "datetime": datetime.now(timezone.utc).isoformat(),
                "lat": 45.5231,
                "lon": -122.6765,
                "elevation": 1200.5
            },
            {
                "flight_id": "test_flight_123",
                "flight_uuid": "123e4567-e89b-12d3-a456-426614174000",
                "datetime": datetime.now(timezone.utc).isoformat(),
                "lat": 45.5235,
                "lon": -122.6770,
                "elevation": 1205.0
            }
        ]

        # Queue test points
        success = await redis_queue.queue_points(
            QUEUE_NAMES['live'],
            sample_points,
            priority=1
        )

        if success:
            logger.info("✓ Successfully queued test points")
        else:
            logger.error("✗ Failed to queue test points")
            return False

        # Check queue stats
        stats = await redis_queue.get_queue_stats()
        logger.info(f"✓ Queue stats: {stats}")

        # Test dequeue
        batches = await redis_queue.dequeue_batch(QUEUE_NAMES['live'], batch_size=1)
        if batches:
            logger.info(f"✓ Successfully dequeued {len(batches)} batch(es)")
            logger.info(
                f"  First batch contains {len(batches[0].get('points', []))} points")
        else:
            logger.info("No batches dequeued (queue might be empty)")

        return True

    except Exception as e:
        logger.error(f"✗ Test failed: {e}")
        return False

    finally:
        # Cleanup
        await redis_queue.close()
        logger.info("✓ Redis connection closed")


async def test_point_processor():
    """Test point processor functionality"""
    try:
        # Initialize Redis first
        await redis_queue.initialize()

        # Test processor stats
        stats = point_processor.get_stats()
        logger.info(f"✓ Processor stats: {stats}")

        return True

    except Exception as e:
        logger.error(f"✗ Processor test failed: {e}")
        return False

    finally:
        await redis_queue.close()


async def main():
    """Run all tests"""
    logger.info("Starting Redis queue system tests...")

    # Test Redis queue
    queue_test = await test_redis_queue()

    # Test point processor
    processor_test = await test_point_processor()

    if queue_test and processor_test:
        logger.info("✓ All tests passed!")
        return True
    else:
        logger.error("✗ Some tests failed!")
        return False

if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
