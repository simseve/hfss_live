#!/usr/bin/env python3
"""
Test script to verify metrics are being pushed correctly to Datadog
"""
import asyncio
import os
import sys
from dotenv import load_dotenv
from datadog import DogStatsd
import requests
import json
from datetime import datetime

load_dotenv()

# Test connection to Datadog
DD_API_KEY = os.getenv('DD_API_KEY')
DD_APP_KEY = os.getenv('DD_APP_KEY')
DD_AGENT_HOST = os.getenv('DD_AGENT_HOST', 'localhost')
DD_DOGSTATSD_PORT = int(os.getenv('DD_DOGSTATSD_PORT', 8125))

print("🔍 Testing Datadog Metrics Push\n")
print("=" * 50)
print(f"Configuration:")
print(f"  DD_AGENT_HOST: {DD_AGENT_HOST}")
print(f"  DD_DOGSTATSD_PORT: {DD_DOGSTATSD_PORT}")
print(f"  DD_API_KEY: {DD_API_KEY[:10]}...")
print("=" * 50)

# Initialize StatsD client
statsd = DogStatsd(
    host=DD_AGENT_HOST,
    port=DD_DOGSTATSD_PORT,
    namespace='hfss',
    constant_tags=['env:test', 'source:manual_test']
)

# Fetch current metrics from production
print("\n📊 Fetching current metrics from production...")
response = requests.get(
    'https://api.hikeandfly.app/api/monitoring/dashboard',
    params={'include_history': False}
)

if response.status_code == 200:
    data = response.json()
    print("✅ Fetched metrics successfully")
    
    # Extract key metrics
    live = data['live_tracking']
    db = data['database']
    queues = data['queues']
    
    print(f"\nCurrent values:")
    print(f"  Messages/sec: {live['messages_per_second']}")
    print(f"  Active flights: {live['active_flights']}")
    print(f"  Total points: {live['total_points']}")
    print(f"  DB connections: {db['connections_active']}/{db['connections_total']}")
    
    # Push test metrics with exact same names as dashboard expects
    print("\n📤 Pushing metrics to Datadog...")
    
    # Live tracking metrics - EXACTLY as dashboard expects
    statsd.gauge('live.messages_per_second', live['messages_per_second'])
    statsd.gauge('live.active_flights', live['active_flights'])
    statsd.gauge('live.active_devices', live['active_devices'])
    statsd.gauge('live.total_points', live['total_points'])
    
    # Queue metrics with tags
    statsd.gauge('queue.pending', live['queue_pending'], tags=['queue_type:live'])
    statsd.gauge('queue.dlq_size', live['dlq_size'], tags=['queue_type:live'])
    
    # Database metrics
    statsd.gauge('database.connections_active', db['connections_active'])
    statsd.gauge('database.connections_idle', db['connections_idle'])
    statsd.gauge('database.connections_total', db['connections_total'])
    
    # Table sizes with tags
    for table, size in db['table_sizes'].items():
        statsd.gauge('database.table_size', size, tags=[f'table:{table}'])
    
    # Total queue metrics (for sum queries)
    total_dlq = sum(q['dlq_size'] for q in queues['queues'].values())
    statsd.gauge('queue.dlq_size', total_dlq)  # Without tags for sum query
    
    # GPS TCP metrics
    gps = data['gps_tcp_server']
    statsd.gauge('gps_tcp.active_connections', gps['active_connections'])
    
    # Platform health
    health_value = 1 if data['platform_health']['status'] == 'healthy' else 0
    statsd.gauge('platform.health', health_value)
    
    # Send a test event
    statsd.event(
        'Test Metrics Push',
        f"Manual test at {datetime.now().isoformat()}. Pushed {live['messages_per_second']} msg/s",
        alert_type='info',
        tags=['service:hfss-live', 'test:manual']
    )
    
    print("✅ Metrics pushed successfully!")
    
    print("\n📊 Dashboard URLs:")
    print("  Main: https://app.datadoghq.eu/dashboard/ric-ec3-uue")
    print("  Metrics Explorer: https://app.datadoghq.eu/metric/explorer")
    print("  Events: https://app.datadoghq.eu/event/stream")
    
    print("\n⏱️  Metrics should appear within 1-2 minutes")
    print("\n💡 Check for these metrics in Datadog:")
    print("  - hfss.live.messages_per_second")
    print("  - hfss.live.active_flights")
    print("  - hfss.queue.dlq_size")
    print("  - hfss.database.connections_active")
    print("  - hfss.gps_tcp.active_connections")
    
else:
    print(f"❌ Failed to fetch metrics: {response.status_code}")
    print("Using test values instead...")
    
    # Send test metrics
    statsd.gauge('live.messages_per_second', 1.5)
    statsd.gauge('live.active_flights', 3)
    statsd.gauge('queue.dlq_size', 0)
    statsd.gauge('database.connections_active', 150)
    statsd.gauge('gps_tcp.active_connections', 2)
    
    print("✅ Test metrics sent")