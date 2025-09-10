#!/usr/bin/env python3
"""Test script to verify rate limiter IP extraction"""

from fastapi import Request
from rate_limiter import get_real_client_ip
import logging

logging.basicConfig(level=logging.DEBUG)

# Mock request with different header scenarios
class MockRequest:
    def __init__(self, headers, client_host="172.27.0.1"):
        self.headers = headers
        self.client = type('Client', (), {'host': client_host})()

# Test 1: X-Forwarded-For header (typical proxy scenario)
print("\nTest 1: X-Forwarded-For header")
req1 = MockRequest({"X-Forwarded-For": "203.0.113.1, 172.27.0.1"})
ip1 = get_real_client_ip(req1)
print(f"Extracted IP: {ip1}")
assert ip1 == "203.0.113.1", f"Expected 203.0.113.1, got {ip1}"

# Test 2: X-Real-IP header (nginx scenario)
print("\nTest 2: X-Real-IP header")
req2 = MockRequest({"X-Real-IP": "198.51.100.42"})
ip2 = get_real_client_ip(req2)
print(f"Extracted IP: {ip2}")
assert ip2 == "198.51.100.42", f"Expected 198.51.100.42, got {ip2}"

# Test 3: Both headers present (X-Forwarded-For takes precedence)
print("\nTest 3: Both headers present")
req3 = MockRequest({
    "X-Forwarded-For": "192.0.2.1",
    "X-Real-IP": "198.51.100.42"
})
ip3 = get_real_client_ip(req3)
print(f"Extracted IP: {ip3}")
assert ip3 == "192.0.2.1", f"Expected 192.0.2.1, got {ip3}"

# Test 4: No proxy headers (fallback to client host)
print("\nTest 4: No proxy headers (direct connection)")
req4 = MockRequest({}, client_host="10.0.0.5")
ip4 = get_real_client_ip(req4)
print(f"Extracted IP: {ip4}")
assert ip4 == "10.0.0.5", f"Expected 10.0.0.5, got {ip4}"

print("\n✅ All tests passed! Rate limiter will now use real client IPs.")