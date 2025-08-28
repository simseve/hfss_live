"""
Extensive stress testing for GPS TCP Server
Tests various attack vectors and edge cases
"""
import asyncio
import logging
import random
import string
import time
from datetime import datetime
from typing import List, Optional
import hashlib

logger = logging.getLogger(__name__)


class StressTestClient:
    """Stress test client for GPS TCP server"""
    
    def __init__(self, host='localhost', port=9091, client_id=None):
        self.host = host
        self.port = port
        self.client_id = client_id or random.randint(1000, 9999)
        self.reader = None
        self.writer = None
        self.connected = False
        self.messages_sent = 0
        self.responses_received = 0
        
    async def connect(self):
        """Connect to server"""
        try:
            self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
            self.connected = True
            logger.debug(f"Client {self.client_id} connected")
            return True
        except Exception as e:
            logger.error(f"Client {self.client_id} connection failed: {e}")
            return False
            
    async def disconnect(self):
        """Disconnect from server"""
        if self.writer:
            self.writer.close()
            await self.writer.wait_closed()
            self.connected = False
            logger.debug(f"Client {self.client_id} disconnected")
            
    async def send_raw(self, data: bytes, expect_response=True):
        """Send raw data to server"""
        if not self.connected:
            return None
            
        try:
            self.writer.write(data)
            await self.writer.drain()
            self.messages_sent += 1
            
            if expect_response:
                try:
                    response = await asyncio.wait_for(self.reader.read(1024), timeout=1.0)
                    self.responses_received += 1
                    return response
                except asyncio.TimeoutError:
                    return None
        except Exception as e:
            logger.error(f"Send error: {e}")
            self.connected = False
            return None
            
    async def send_message(self, message: str, expect_response=True):
        """Send string message"""
        return await self.send_raw(message.encode('utf-8'), expect_response)


class MaliciousTests:
    """Test cases designed to break the server"""
    
    @staticmethod
    async def test_flood_connections(host, port, count=100):
        """Flood server with connections"""
        logger.info(f"=== Flood Test: {count} connections ===")
        clients = []
        
        for i in range(count):
            client = StressTestClient(host, port, f"flood_{i}")
            if await client.connect():
                clients.append(client)
            await asyncio.sleep(0.01)  # Small delay
            
        logger.info(f"Connected {len(clients)}/{count} clients")
        
        # Keep connections open for a bit
        await asyncio.sleep(2)
        
        # Disconnect all
        for client in clients:
            await client.disconnect()
            
        return len(clients) > 0
        
    @staticmethod
    async def test_rapid_reconnect(host, port, iterations=50):
        """Rapidly connect and disconnect"""
        logger.info(f"=== Rapid Reconnect Test: {iterations} iterations ===")
        client = StressTestClient(host, port, "rapid_reconnect")
        
        for i in range(iterations):
            await client.connect()
            await asyncio.sleep(0.1)
            await client.disconnect()
            await asyncio.sleep(0.1)
            
        return True
        
    @staticmethod
    async def test_malformed_packets(host, port):
        """Send various malformed packets"""
        logger.info("=== Malformed Packets Test ===")
        client = StressTestClient(host, port, "malformed")
        
        if not await client.connect():
            return False
            
        malformed_packets = [
            b"",  # Empty
            b"\x00\x01\x02\x03",  # Binary garbage
            b"[" * 1000,  # Unclosed brackets
            b"(" * 1000 + b")",  # Mismatched parentheses
            b"[3G*123*]",  # Missing data
            b"[3G*abc*0010*UD2,,,,,,,]",  # Invalid device ID
            b"A" * 5000,  # Oversized message
            b"[3G*123*0010*\x00\x01\x02]",  # Control characters
            b"[3G*123*0010*UD2," + b"X" * 1000 + b"]",  # Oversized fields
            b"\r\n\r\n\r\n",  # Multiple newlines
            b"[[[[]]]]",  # Nested brackets
            b"(((())))",  # Nested parentheses
            b"[3G*123*0010*UD2,999999,999999,A,999.9999,N,999.9999,E,0,0,0]",  # Invalid coordinates
            b"[3G*" + b"9" * 100 + b"*0010*UD2]",  # Huge device ID
            b"<%><?php?>",  # Injection attempt
            b"'; DROP TABLE gps;--",  # SQL injection attempt
        ]
        
        for i, packet in enumerate(malformed_packets):
            logger.debug(f"Sending malformed packet {i+1}: {packet[:50]}")
            await client.send_raw(packet, expect_response=False)
            await asyncio.sleep(0.1)
            
        await client.disconnect()
        return True
        
    @staticmethod
    async def test_rate_limiting(host, port):
        """Test rate limiting by sending rapid messages"""
        logger.info("=== Rate Limiting Test ===")
        client = StressTestClient(host, port, "rate_limit")
        
        if not await client.connect():
            return False
            
        device_id = "9999999999"
        
        # Send rapid messages from same device
        for i in range(30):
            now = datetime.now()
            message = f"[3G*{device_id}*0079*UD2,{now.strftime('%d%m%y')},{now.strftime('%H%M%S')},A,40.7128,N,74.0060,W,10.0,180.0,100.0,8,90,85,0,0,00000008]"
            response = await client.send_message(message)
            
            if response and b"FAIL" in response:
                logger.info(f"Rate limit triggered after {i+1} messages")
                break
                
            await asyncio.sleep(0.2)  # Send every 200ms (faster than allowed)
            
        await client.disconnect()
        return True
        
    @staticmethod
    async def test_duplicate_messages(host, port):
        """Test duplicate/retransmission handling"""
        logger.info("=== Duplicate Messages Test ===")
        client = StressTestClient(host, port, "duplicate")
        
        if not await client.connect():
            return False
            
        # Same message multiple times
        message = "[3G*8888888888*0079*UD2,010125,120000,A,51.5074,N,0.1278,W,5.0,90.0,50.0,10,95,90,0,0,00000001]"
        
        responses = []
        for i in range(5):
            response = await client.send_message(message)
            responses.append(response)
            logger.debug(f"Duplicate {i+1}: {response}")
            await asyncio.sleep(0.5)
            
        await client.disconnect()
        return all(r is not None for r in responses)
        
    @staticmethod
    async def test_buffer_overflow(host, port):
        """Try to overflow connection buffer"""
        logger.info("=== Buffer Overflow Test ===")
        client = StressTestClient(host, port, "overflow")
        
        if not await client.connect():
            return False
            
        # Send data without delimiters to fill buffer
        huge_data = b"A" * 10000  # 10KB of data
        await client.send_raw(huge_data, expect_response=False)
        
        # Check if connection still works
        await asyncio.sleep(1)
        test_message = "[3G*7777777777*0010*HEART,100]"
        response = await client.send_message(test_message)
        
        await client.disconnect()
        return response is None  # Should be disconnected
        
    @staticmethod
    async def test_protocol_switching(host, port):
        """Switch between protocols mid-connection"""
        logger.info("=== Protocol Switching Test ===")
        client = StressTestClient(host, port, "switch")
        
        if not await client.connect():
            return False
            
        # Send watch protocol
        watch_msg = "[3G*6666666666*0008*LK,0,0,100]"
        await client.send_message(watch_msg)
        
        # Switch to TK103
        tk103_msg = "(5555555555,BP05,5555555555,101214,V,0000.0000N,00000.0000E,000.0,193148,000.0)"
        await client.send_message(tk103_msg)
        
        # Back to watch
        await client.send_message(watch_msg)
        
        await client.disconnect()
        return True
        
    @staticmethod
    async def test_long_idle_connection(host, port):
        """Keep connection idle to test timeout"""
        logger.info("=== Idle Connection Test ===")
        client = StressTestClient(host, port, "idle")
        
        if not await client.connect():
            return False
            
        logger.info("Keeping connection idle for 6 minutes...")
        await asyncio.sleep(360)  # 6 minutes (> 5 min timeout)
        
        # Try to send after timeout
        message = "[3G*4444444444*0010*HEART,100]"
        response = await client.send_message(message)
        
        await client.disconnect()
        return response is None  # Should be timed out
        
    @staticmethod
    async def test_concurrent_device_ids(host, port):
        """Multiple connections claiming same device ID"""
        logger.info("=== Concurrent Device ID Test ===")
        
        clients = []
        device_id = "3333333333"
        
        # Connect multiple clients with same device ID
        for i in range(5):
            client = StressTestClient(host, port, f"concurrent_{i}")
            if await client.connect():
                clients.append(client)
                
                # Send login with same device ID
                message = f"[3G*{device_id}*0008*LK,0,0,100]"
                await client.send_message(message)
                
        await asyncio.sleep(2)
        
        # All should still be connected
        for client in clients:
            await client.disconnect()
            
        return len(clients) > 0


class NormalLoadTest:
    """Simulate normal GPS tracker behavior"""
    
    @staticmethod
    async def simulate_gps_tracker(host, port, device_id, duration=60):
        """Simulate a real GPS tracker"""
        client = StressTestClient(host, port, f"gps_{device_id}")
        
        if not await client.connect():
            return False
            
        start_time = time.time()
        locations_sent = 0
        
        # Send login
        login = f"[3G*{device_id}*0008*LK,0,0,100]"
        await client.send_message(login)
        
        while time.time() - start_time < duration:
            # Send GPS location every 5-10 seconds
            await asyncio.sleep(random.uniform(5, 10))
            
            now = datetime.now()
            lat = 37.7749 + random.uniform(-0.01, 0.01)
            lon = 122.4194 + random.uniform(-0.01, 0.01)
            speed = random.uniform(0, 60)
            heading = random.uniform(0, 360)
            battery = random.randint(70, 100)
            
            message = f"[3G*{device_id}*0079*UD2,{now.strftime('%d%m%y')},{now.strftime('%H%M%S')},A,{lat:.4f},N,{lon:.4f},W,{speed:.1f},{heading:.1f},100.0,8,{battery},85,0,0,00000008]"
            
            response = await client.send_message(message)
            if response:
                locations_sent += 1
                
        await client.disconnect()
        logger.info(f"Device {device_id} sent {locations_sent} locations")
        return locations_sent > 0
        
    @staticmethod
    async def test_multiple_trackers(host, port, count=20, duration=30):
        """Simulate multiple GPS trackers"""
        logger.info(f"=== Multiple Trackers Test: {count} devices for {duration}s ===")
        
        tasks = []
        for i in range(count):
            device_id = f"{2000000000 + i}"
            task = asyncio.create_task(
                NormalLoadTest.simulate_gps_tracker(host, port, device_id, duration)
            )
            tasks.append(task)
            await asyncio.sleep(0.2)  # Stagger connections
            
        results = await asyncio.gather(*tasks)
        successful = sum(1 for r in results if r)
        
        logger.info(f"Successful trackers: {successful}/{count}")
        return successful > count * 0.8  # At least 80% success


async def run_all_tests(host='localhost', port=9091):
    """Run all stress tests"""
    logger.info("=" * 50)
    logger.info("Starting GPS TCP Server Stress Tests")
    logger.info("=" * 50)
    
    results = {}
    
    # Malicious tests
    logger.info("\n### MALICIOUS TESTS ###")
    
    tests = [
        ("Flood Connections", MaliciousTests.test_flood_connections(host, port, 50)),
        ("Rapid Reconnect", MaliciousTests.test_rapid_reconnect(host, port, 20)),
        ("Malformed Packets", MaliciousTests.test_malformed_packets(host, port)),
        ("Rate Limiting", MaliciousTests.test_rate_limiting(host, port)),
        ("Duplicate Messages", MaliciousTests.test_duplicate_messages(host, port)),
        ("Buffer Overflow", MaliciousTests.test_buffer_overflow(host, port)),
        ("Protocol Switching", MaliciousTests.test_protocol_switching(host, port)),
        ("Concurrent Device IDs", MaliciousTests.test_concurrent_device_ids(host, port)),
    ]
    
    for name, test_coro in tests:
        try:
            result = await test_coro
            results[name] = "PASS" if result else "FAIL"
            logger.info(f"{name}: {results[name]}")
        except Exception as e:
            results[name] = f"ERROR: {e}"
            logger.error(f"{name}: {results[name]}")
        
        await asyncio.sleep(2)  # Pause between tests
    
    # Normal load test
    logger.info("\n### LOAD TESTS ###")
    
    try:
        result = await NormalLoadTest.test_multiple_trackers(host, port, 10, 20)
        results["Multiple Trackers"] = "PASS" if result else "FAIL"
        logger.info(f"Multiple Trackers: {results['Multiple Trackers']}")
    except Exception as e:
        results["Multiple Trackers"] = f"ERROR: {e}"
        logger.error(f"Multiple Trackers: {results['Multiple Trackers']}")
    
    # Skip long idle test in automated run (uncomment to test)
    # result = await MaliciousTests.test_long_idle_connection(host, port)
    # results["Idle Timeout"] = "PASS" if result else "FAIL"
    
    # Summary
    logger.info("\n" + "=" * 50)
    logger.info("TEST SUMMARY")
    logger.info("=" * 50)
    
    passed = sum(1 for r in results.values() if r == "PASS")
    failed = sum(1 for r in results.values() if r == "FAIL")
    errors = sum(1 for r in results.values() if "ERROR" in str(r))
    
    for test_name, result in results.items():
        status = "✅" if result == "PASS" else "❌"
        logger.info(f"{status} {test_name}: {result}")
    
    logger.info(f"\nTotal: {len(results)} tests")
    logger.info(f"Passed: {passed}")
    logger.info(f"Failed: {failed}")
    logger.info(f"Errors: {errors}")
    
    return passed > len(results) * 0.7  # 70% pass rate


async def continuous_stress_test(host='localhost', port=9091, duration=300):
    """Run continuous stress test for specified duration"""
    logger.info(f"Running continuous stress test for {duration} seconds")
    
    start_time = time.time()
    iteration = 0
    
    while time.time() - start_time < duration:
        iteration += 1
        logger.info(f"\n### ITERATION {iteration} ###")
        
        # Run random stress test
        test_choice = random.choice([
            MaliciousTests.test_flood_connections(host, port, 20),
            MaliciousTests.test_rapid_reconnect(host, port, 10),
            MaliciousTests.test_malformed_packets(host, port),
            MaliciousTests.test_rate_limiting(host, port),
            NormalLoadTest.test_multiple_trackers(host, port, 5, 10),
        ])
        
        try:
            await test_choice
        except Exception as e:
            logger.error(f"Test failed: {e}")
        
        await asyncio.sleep(5)
    
    logger.info(f"Continuous stress test completed: {iteration} iterations")


def main():
    """Main entry point"""
    import sys
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Parse arguments
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    host = sys.argv[2] if len(sys.argv) > 2 else "localhost"
    port = int(sys.argv[3]) if len(sys.argv) > 3 else 9091
    
    if mode == "continuous":
        duration = int(sys.argv[4]) if len(sys.argv) > 4 else 300
        asyncio.run(continuous_stress_test(host, port, duration))
    else:
        asyncio.run(run_all_tests(host, port))


if __name__ == "__main__":
    main()