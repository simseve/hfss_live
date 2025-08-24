#!/usr/bin/env python3
"""
Test script for async logging implementation.
"""
import logging
import time
import threading
from logs.logconfig import configure_logging
from config import settings

def test_logging_performance(use_async: bool, num_messages: int = 1000):
    """Test logging performance with sync vs async."""
    # Configure logging
    configure_logging("test-session", use_async=use_async)
    
    logger = logging.getLogger(__name__)
    
    # Test logging performance
    start_time = time.time()
    
    for i in range(num_messages):
        logger.info(f"Test message {i}: This is a test of {'async' if use_async else 'sync'} logging performance")
        if i % 100 == 0:
            logger.warning(f"Warning message at {i}")
        if i % 500 == 0:
            logger.error(f"Error message at {i}")
    
    elapsed = time.time() - start_time
    
    print(f"{'Async' if use_async else 'Sync'} logging: {num_messages} messages in {elapsed:.3f} seconds")
    print(f"Rate: {num_messages/elapsed:.1f} messages/second")
    
    return elapsed

def test_concurrent_logging(use_async: bool):
    """Test logging with multiple threads."""
    configure_logging("concurrent-test", use_async=use_async)
    
    def worker(thread_id: int, num_messages: int = 100):
        logger = logging.getLogger(f"worker-{thread_id}")
        for i in range(num_messages):
            logger.info(f"Thread {thread_id}: Message {i}")
    
    threads = []
    num_threads = 5
    
    start_time = time.time()
    
    for i in range(num_threads):
        t = threading.Thread(target=worker, args=(i, 100))
        t.start()
        threads.append(t)
    
    for t in threads:
        t.join()
    
    elapsed = time.time() - start_time
    print(f"{'Async' if use_async else 'Sync'} concurrent logging: {num_threads} threads completed in {elapsed:.3f} seconds")

if __name__ == "__main__":
    print("Testing Logging Performance")
    print("=" * 50)
    
    # Test with original PROD setting
    original_prod = settings.PROD
    
    # Test in development mode (sync only)
    print("\n1. Development Mode (PROD=False, sync only):")
    settings.PROD = False
    sync_time_dev = test_logging_performance(use_async=False, num_messages=500)
    
    # Test in production mode
    print("\n2. Production Mode (PROD=True):")
    settings.PROD = True
    
    print("\n2a. Synchronous logging:")
    sync_time = test_logging_performance(use_async=False, num_messages=1000)
    
    print("\n2b. Asynchronous logging:")
    async_time = test_logging_performance(use_async=True, num_messages=1000)
    
    if async_time > 0:
        improvement = ((sync_time - async_time) / sync_time) * 100
        print(f"\nPerformance improvement: {improvement:.1f}%")
    
    print("\n3. Concurrent Logging Test:")
    print("\n3a. Synchronous:")
    test_concurrent_logging(use_async=False)
    
    print("\n3b. Asynchronous:")
    test_concurrent_logging(use_async=True)
    
    # Restore original setting
    settings.PROD = original_prod
    
    print("\n" + "=" * 50)
    print("Testing complete!")
    
    # Give async logger time to flush
    time.sleep(1)