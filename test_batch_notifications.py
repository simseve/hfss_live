#!/usr/bin/env python3
"""
Test script for batch push notifications with Expo SDK

This script demonstrates how the new batch notification system works
compared to the previous individual sending approach.
"""

import asyncio
import time
from unittest.mock import Mock, AsyncMock
from exponent_server_sdk import PushMessage, PushClient

# Mock function to simulate the old individual sending approach


async def send_individual_notifications(tokens, title, message, extra_data=None):
    """Simulate the old approach of sending notifications one by one"""
    start_time = time.time()

    print(f"🔄 Sending {len(tokens)} notifications individually...")

    tickets = []
    errors = []

    for i, token in enumerate(tokens):
        try:
            # Simulate network delay for each individual request
            await asyncio.sleep(0.1)  # 100ms per request

            # Mock successful response
            ticket = {"status": "ok", "id": f"ticket_{i}"}
            tickets.append(ticket)

            if i % 10 == 0:
                print(f"  Sent {i + 1}/{len(tokens)} notifications...")

        except Exception as e:
            errors.append({"token": token[:10] + "...", "error": str(e)})

    end_time = time.time()
    duration = end_time - start_time

    print(f"✅ Individual sending completed in {duration:.2f}s")
    print(
        f"   Success rate: {len(tickets)}/{len(tokens)} ({len(tickets)/len(tokens)*100:.1f}%)")

    return tickets, errors, duration

# Mock function to simulate the new batch sending approach


async def send_batch_notifications(tokens, title, message, extra_data=None, batch_size=100):
    """Simulate the new batch approach"""
    start_time = time.time()

    print(
        f"🚀 Sending {len(tokens)} notifications in batches of {batch_size}...")

    tickets = []
    errors = []

    for i in range(0, len(tokens), batch_size):
        batch_tokens = tokens[i:i + batch_size]
        batch_num = (i // batch_size) + 1
        total_batches = (len(tokens) + batch_size - 1) // batch_size

        print(
            f"  Processing batch {batch_num}/{total_batches} ({len(batch_tokens)} tokens)...")

        try:
            # Simulate batch network request (much faster than individual)
            await asyncio.sleep(0.2)  # 200ms per batch regardless of size

            # Mock successful batch response
            batch_tickets = [{"status": "ok", "id": f"batch_{batch_num}_ticket_{j}"}
                             for j in range(len(batch_tokens))]
            tickets.extend(batch_tickets)

            # Small delay between batches to respect rate limits
            if i + batch_size < len(tokens):
                await asyncio.sleep(0.1)

        except Exception as e:
            # Mock error handling
            for token in batch_tokens:
                errors.append({"token": token[:10] + "...", "error": str(e)})

    end_time = time.time()
    duration = end_time - start_time

    print(f"✅ Batch sending completed in {duration:.2f}s")
    print(
        f"   Success rate: {len(tickets)}/{len(tokens)} ({len(tickets)/len(tokens)*100:.1f}%)")

    return tickets, errors, duration


async def main():
    """Compare individual vs batch notification sending"""
    print("🧪 Testing Push Notification Performance: Individual vs Batch")
    print("=" * 60)

    # Test with different numbers of recipients
    test_cases = [10, 50, 100, 250, 500]

    for num_tokens in test_cases:
        print(f"\n📊 Test Case: {num_tokens} recipients")
        print("-" * 40)

        # Generate mock tokens
        tokens = [
            f"ExponentPushToken[{'x' * 20}_{i}]" for i in range(num_tokens)]

        # Test individual sending
        individual_tickets, individual_errors, individual_time = await send_individual_notifications(
            tokens, "Test Title", "Test Message", {"priority": "normal"}
        )

        print()

        # Test batch sending
        batch_tickets, batch_errors, batch_time = await send_batch_notifications(
            tokens, "Test Title", "Test Message", {"priority": "normal"}
        )

        # Calculate improvement
        time_saved = individual_time - batch_time
        improvement_percent = (
            (individual_time - batch_time) / individual_time) * 100

        print(f"\n📈 Performance Improvement:")
        print(
            f"   Time saved: {time_saved:.2f}s ({improvement_percent:.1f}% faster)")
        print(
            f"   Throughput: {num_tokens/batch_time:.1f} notifications/second (batch) vs {num_tokens/individual_time:.1f}/second (individual)")

        if num_tokens < len(test_cases):
            print("\n" + "=" * 60)

if __name__ == "__main__":
    print("🚀 Expo SDK Batch Notifications Performance Test")
    print("This test simulates the performance difference between individual")
    print("and batch notification sending approaches.\n")

    asyncio.run(main())

    print("\n" + "=" * 60)
    print("✨ Key Benefits of Batch Notifications:")
    print("   • Significantly faster sending times")
    print("   • Reduced API calls to Expo servers")
    print("   • Better rate limit compliance")
    print("   • Improved reliability with automatic fallback")
    print("   • Lower server resource usage")
    print("   • Built-in error handling per batch")
