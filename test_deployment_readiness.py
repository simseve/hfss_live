#!/usr/bin/env python3
"""
Test deployment readiness with reduced Redis connections
"""
import asyncio
import aiohttp
import json
import time
from datetime import datetime

async def test_health_endpoint():
    """Test the health check endpoint"""
    print("\n🏥 Testing Health Endpoint")
    print("=" * 50)
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get('http://localhost:8001/health') as resp:
                data = await resp.json()
                status_code = resp.status
                
                print(f"Status Code: {status_code}")
                print(f"System Status: {data.get('status')}")
                print(f"Database: {data.get('database', {}).get('status')}")
                print(f"Redis: {data.get('redis', {}).get('status')}")
                
                # Check Redis connection pool
                pool_info = data.get('redis', {}).get('connection_pool', {})
                if pool_info:
                    print(f"\nRedis Connection Pool:")
                    print(f"  Created: {pool_info.get('created_connections', 'N/A')}")
                    print(f"  Available: {pool_info.get('available_connections', 'N/A')}")
                    print(f"  In Use: {pool_info.get('in_use_connections', 'N/A')}")
                    print(f"  Max: {pool_info.get('max_connections', 'N/A')}")
                
                return status_code == 200
        except Exception as e:
            print(f"❌ Health check failed: {e}")
            return False

async def test_concurrent_requests(num_requests=15):
    """Test system with concurrent requests"""
    print(f"\n🔄 Testing {num_requests} Concurrent Requests")
    print("=" * 50)
    
    async with aiohttp.ClientSession() as session:
        # Create concurrent requests
        tasks = []
        for i in range(num_requests):
            tasks.append(session.get('http://localhost:8001/health'))
        
        start = time.time()
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        elapsed = time.time() - start
        
        # Analyze results
        successful = 0
        failed = 0
        errors = []
        
        for i, resp in enumerate(responses):
            if isinstance(resp, Exception):
                failed += 1
                errors.append(str(resp))
            elif hasattr(resp, 'status'):
                if resp.status == 200:
                    successful += 1
                else:
                    failed += 1
                    try:
                        data = await resp.json()
                        errors.append(f"Status {resp.status}: {data}")
                    except:
                        errors.append(f"Status {resp.status}")
                if hasattr(resp, 'close'):
                    resp.close()
        
        print(f"✅ Successful: {successful}/{num_requests}")
        print(f"❌ Failed: {failed}/{num_requests}")
        print(f"⏱️ Time: {elapsed:.2f} seconds")
        print(f"📊 Avg response time: {elapsed/num_requests*1000:.0f}ms")
        
        if errors:
            print("\nErrors:")
            for err in errors[:5]:  # Show first 5 errors
                print(f"  - {err}")
        
        return failed == 0

async def test_queue_operations():
    """Test queue operations with reduced connections"""
    print("\n📨 Testing Queue Operations")
    print("=" * 50)
    
    async with aiohttp.ClientSession() as session:
        # Test queue status
        try:
            async with session.get('http://localhost:8001/queue/status') as resp:
                if resp.status == 200:
                    data = await resp.json()
                    print("Queue Status: ✅ Accessible")
                    for queue_type, stats in data.get('queues', {}).items():
                        print(f"  {queue_type}: {stats.get('total_pending', 0)} pending")
                else:
                    print(f"Queue Status: ❌ Status {resp.status}")
                    return False
        except Exception as e:
            print(f"Queue Status: ❌ {e}")
            return False
        
        # Test adding points to queue
        test_data = {
            "points": [
                {"lat": 47.0, "lon": 8.0, "elevation": 500}
            ],
            "flight_id": "test_flight",
            "tracking_token": "test_token"
        }
        
        try:
            async with session.post(
                'http://localhost:8001/api/v2/live/add_live_track_points',
                json=test_data
            ) as resp:
                if resp.status in [200, 201]:
                    print("Queue Write: ✅ Successful")
                else:
                    print(f"Queue Write: ❌ Status {resp.status}")
                    return False
        except Exception as e:
            print(f"Queue Write: ❌ {e}")
            return False
        
        return True

async def stress_test_connections():
    """Stress test with connection limit"""
    print("\n⚡ Stress Testing Connection Limit")
    print("=" * 50)
    
    print("Creating 20 concurrent connections (double the limit)...")
    
    async with aiohttp.ClientSession() as session:
        tasks = []
        for i in range(20):
            tasks.append(session.get('http://localhost:8001/health'))
        
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        
        successful = sum(1 for r in responses if not isinstance(r, Exception) and r.status == 200)
        failed = 20 - successful
        
        print(f"Results with 20 concurrent requests:")
        print(f"  ✅ Successful: {successful}/20")
        print(f"  ❌ Failed: {failed}/20")
        
        if failed > 0:
            print("\n⚠️ Some requests failed - this is expected with connection limits")
            print("The system should recover gracefully")
        
        # Clean up responses
        for resp in responses:
            if hasattr(resp, 'close'):
                if hasattr(resp, 'close'):
                    resp.close()
        
        # Wait for recovery
        await asyncio.sleep(2)
        
        # Test recovery
        print("\nTesting recovery after stress...")
        recovery_ok = await test_health_endpoint()
        
        if recovery_ok:
            print("✅ System recovered successfully")
            return True
        else:
            print("❌ System did not recover")
            return False

async def main():
    """Run all deployment readiness tests"""
    print("\n🚀 DEPLOYMENT READINESS TEST")
    print("=" * 50)
    print("Testing with REDIS_MAX_CONNECTIONS=10")
    print(f"Timestamp: {datetime.now().isoformat()}")
    
    all_tests_passed = True
    
    # Test 1: Basic health check
    if not await test_health_endpoint():
        all_tests_passed = False
        print("❌ Basic health check failed")
    else:
        print("✅ Basic health check passed")
    
    await asyncio.sleep(1)
    
    # Test 2: Concurrent requests
    if not await test_concurrent_requests(10):
        all_tests_passed = False
        print("❌ Concurrent requests test failed")
    else:
        print("✅ Concurrent requests test passed")
    
    await asyncio.sleep(1)
    
    # Test 3: Queue operations
    if not await test_queue_operations():
        all_tests_passed = False
        print("❌ Queue operations test failed")
    else:
        print("✅ Queue operations test passed")
    
    await asyncio.sleep(1)
    
    # Test 4: Stress test
    if not await stress_test_connections():
        all_tests_passed = False
        print("❌ Stress test failed")
    else:
        print("✅ Stress test passed")
    
    # Final verdict
    print("\n" + "=" * 50)
    print("🎯 DEPLOYMENT READINESS VERDICT")
    print("=" * 50)
    
    if all_tests_passed:
        print("✅ READY FOR DEPLOYMENT")
        print("\nAll tests passed with reduced connection limit.")
        print("The system is stable and can handle concurrent load.")
    else:
        print("❌ NOT READY FOR DEPLOYMENT")
        print("\nSome tests failed. Please review the errors above.")
        print("Common issues:")
        print("- Redis connection pool exhaustion")
        print("- Database connection timeouts")
        print("- Queue processing bottlenecks")
    
    print("\n📊 Recommendations:")
    print("1. Monitor Redis connection pool usage in production")
    print("2. Set up alerts for connection pool exhaustion")
    print("3. Consider implementing circuit breakers")
    print("4. Use connection pooling for all external services")

if __name__ == "__main__":
    asyncio.run(main())