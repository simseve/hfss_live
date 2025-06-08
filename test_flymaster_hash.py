#!/usr/bin/env python3
"""
Test script to verify Flymaster standard SHA256 hash generation and validation.
This script tests the authentication mechanism used in the Flymaster upload endpoint.
"""

import hashlib
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def generate_flymaster_hash(device_id, secret):
    """
    Generate standard SHA256 hash for Flymaster device authentication.

    Args:
        device_id: Device ID (as string or integer)
        secret: FLYMASTER_SECRET key

    Returns:
        str: SHA256 hash in hexadecimal format
    """
    # Convert device_id to string if it's an integer
    device_id_str = str(device_id)

    # Combine device_id and secret
    combined = device_id_str + secret

    # Generate standard SHA256 hash
    hash_obj = hashlib.sha256(combined.encode())

    return hash_obj.hexdigest()


def test_flymaster_authentication():
    """Test Flymaster authentication with provided values"""

    # Test data
    test_device_id = "123457"
    test_secret = "JijoHPvHXyHjajDK00V"
    expected_hash = "64e1d390354e3869bbc0453886cd36a1d453b8776ff40443e75bffcf9b2d810a"

    logger.info("🔍 Testing Flymaster Standard SHA256 Authentication")
    logger.info("="*60)
    logger.info(f"Device ID: {test_device_id}")
    logger.info(f"Secret: {test_secret}")
    logger.info(f"Combined: {test_device_id + test_secret}")
    logger.info(f"Expected Hash: {expected_hash}")
    logger.info("")

    # Generate hash
    generated_hash = generate_flymaster_hash(test_device_id, test_secret)

    logger.info(f"Generated Hash: {generated_hash}")
    logger.info("")

    # Compare hashes
    if generated_hash == expected_hash:
        logger.info("✅ SUCCESS: Hash matches expected value!")
        return True
    else:
        logger.error("❌ FAILURE: Hash does not match expected value!")
        logger.error(f"Expected: {expected_hash}")
        logger.error(f"Got:      {generated_hash}")
        return False


def test_additional_scenarios():
    """Test additional scenarios to understand the hash generation"""

    logger.info("\n🧪 Testing Additional Scenarios")
    logger.info("="*60)

    test_cases = [
        # Test with integer device_id
        {"device_id": 123457, "secret": "JijoHPvHXyHjajDK00V"},
        # Test with different device_id
        {"device_id": "123456", "secret": "JijoHPvHXyHjajDK00V"},
        {"device_id": "123458", "secret": "JijoHPvHXyHjajDK00V"},
        # Test with different secret (just to see different output)
        {"device_id": "123457", "secret": "DifferentSecret"},
    ]

    for i, case in enumerate(test_cases, 1):
        device_id = case["device_id"]
        secret = case["secret"]
        generated_hash = generate_flymaster_hash(device_id, secret)

        logger.info(f"Test Case {i}:")
        logger.info(
            f"  Device ID: {device_id} (type: {type(device_id).__name__})")
        logger.info(f"  Secret: {secret}")
        logger.info(f"  Hash: {generated_hash}")
        logger.info("")


def test_hash_components():
    """Break down the hash generation to understand each step"""

    logger.info("🔬 Hash Generation Breakdown")
    logger.info("="*60)

    device_id = "123457"
    secret = "JijoHPvHXyHjajDK00V"

    logger.info(f"1. Device ID (string): '{device_id}'")
    logger.info(f"2. Secret (string): '{secret}'")
    logger.info(f"3. Combined string: '{device_id + secret}'")
    logger.info(f"4. Combined (bytes): {(device_id + secret).encode()}")
    logger.info("")

    # Step by step hash generation
    combined = device_id + secret
    combined_bytes = combined.encode()

    logger.info("5. SHA256 Generation:")
    logger.info(f"   hashlib.sha256('{combined}'.encode())")

    hash_obj = hashlib.sha256(combined_bytes)
    hash_hex = hash_obj.hexdigest()

    logger.info(f"6. Final Hash: {hash_hex}")
    logger.info("")


def verify_against_expected():
    """Verify the exact hash against the expected value"""

    logger.info("🎯 Final Verification")
    logger.info("="*60)

    device_id = "123457"
    secret = "JijoHPvHXyHjajDK00V"
    expected = "64e1d390354e3869bbc0453886cd36a1d453b8776ff40443e75bffcf9b2d810a"

    # Generate using the exact same method as standard SHA256
    combined = device_id + secret
    generated = hashlib.sha256(combined.encode()).hexdigest()

    logger.info(f"Device ID: {device_id}")
    logger.info(f"Secret: {secret}")
    logger.info(f"Expected:  {expected}")
    logger.info(f"Generated: {generated}")
    logger.info(f"Match: {'✅ YES' if generated == expected else '❌ NO'}")

    if generated == expected:
        logger.info("\n🎉 AUTHENTICATION TEST PASSED!")
        logger.info("The hash generation is working correctly.")
    else:
        logger.error("\n⚠️  AUTHENTICATION TEST FAILED!")
        logger.error("There might be an issue with the hash generation.")

        # Additional debugging
        logger.info("\nDebugging information:")
        logger.info(f"Expected length: {len(expected)}")
        logger.info(f"Generated length: {len(generated)}")

        # Character by character comparison
        for i, (e, g) in enumerate(zip(expected, generated)):
            if e != g:
                logger.info(
                    f"First difference at position {i}: expected '{e}', got '{g}'")
                break

    return generated == expected


def main():
    """Run all tests"""
    logger.info("🚀 Flymaster Standard SHA256 Hash Test Suite")
    logger.info("="*80)

    # Test basic functionality
    success = test_flymaster_authentication()

    # Test hash breakdown
    test_hash_components()

    # Test additional scenarios
    test_additional_scenarios()

    # Final verification
    final_result = verify_against_expected()

    logger.info("\n" + "="*80)
    logger.info("📊 TEST SUMMARY")
    logger.info("="*80)
    logger.info(f"Basic Test: {'✅ PASSED' if success else '❌ FAILED'}")
    logger.info(
        f"Final Verification: {'✅ PASSED' if final_result else '❌ FAILED'}")

    if success and final_result:
        logger.info("\n🎉 ALL TESTS PASSED!")
        logger.info("The Flymaster authentication hash is working correctly.")
    else:
        logger.error("\n⚠️  SOME TESTS FAILED!")
        logger.error("Please check the hash generation logic.")

    return success and final_result


if __name__ == "__main__":
    main()
