#!/usr/bin/env python3
"""
Comprehensive stress test to find system capacity limits
Tests Redis connections, queue throughput, and processing capacity
"""
import asyncio
import aiohttp
import time
import json
import uuid
import psutil
import os
from datetime import datetime, timezone
from typing import Dict, List
from redis.asyncio import Redis
from config import settings
import multiprocessing
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor

class CapacityStressTester:
    def __init__(self):
        self.base_url = "http://localhost:8001"
        self.metrics = {
            'max_concurrent_redis': 0,
            'max_queue_throughput': 0,
            'max_processing_rate': 0,
            'connection_errors': 0,
            'total_points_queued': 0,
            'total_points_processed': 0,
            'peak_memory_mb': 0,
            'peak_cpu_percent': 0
        }
        self.active_connections = []
        
    async def monitor_system_resources(self, duration: int = 60):
        """Monitor CPU and memory usage during test"""
        process = psutil.Process(os.getpid())
        start_time = time.time()
        
        while time.time() - start_time < duration:
            try:
                cpu_percent = process.cpu_percent(interval=0.1)
                memory_mb = process.memory_info().rss / 1024 / 1024
                
                self.metrics['peak_cpu_percent'] = max(self.metrics['peak_cpu_percent'], cpu_percent)
                self.metrics['peak_memory_mb'] = max(self.metrics['peak_memory_mb'], memory_mb)
                
                await asyncio.sleep(1)
            except:
                break
    
    async def test_redis_connection_limit(self):
        """Test 1: Find maximum concurrent Redis connections"""
        print("\n🔴 Test 1: Redis Connection Limit")
        print("-" * 40)
        
        redis_url = settings.get_redis_url()
        connections = []
        max_successful = 0
        
        try:
            for i in range(100):  # Try to create 100 connections
                try:
                    conn = await Redis.from_url(redis_url, decode_responses=True, 
                                               socket_connect_timeout=2,
                                               socket_timeout=2)
                    await conn.ping()
                    connections.append(conn)
                    max_successful = i + 1
                    
                    if (i + 1) % 10 == 0:
                        print(f"  ✅ Created {i + 1} concurrent Redis connections")
                        
                except Exception as e:
                    print(f"  ❌ Failed at connection {i + 1}: {str(e)[:50]}")
                    self.metrics['connection_errors'] += 1
                    break
            
            self.metrics['max_concurrent_redis'] = max_successful
            print(f"\n  📊 Maximum concurrent Redis connections: {max_successful}")
            
        finally:
            # Clean up connections
            for conn in connections:
                try:
                    await conn.aclose()
                except:
                    pass
        
        return max_successful
    
    async def test_queue_throughput(self):
        """Test 2: Maximum queue throughput"""
        print("\n📨 Test 2: Queue Throughput Capacity")
        print("-" * 40)
        
        redis_url = settings.get_redis_url()
        redis = await Redis.from_url(redis_url, decode_responses=True,
                                    max_connections=50)  # Use higher pool
        
        try:
            # Clear queue first
            await redis.delete("queue:stress_test")
            
            # Test different batch sizes
            test_configs = [
                (100, 100),   # 100 batches of 100 points
                (500, 100),   # 500 batches of 100 points
                (1000, 100),  # 1000 batches of 100 points
                (100, 1000),  # 100 batches of 1000 points
            ]
            
            best_throughput = 0
            best_config = None
            
            for num_batches, points_per_batch in test_configs:
                await redis.delete("queue:stress_test")
                
                print(f"\n  Testing: {num_batches} batches × {points_per_batch} points")
                
                # Generate test data
                tasks = []
                start = time.time()
                
                for i in range(num_batches):
                    points = []
                    for j in range(points_per_batch):
                        point = {
                            'datetime': datetime.now(timezone.utc).isoformat(),
                            'lat': 47.0 + (i * 0.0001),
                            'lon': 8.0 + (i * 0.0001),
                            'elevation': 500 + j
                        }
                        points.append(point)
                    
                    item = {
                        'points': points,
                        'timestamp': datetime.now(timezone.utc).isoformat(),
                        'batch_id': i
                    }
                    
                    task = redis.zadd("queue:stress_test", {json.dumps(item): i})
                    tasks.append(task)
                
                # Execute all tasks concurrently
                await asyncio.gather(*tasks, return_exceptions=True)
                
                elapsed = time.time() - start
                total_points = num_batches * points_per_batch
                throughput = total_points / elapsed
                
                print(f"    Time: {elapsed:.2f}s")
                print(f"    Throughput: {throughput:.0f} points/sec")
                
                if throughput > best_throughput:
                    best_throughput = throughput
                    best_config = (num_batches, points_per_batch)
                
                self.metrics['total_points_queued'] += total_points
                
                # Small delay between tests
                await asyncio.sleep(1)
            
            self.metrics['max_queue_throughput'] = best_throughput
            print(f"\n  📊 Best throughput: {best_throughput:.0f} points/sec")
            print(f"     Configuration: {best_config[0]} batches × {best_config[1]} points")
            
        finally:
            await redis.aclose()
    
    async def test_concurrent_api_load(self):
        """Test 3: API endpoint concurrency limit"""
        print("\n🌐 Test 3: API Concurrency Limit")
        print("-" * 40)
        
        async def make_request(session, endpoint, method='GET', **kwargs):
            try:
                async with session.request(method, f"{self.base_url}{endpoint}", **kwargs) as resp:
                    return resp.status, await resp.text()
            except Exception as e:
                return None, str(e)
        
        # Test different concurrency levels
        test_levels = [10, 50, 100, 200, 500]
        best_rps = 0
        
        for concurrent_requests in test_levels:
            print(f"\n  Testing {concurrent_requests} concurrent requests")
            
            async with aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(limit=concurrent_requests)
            ) as session:
                tasks = []
                start = time.time()
                
                for i in range(concurrent_requests):
                    # Mix of different endpoints
                    if i % 3 == 0:
                        task = make_request(session, '/health')
                    elif i % 3 == 1:
                        task = make_request(session, '/admin/queue/stats')
                    else:
                        task = make_request(session, '/admin/queue/health')
                    
                    tasks.append(task)
                
                results = await asyncio.gather(*tasks)
                elapsed = time.time() - start
                
                successful = sum(1 for status, _ in results if status == 200)
                failed = concurrent_requests - successful
                rps = successful / elapsed
                
                print(f"    Success: {successful}/{concurrent_requests}")
                print(f"    RPS: {rps:.1f}")
                
                if failed > concurrent_requests * 0.1:  # More than 10% failure
                    print(f"    ⚠️  High failure rate, stopping at this level")
                    break
                
                if rps > best_rps:
                    best_rps = rps
        
        self.metrics['max_api_rps'] = best_rps
        print(f"\n  📊 Maximum sustained RPS: {best_rps:.1f}")
    
    async def test_processing_capacity(self):
        """Test 4: Processing capacity with valid data"""
        print("\n⚡ Test 4: Processing Capacity")
        print("-" * 40)
        
        # First create a valid flight for testing
        from database.db_conf import Session
        from database.models import Race, Flight
        
        with Session() as db:
            # Create test race
            race = Race(
                id=uuid.uuid4(),
                race_id=f"stress-race-{uuid.uuid4().hex[:8]}",
                name="Stress Test Race",
                date=datetime.now(timezone.utc),
                end_date=datetime.now(timezone.utc),
                timezone="UTC",
                location="Test"
            )
            db.add(race)
            
            # Create test flight
            flight = Flight(
                id=uuid.uuid4(),
                flight_id=f"stress-flight-{uuid.uuid4().hex[:8]}",
                race_uuid=race.id,
                race_id=str(race.id),
                pilot_id="stress-pilot",
                pilot_name="Stress Test Pilot",
                source="live"
            )
            db.add(flight)
            db.commit()
            
            flight_uuid = str(flight.id)
            race_uuid = str(race.id)
        
        redis_url = settings.get_redis_url()
        redis = await Redis.from_url(redis_url, decode_responses=True)
        
        try:
            # Clear queues
            await redis.delete("queue:live_points")
            
            # Queue a large amount of valid data
            num_batches = 200
            points_per_batch = 100
            
            print(f"  Queuing {num_batches * points_per_batch} valid points...")
            
            for i in range(num_batches):
                points = []
                for j in range(points_per_batch):
                    point = {
                        'datetime': datetime.now(timezone.utc).isoformat(),
                        'flight_uuid': flight_uuid,
                        'flight_id': f'flight-{flight_uuid[:8]}',
                        'lat': 47.0 + (i * 0.001) + (j * 0.00001),
                        'lon': 8.0 + (i * 0.001) + (j * 0.00001),
                        'elevation': 500 + j
                    }
                    points.append(point)
                
                item = {
                    'points': points,
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                    'count': len(points),
                    'queue_type': 'live_points'
                }
                
                await redis.zadd("queue:live_points", {json.dumps(item): i})
            
            print(f"  ✅ Queued {num_batches * points_per_batch} points")
            
            # Process with multiple concurrent requests
            print("\n  Processing with concurrent force-process calls...")
            
            async with aiohttp.ClientSession() as session:
                process_start = time.time()
                total_processed = 0
                concurrent_processors = 5
                
                while True:
                    tasks = []
                    for _ in range(concurrent_processors):
                        task = session.post(
                            f"{self.base_url}/admin/queue/force-process/live",
                            params={'batch_size': 500}
                        )
                        tasks.append(task)
                    
                    responses = await asyncio.gather(*tasks, return_exceptions=True)
                    
                    batch_processed = 0
                    for resp in responses:
                        if not isinstance(resp, Exception):
                            async with resp as r:
                                if r.status == 200:
                                    data = await r.json()
                                    batch_processed += data.get('items_retrieved', 0)
                    
                    total_processed += batch_processed
                    
                    if batch_processed == 0:
                        break
                    
                    print(f"    Processed batch: {batch_processed} items")
                
                process_time = time.time() - process_start
                processing_rate = total_processed / process_time if process_time > 0 else 0
                
                self.metrics['max_processing_rate'] = processing_rate
                self.metrics['total_points_processed'] = total_processed
                
                print(f"\n  📊 Processing complete:")
                print(f"     Total processed: {total_processed} items")
                print(f"     Time: {process_time:.2f}s")
                print(f"     Rate: {processing_rate:.0f} items/sec")
            
        finally:
            # Cleanup
            with Session() as db:
                db.query(Flight).filter(Flight.id == flight_uuid).delete()
                db.query(Race).filter(Race.id == race_uuid).delete()
                db.commit()
            
            await redis.aclose()
    
    async def test_parallel_workers(self):
        """Test 5: Multiple parallel queue workers"""
        print("\n👥 Test 5: Parallel Worker Capacity")
        print("-" * 40)
        
        async def worker(worker_id: int, num_operations: int):
            """Simulate a queue worker"""
            redis = await Redis.from_url(
                settings.get_redis_url(), 
                decode_responses=True
            )
            
            success_count = 0
            error_count = 0
            
            try:
                for i in range(num_operations):
                    try:
                        # Simulate queue operations
                        await redis.zadd(f"queue:worker_{worker_id}", {f"item_{i}": i})
                        await redis.zpopmin(f"queue:worker_{worker_id}")
                        success_count += 1
                    except Exception:
                        error_count += 1
                        
            finally:
                await redis.delete(f"queue:worker_{worker_id}")
                await redis.aclose()
            
            return worker_id, success_count, error_count
        
        # Test different numbers of workers
        test_configs = [5, 10, 20, 50]
        
        for num_workers in test_configs:
            print(f"\n  Testing {num_workers} parallel workers")
            
            start = time.time()
            tasks = []
            
            for i in range(num_workers):
                task = worker(i, 100)  # Each worker does 100 operations
                tasks.append(task)
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            elapsed = time.time() - start
            
            total_success = sum(s for _, s, _ in results if not isinstance(results, Exception))
            total_errors = sum(e for _, _, e in results if not isinstance(results, Exception))
            
            ops_per_second = total_success / elapsed
            
            print(f"    Success: {total_success} operations")
            print(f"    Errors: {total_errors}")
            print(f"    Ops/sec: {ops_per_second:.0f}")
            
            if total_errors > total_success * 0.1:
                print(f"    ⚠️  High error rate, stopping here")
                break
    
    async def run_all_tests(self):
        """Run all capacity tests"""
        print("=" * 60)
        print("🚀 SYSTEM CAPACITY STRESS TEST")
        print("=" * 60)
        
        # Start resource monitoring
        monitor_task = asyncio.create_task(self.monitor_system_resources(120))
        
        try:
            # Run tests
            await self.test_redis_connection_limit()
            await asyncio.sleep(2)
            
            await self.test_queue_throughput()
            await asyncio.sleep(2)
            
            await self.test_concurrent_api_load()
            await asyncio.sleep(2)
            
            await self.test_processing_capacity()
            await asyncio.sleep(2)
            
            await self.test_parallel_workers()
            
        finally:
            monitor_task.cancel()
        
        # Print summary
        print("\n" + "=" * 60)
        print("📊 CAPACITY TEST SUMMARY")
        print("=" * 60)
        
        print("\n🔴 Redis Capacity:")
        print(f"  Max concurrent connections: {self.metrics['max_concurrent_redis']}")
        print(f"  Connection errors: {self.metrics['connection_errors']}")
        
        print("\n📨 Queue Capacity:")
        print(f"  Max throughput: {self.metrics['max_queue_throughput']:.0f} points/sec")
        print(f"  Total queued: {self.metrics['total_points_queued']:,} points")
        
        print("\n⚡ Processing Capacity:")
        print(f"  Max processing rate: {self.metrics['max_processing_rate']:.0f} items/sec")
        print(f"  Total processed: {self.metrics['total_points_processed']:,} points")
        
        print("\n🌐 API Capacity:")
        print(f"  Max RPS: {self.metrics.get('max_api_rps', 0):.1f} requests/sec")
        
        print("\n💻 System Resources:")
        print(f"  Peak CPU: {self.metrics['peak_cpu_percent']:.1f}%")
        print(f"  Peak Memory: {self.metrics['peak_memory_mb']:.1f} MB")
        
        print("\n🎯 Recommendations:")
        if self.metrics['max_concurrent_redis'] < 50:
            print("  ⚠️  Redis connection limit is low. Consider:")
            print("     - Increasing max_connections in Redis config")
            print("     - Using connection pooling more efficiently")
        
        if self.metrics['max_queue_throughput'] < 5000:
            print("  ⚠️  Queue throughput could be improved. Consider:")
            print("     - Using pipelining for batch operations")
            print("     - Increasing Redis network buffer sizes")
        
        if self.metrics['max_processing_rate'] < 1000:
            print("  ⚠️  Processing rate is limited. Consider:")
            print("     - Using bulk insert operations")
            print("     - Adding more worker processes")
            print("     - Optimizing database indexes")


async def main():
    tester = CapacityStressTester()
    await tester.run_all_tests()


if __name__ == "__main__":
    print("⚠️  WARNING: This is an intensive stress test!")
    print("It will push the system to its limits.")
    response = input("Continue? (yes/no): ")
    
    if response.lower() in ['yes', 'y']:
        asyncio.run(main())
    else:
        print("Test cancelled")