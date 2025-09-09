#!/usr/bin/env python3
"""
Send current metrics from production API to Datadog
"""
import os
import requests
import time
from dotenv import load_dotenv
from datadog import initialize, statsd

load_dotenv()

DD_API_KEY = os.getenv('DD_API_KEY')
DD_APP_KEY = os.getenv('DD_APP_KEY')

# Initialize Datadog
initialize(
    api_key=DD_API_KEY,
    app_key=DD_APP_KEY,
    statsd_host='127.0.0.1',
    statsd_port=8125
)

# Fetch current metrics from production
response = requests.get(
    'https://api.hikeandfly.app/api/monitoring/dashboard',
    params={'include_history': False},
    headers={'accept': 'application/json'}
)

if response.status_code == 200:
    data = response.json()
    
    # Send metrics to Datadog
    print("📊 Sending metrics to Datadog...")
    
    # Live tracking metrics
    statsd.gauge('hfss.live.active_flights', data['live_tracking']['active_flights'])
    statsd.gauge('hfss.live.active_devices', data['live_tracking']['active_devices'])
    statsd.gauge('hfss.live.total_points', data['live_tracking']['total_points'])
    statsd.gauge('hfss.live.messages_per_second', data['live_tracking']['messages_per_second'])
    statsd.gauge('hfss.queue.pending', data['live_tracking']['queue_pending'], tags=['queue_type:live'])
    statsd.gauge('hfss.queue.dlq_size', data['live_tracking']['dlq_size'], tags=['queue_type:live'])
    
    # Upload metrics
    statsd.gauge('hfss.uploads.total', data['uploads']['total_uploads'])
    statsd.gauge('hfss.uploads.last_hour', data['uploads']['uploads_last_hour'])
    statsd.gauge('hfss.queue.pending', data['uploads']['queue_pending'], tags=['queue_type:upload'])
    statsd.gauge('hfss.queue.dlq_size', data['uploads']['dlq_size'], tags=['queue_type:upload'])
    
    # Scoring metrics
    statsd.gauge('hfss.queue.pending', data['scoring']['queue_pending'], tags=['queue_type:scoring'])
    statsd.gauge('hfss.queue.dlq_size', data['scoring']['dlq_size'], tags=['queue_type:scoring'])
    
    # GPS TCP Server metrics
    statsd.gauge('hfss.gps_tcp.active_connections', data['gps_tcp_server']['active_connections'])
    statsd.gauge('hfss.gps_tcp.messages_total', data['gps_tcp_server']['messages_total'])
    statsd.gauge('hfss.gps_tcp.devices_total', data['gps_tcp_server']['devices_total'])
    
    # Database metrics
    statsd.gauge('hfss.database.connections_active', data['database']['connections_active'])
    statsd.gauge('hfss.database.connections_idle', data['database']['connections_idle'])
    statsd.gauge('hfss.database.connections_total', data['database']['connections_total'])
    
    # Table sizes
    for table, size in data['database']['table_sizes'].items():
        statsd.gauge('hfss.database.table_size', size, tags=[f'table:{table}'])
    
    # Total DLQ across all queues
    total_dlq = sum(q['dlq_size'] for q in data['queues']['queues'].values())
    statsd.gauge('hfss.queue.dlq_size', total_dlq)
    
    # Send event about platform health
    if data['platform_health']['status'] != 'healthy':
        # Send event via API
        headers = {
            'DD-API-KEY': DD_API_KEY,
            'DD-APPLICATION-KEY': DD_APP_KEY,
            'Content-Type': 'application/json'
        }
        
        event = {
            "title": "⚠️ HFSS Platform Health Degraded",
            "text": f"Platform status: {data['platform_health']['status']}. Issues: {', '.join(data['platform_health']['issues'])}",
            "priority": "normal",
            "tags": ["service:hfss-live", "env:production"],
            "alert_type": "warning"
        }
        
        event_response = requests.post(
            "https://api.datadoghq.eu/api/v1/events",
            headers=headers,
            json=event
        )
        
        if event_response.status_code in [200, 202]:
            print("⚠️  Sent platform health warning event")
    
    print("\n✅ Metrics sent successfully!")
    print("\nCurrent Status:")
    print(f"  📡 Messages/sec: {data['live_tracking']['messages_per_second']}")
    print(f"  ✈️  Active Flights: {data['live_tracking']['active_flights']}")
    print(f"  📊 Total Points: {data['live_tracking']['total_points']:,}")
    print(f"  💾 DB Connections: {data['database']['connections_active']}/{data['database']['connections_total']}")
    print(f"  ⚠️  Platform: {data['platform_health']['status']}")
    
    if data['platform_health']['issues']:
        print(f"\n🔴 Issues: {', '.join(data['platform_health']['issues'])}")
    
    print("\n📊 View your dashboard at:")
    print("   https://app.datadoghq.eu/dashboard/ric-ec3-uue")
    
else:
    print(f"❌ Failed to fetch metrics: {response.status_code}")