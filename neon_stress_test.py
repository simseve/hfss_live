#!/usr/bin/env python3
"""
Neon Database Stress Test - 100 Users with Different Flight IDs
Sends real tracking data that will be written to the database
"""
import asyncio
import aiohttp
import time
import random
import jwt
from datetime import datetime, timezone, timedelta
from uuid import uuid4
import sys

# Configuration
LOCAL_URL = "http://localhost:8001"
PRODUCTION_URL = "http://api.hikeandfly.app:5012"

# JWT configuration (from your .env)
SECRET_KEY = "M2U4JZkAqwj64NMmfFu4u9d18krM1udf"
ALGORITHM = "HS256"

class NeonStressTest:
    def __init__(self, target_url=LOCAL_URL):
        self.target_url = target_url
        self.stats = {
            'batches_sent': 0,
            'batches_success': 0,
            'batches_failed': 0,
            'points_written': 0,
            'response_times': [],
            'errors': {},
            'db_writes': 0
        }
        # Create a test race that will accept our data
        self.race_id = "stress-test-race-" + datetime.now().strftime("%Y%m%d%H%M%S")
        self.flights = {}  # Store flight info for each user
        
    def create_auth_token(self, pilot_id: str, flight_id: str) -> str:
        """Create a valid JWT token that will allow database writes"""
        payload = {
            "pilot_id": pilot_id,
            "race_id": self.race_id,
            "flight_id": flight_id,
            "pilot_name": f"Stress Test Pilot {pilot_id}",
            "exp": datetime.now(timezone.utc) + timedelta(hours=2),
            "race": {
                "name": "STRESS TEST RACE",
                "date": datetime.now().strftime("%Y-%m-%d"),
                "timezone": "Europe/Rome",
                "location": "LOMBARDY",
                "end_date": (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
            }
        }
        return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    
    def generate_flight_batch(self, pilot_id: int, batch_num: int) -> tuple:
        """Generate realistic flight data for one batch (10 seconds of flight)"""
        # Initialize or update flight path for this pilot
        if pilot_id not in self.flights:
            self.flights[pilot_id] = {
                'flight_id': f"flight-{pilot_id}-{uuid4().hex[:8]}",
                'lat': 45.5 + random.uniform(0, 0.2),
                'lon': 8.7 + random.uniform(0, 0.2),
                'alt': 500 + random.randint(0, 1500),
                'heading': random.uniform(0, 360),
                'speed': random.uniform(25, 35)  # km/h
            }
        
        flight = self.flights[pilot_id]
        points = []
        
        # Generate 10-15 points (1-1.5 Hz sampling for 10 seconds)
        num_points = random.randint(10, 15)
        base_time = datetime.now(timezone.utc) - timedelta(seconds=num_points)
        
        for i in range(num_points):
            # Simulate realistic movement
            flight['heading'] += random.uniform(-10, 10)
            flight['speed'] += random.uniform(-2, 2)
            flight['alt'] += random.uniform(-5, 5)
            
            # Calculate new position (simplified physics)
            delta_lat = (flight['speed'] / 111000) * 0.0003  # rough conversion
            delta_lon = (flight['speed'] / 111000) * 0.0003
            flight['lat'] += delta_lat * random.uniform(0.8, 1.2)
            flight['lon'] += delta_lon * random.uniform(0.8, 1.2)
            
            points.append({
                'lat': round(flight['lat'], 6),
                'lon': round(flight['lon'], 6),
                'elevation': int(flight['alt']),
                'barometric_altitude': round(flight['alt'] + random.uniform(-3, 3), 1),
                'datetime': (base_time + timedelta(seconds=i)).isoformat() + 'Z'
            })
        
        return points, flight['flight_id']
    
    async def send_tracking_batch(self, session: aiohttp.ClientSession, pilot_id: int, batch_num: int):
        """Send one batch of tracking data for a pilot"""
        points, flight_id = self.generate_flight_batch(pilot_id, batch_num)
        token = self.create_auth_token(f"pilot-{pilot_id}", flight_id)
        
        data = {
            'track_points': points,
            'flight_id': flight_id,
            'device_id': f'stress-device-{pilot_id}'
        }
        
        start = time.time()
        try:
            async with session.post(
                f"{self.target_url}/tracking/live",
                json=data,
                params={'token': token},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                elapsed = time.time() - start
                self.stats['response_times'].append(elapsed)
                self.stats['batches_sent'] += 1
                
                if response.status in [200, 201, 202]:
                    self.stats['batches_success'] += 1
                    self.stats['points_written'] += len(points)
                    self.stats['db_writes'] += len(points)
                    return True, elapsed, response.status
                else:
                    self.stats['batches_failed'] += 1
                    text = await response.text()
                    self.stats['errors'][response.status] = text[:100]
                    return False, elapsed, response.status
                    
        except asyncio.TimeoutError:
            self.stats['batches_failed'] += 1
            self.stats['errors']['timeout'] = self.stats['errors'].get('timeout', 0) + 1
            return False, 10.0, 'timeout'
        except Exception as e:
            self.stats['batches_failed'] += 1
            self.stats['errors']['exception'] = str(e)[:100]
            return False, 0, 'error'
    
    async def simulate_pilot(self, session: aiohttp.ClientSession, pilot_id: int, num_batches: int):
        """Simulate one pilot sending data every 10 seconds"""
        for batch_num in range(num_batches):
            success, elapsed, status = await self.send_tracking_batch(session, pilot_id, batch_num)
            
            if batch_num == 0:
                status_symbol = "✅" if success else "❌"
                print(f"  Pilot {pilot_id:3d}: {status_symbol} {status} ({elapsed*1000:.0f}ms)")
            
            # Wait 10 seconds before next batch (realistic interval)
            if batch_num < num_batches - 1:
                await asyncio.sleep(10)
    
    async def monitor_system(self, duration: int):
        """Monitor system health during test"""
        start = time.time()
        print("\n📊 System Monitoring:")
        print("Time | Status | Redis | DB | Response")
        print("-" * 45)
        
        while time.time() - start < duration:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(f"{self.target_url}/health", timeout=aiohttp.ClientTimeout(total=2)) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            elapsed = int(time.time() - start)
                            status = data.get('status', 'unknown')[:7]
                            redis = data.get('redis', {}).get('status', 'unknown')[:4]
                            db = data.get('database', {}).get('status', 'unknown')[:4]
                            
                            # Get a sample response time
                            if self.stats['response_times']:
                                recent_rt = self.stats['response_times'][-1] * 1000
                            else:
                                recent_rt = 0
                            
                            print(f"{elapsed:3d}s | {status:7s} | {redis:4s} | {db:4s} | {recent_rt:3.0f}ms")
            except:
                pass
            
            await asyncio.sleep(3)
    
    async def run_stress_test(self, num_users: int = 100, duration_seconds: int = 60):
        """Run the Neon database stress test"""
        print(f"\n🔥 NEON DATABASE STRESS TEST")
        print(f"=" * 50)
        print(f"Target: {self.target_url}")
        print(f"Users: {num_users} (each with unique flight ID)")
        print(f"Duration: {duration_seconds} seconds")
        print(f"Pattern: Batches every 10 seconds")
        print(f"Expected DB writes: ~{num_users * (duration_seconds // 10) * 12} points")
        print(f"=" * 50)
        
        # Check initial system state
        print(f"\n🔍 Initial System Check:")
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(f"{self.target_url}/health") as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        print(f"  System: {data.get('status')}")
                        print(f"  Database: {data.get('database', {}).get('status')}")
                        print(f"  Redis: {data.get('redis', {}).get('status')}")
            except Exception as e:
                print(f"  Health check failed: {e}")
                return
        
        print(f"\n🚀 Starting stress test with {num_users} users...")
        print(f"  Each user has a unique flight ID")
        print(f"  Sending real tracking data to database")
        print(f"\n  Launching pilots:")
        
        num_batches = duration_seconds // 10
        
        # Create high-limit connector
        connector = aiohttp.TCPConnector(limit=200, limit_per_host=200)
        
        async with aiohttp.ClientSession(connector=connector) as session:
            # Start monitoring
            monitor_task = asyncio.create_task(self.monitor_system(duration_seconds + 10))
            
            # Launch all pilots
            start_time = time.time()
            tasks = []
            
            # Stagger pilot starts slightly
            for i in range(num_users):
                pilot_task = asyncio.create_task(
                    self.simulate_pilot(session, i, num_batches)
                )
                tasks.append(pilot_task)
                
                # Small delay every 10 pilots to avoid thundering herd
                if i > 0 and i % 10 == 0:
                    await asyncio.sleep(0.1)
            
            print(f"\n  All {num_users} pilots launched!")
            print(f"  Test running for {duration_seconds} seconds...")
            
            # Wait for all pilots to complete
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Check for exceptions
            exceptions = [r for r in results if isinstance(r, Exception)]
            if exceptions:
                print(f"\n  ⚠️ {len(exceptions)} pilots had errors")
            
            # Cancel monitoring
            monitor_task.cancel()
            try:
                await monitor_task
            except asyncio.CancelledError:
                pass
        
        elapsed = time.time() - start_time
        
        # Calculate statistics
        if self.stats['response_times']:
            avg_rt = sum(self.stats['response_times']) / len(self.stats['response_times'])
            sorted_times = sorted(self.stats['response_times'])
            p50 = sorted_times[len(sorted_times) // 2]
            p95 = sorted_times[int(len(sorted_times) * 0.95)]
            p99 = sorted_times[int(len(sorted_times) * 0.99)]
            max_rt = max(self.stats['response_times'])
        else:
            avg_rt = p50 = p95 = p99 = max_rt = 0
        
        # Final system check
        print(f"\n📊 Final System Check:")
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(f"{self.target_url}/health") as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        print(f"  System: {data.get('status')}")
                        print(f"  Database: {data.get('database', {}).get('status')}")
                        print(f"  Redis: {data.get('redis', {}).get('status')}")
            except Exception as e:
                print(f"  Health check failed: {e}")
        
        # Print results
        print(f"\n" + "=" * 50)
        print(f"📈 STRESS TEST RESULTS")
        print(f"=" * 50)
        print(f"Test Duration: {elapsed:.1f} seconds")
        print(f"Active Users: {num_users}")
        print(f"Unique Flights: {len(self.flights)}")
        
        print(f"\n📊 Database Write Statistics:")
        print(f"  Batches Sent: {self.stats['batches_sent']}")
        print(f"  Batches Success: {self.stats['batches_success']}")
        print(f"  Batches Failed: {self.stats['batches_failed']}")
        print(f"  Points Written to DB: {self.stats['points_written']:,}")
        print(f"  Success Rate: {self.stats['batches_success']/max(1, self.stats['batches_sent'])*100:.1f}%")
        
        print(f"\n⚡ Performance Metrics:")
        print(f"  Writes/sec: {self.stats['points_written']/elapsed:.1f} points/sec")
        print(f"  Avg Response: {avg_rt*1000:.0f}ms")
        print(f"  P50 Response: {p50*1000:.0f}ms")
        print(f"  P95 Response: {p95*1000:.0f}ms")
        print(f"  P99 Response: {p99*1000:.0f}ms")
        print(f"  Max Response: {max_rt*1000:.0f}ms")
        
        if self.stats['errors']:
            print(f"\n⚠️ Errors:")
            for error_type, error_msg in list(self.stats['errors'].items())[:5]:
                print(f"  {error_type}: {error_msg}")
        
        # Verdict
        print(f"\n" + "=" * 50)
        print(f"🎯 NEON DATABASE VERDICT")
        print(f"=" * 50)
        
        success_rate = self.stats['batches_success'] / max(1, self.stats['batches_sent'])
        
        if success_rate > 0.99 and p95 < 1.0:
            print(f"  🏆 EXCELLENT - Neon handled {num_users} users perfectly!")
            print(f"  - Written {self.stats['points_written']:,} points to database")
            print(f"  - P95 under 1 second")
            print(f"  - Can handle production load easily")
        elif success_rate > 0.95 and p95 < 2.0:
            print(f"  ✅ GOOD - Neon handled load well")
            print(f"  - 95%+ success rate")
            print(f"  - Some latency under load but acceptable")
        elif success_rate > 0.90:
            print(f"  ⚠️ ADEQUATE - Neon showing stress")
            print(f"  - Consider connection pool tuning")
            print(f"  - May need optimization for this load")
        else:
            print(f"  ❌ STRUGGLING - Neon had issues with {num_users} users")
            print(f"  - High failure rate")
            print(f"  - Need to investigate bottlenecks")

async def main():
    print("\n🔬 Neon Database Stress Test")
    print("Testing with 100 unique flights writing to database")
    
    # Choose target
    target = LOCAL_URL
    if len(sys.argv) > 1:
        if sys.argv[1] == "prod":
            target = PRODUCTION_URL
            print("\n⚠️ WARNING: Testing PRODUCTION database!")
            confirm = input("This will write real data. Continue? (yes/no): ")
            if confirm.lower() != "yes":
                return
    
    tester = NeonStressTest(target)
    
    # Run test: 100 users for 60 seconds
    await tester.run_stress_test(num_users=100, duration_seconds=60)
    
    print("\n💡 Note: Check database for 'stress-test-race-*' data if cleanup needed")

if __name__ == "__main__":
    asyncio.run(main())