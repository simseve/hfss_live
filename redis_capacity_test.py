#!/usr/bin/env python3
"""
Focused Redis capacity and performance test
"""
import asyncio
import time
import json
from datetime import datetime, timezone
from redis.asyncio import Redis, ConnectionPool
from redis.asyncio.connection import ConnectionError
from config import settings
import aiohttp

async def test_redis_connections():
    """Test Redis connection limits and pooling"""
    print("\n🔴 REDIS CONNECTION CAPACITY TEST")
    print("=" * 50)
    
    redis_url = settings.get_redis_url()
    
    # Test 1: Individual connections without pooling
    print("\n1️⃣ Test: Individual Connections (no pooling)")
    connections = []
    max_individual = 0
    
    for i in range(100):
        try:
            conn = Redis.from_url(redis_url, decode_responses=True, 
                                 single_connection_client=True)
            await conn.ping()
            connections.append(conn)
            max_individual = i + 1
            
            if (i + 1) % 10 == 0:
                print(f"  ✅ {i + 1} connections active")
                
        except Exception as e:
            print(f"  ❌ Failed at connection {i + 1}: {e}")
            break
    
    print(f"  Maximum individual connections: {max_individual}")
    
    # Close all connections
    for conn in connections:
        try:
            await conn.aclose()
        except:
            pass
    
    await asyncio.sleep(2)
    
    # Test 2: Connection pool test
    print("\n2️⃣ Test: Connection Pool Performance")
    
    pool_sizes = [10, 20, 50, 100]
    
    for pool_size in pool_sizes:
        print(f"\n  Testing pool size: {pool_size}")
        
        # Create Redis client with specific pool size
        pool = ConnectionPool.from_url(
            redis_url,
            max_connections=pool_size,
            decode_responses=True
        )
        redis = Redis(connection_pool=pool)
        
        try:
            # Test concurrent operations
            start = time.time()
            tasks = []
            
            for i in range(pool_size * 2):  # Try 2x the pool size
                async def operation(idx):
                    try:
                        await redis.set(f"test_key_{idx}", f"value_{idx}")
                        await redis.get(f"test_key_{idx}")
                        await redis.delete(f"test_key_{idx}")
                        return True
                    except Exception as e:
                        return False
                
                tasks.append(operation(i))
            
            results = await asyncio.gather(*tasks)
            elapsed = time.time() - start
            
            successful = sum(1 for r in results if r)
            ops_per_sec = successful / elapsed
            
            print(f"    Operations: {successful}/{len(tasks)} successful")
            print(f"    Time: {elapsed:.2f}s")
            print(f"    Ops/sec: {ops_per_sec:.0f}")
            
        finally:
            await pool.disconnect()
            await redis.aclose()
    
    # Test 3: Queue operation performance
    print("\n3️⃣ Test: Queue Operation Performance")
    
    redis = await Redis.from_url(redis_url, decode_responses=True,
                                max_connections=50)
    
    try:
        # Clear test queue
        await redis.delete("perf_test_queue")
        
        # Test different batch sizes
        batch_configs = [
            (100, 10),    # 100 items, 10 points each
            (100, 100),   # 100 items, 100 points each
            (1000, 10),   # 1000 items, 10 points each
            (1000, 100),  # 1000 items, 100 points each
        ]
        
        for num_items, points_per_item in batch_configs:
            print(f"\n  Testing: {num_items} items × {points_per_item} points")
            
            # Prepare data
            items = []
            for i in range(num_items):
                item = {
                    'id': i,
                    'points': [{'x': j, 'y': j*2} for j in range(points_per_item)],
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }
                items.append((json.dumps(item), i))  # (member, score) for zadd
            
            # Test write performance
            start = time.time()
            
            # Use pipeline for batch operations
            pipe = redis.pipeline()
            for item, score in items:
                pipe.zadd("perf_test_queue", {item: score})
            
            await pipe.execute()
            write_time = time.time() - start
            
            total_points = num_items * points_per_item
            write_throughput = total_points / write_time
            
            # Test read performance
            start = time.time()
            
            read_items = []
            while True:
                batch = await redis.zpopmin("perf_test_queue", 100)
                if not batch:
                    break
                read_items.extend(batch)
            
            read_time = time.time() - start
            read_throughput = total_points / read_time
            
            print(f"    Write: {write_time:.2f}s ({write_throughput:.0f} points/sec)")
            print(f"    Read:  {read_time:.2f}s ({read_throughput:.0f} points/sec)")
    
    finally:
        await redis.aclose()
    
    # Test 4: Concurrent clients simulation
    print("\n4️⃣ Test: Concurrent Client Simulation")
    
    async def client_worker(client_id: int, operations: int):
        """Simulate a client doing operations"""
        redis = await Redis.from_url(redis_url, decode_responses=True)
        
        success = 0
        errors = 0
        
        try:
            for i in range(operations):
                try:
                    # Simulate typical operations
                    await redis.zadd(f"client_{client_id}_queue", {f"item_{i}": i})
                    await redis.zcard(f"client_{client_id}_queue")
                    await redis.zpopmin(f"client_{client_id}_queue")
                    success += 1
                except:
                    errors += 1
            
            # Cleanup
            await redis.delete(f"client_{client_id}_queue")
            
        finally:
            await redis.aclose()
        
        return success, errors
    
    client_counts = [5, 10, 20, 50]
    
    for num_clients in client_counts:
        print(f"\n  Testing {num_clients} concurrent clients")
        
        start = time.time()
        tasks = []
        
        for i in range(num_clients):
            task = client_worker(i, 50)  # 50 operations each
            tasks.append(task)
        
        results = await asyncio.gather(*tasks)
        elapsed = time.time() - start
        
        total_success = sum(s for s, _ in results)
        total_errors = sum(e for _, e in results)
        
        print(f"    Success: {total_success} operations")
        print(f"    Errors: {total_errors}")
        print(f"    Time: {elapsed:.2f}s")
        print(f"    Ops/sec: {total_success/elapsed:.0f}")
        
        if total_errors > total_success * 0.1:
            print(f"    ⚠️  High error rate detected")
            break

async def test_api_capacity():
    """Test API endpoint capacity"""
    print("\n🌐 API CAPACITY TEST")
    print("=" * 50)
    
    base_url = "http://localhost:8001"
    
    # Test health endpoint with increasing load
    print("\n  Testing /health endpoint")
    
    test_levels = [10, 50, 100, 200]
    
    for concurrent in test_levels:
        print(f"\n  {concurrent} concurrent requests:")
        
        async with aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(limit=concurrent)
        ) as session:
            
            start = time.time()
            tasks = []
            
            for i in range(concurrent):
                task = session.get(f"{base_url}/health")
                tasks.append(task)
            
            responses = await asyncio.gather(*tasks, return_exceptions=True)
            elapsed = time.time() - start
            
            success = 0
            for resp in responses:
                if not isinstance(resp, Exception):
                    async with resp as r:
                        if r.status == 200:
                            success += 1
            
            rps = success / elapsed
            print(f"    Success: {success}/{concurrent}")
            print(f"    Time: {elapsed:.2f}s")
            print(f"    RPS: {rps:.0f}")

async def main():
    print("=" * 60)
    print("🚀 REDIS & SYSTEM CAPACITY TEST")
    print("=" * 60)
    
    await test_redis_connections()
    print("\n" + "-" * 60)
    await test_api_capacity()
    
    print("\n" + "=" * 60)
    print("✅ CAPACITY TEST COMPLETE")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())