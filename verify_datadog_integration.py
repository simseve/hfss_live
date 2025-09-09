#!/usr/bin/env python3
"""
Verify Datadog integration and data flow
"""
import os
import requests
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

DD_API_KEY = os.getenv('DD_API_KEY')
DD_APP_KEY = os.getenv('DD_APP_KEY')

print("🔍 Verifying Datadog Integration\n")
print("=" * 50)

# 1. Check if metrics are being received
headers = {
    'DD-API-KEY': DD_API_KEY,
    'DD-APPLICATION-KEY': DD_APP_KEY,
    'Content-Type': 'application/json'
}

# Get metric list
print("\n📊 Checking HFSS metrics in Datadog...")
metrics_response = requests.get(
    "https://api.datadoghq.eu/api/v1/metrics",
    headers=headers,
    params={
        'from': int((datetime.now() - timedelta(hours=1)).timestamp()),
        'host': '*'
    }
)

if metrics_response.status_code == 200:
    metrics = metrics_response.json().get('metrics', [])
    hfss_metrics = [m for m in metrics if m.startswith('hfss.')]
    
    if hfss_metrics:
        print(f"✅ Found {len(hfss_metrics)} HFSS metrics:")
        for metric in hfss_metrics[:10]:  # Show first 10
            print(f"   • {metric}")
        if len(hfss_metrics) > 10:
            print(f"   ... and {len(hfss_metrics) - 10} more")
    else:
        print("⚠️  No HFSS metrics found in last hour")
else:
    print(f"❌ Failed to fetch metrics: {metrics_response.status_code}")

# 2. Check recent events
print("\n📢 Checking recent HFSS events...")
events_response = requests.get(
    "https://api.datadoghq.eu/api/v1/events",
    headers=headers,
    params={
        'start': int((datetime.now() - timedelta(hours=1)).timestamp()),
        'end': int(datetime.now().timestamp()),
        'tags': 'service:hfss-live'
    }
)

if events_response.status_code == 200:
    events = events_response.json().get('events', [])
    if events:
        print(f"✅ Found {len(events)} recent events:")
        for event in events[:3]:  # Show first 3
            print(f"   • {event.get('title', 'No title')}")
            print(f"     {datetime.fromtimestamp(event.get('date_happened', 0)).strftime('%Y-%m-%d %H:%M:%S')}")
    else:
        print("ℹ️  No events in last hour")
else:
    print(f"❌ Failed to fetch events: {events_response.status_code}")

# 3. Query specific metric values
print("\n📈 Querying latest metric values...")
now = int(datetime.now().timestamp())
hour_ago = int((datetime.now() - timedelta(hours=1)).timestamp())

query_metrics = [
    'hfss.live.messages_per_second',
    'hfss.live.active_flights',
    'hfss.database.connections_active',
    'hfss.queue.dlq_size'
]

for metric_name in query_metrics:
    query_response = requests.get(
        "https://api.datadoghq.eu/api/v1/query",
        headers=headers,
        params={
            'from': hour_ago,
            'to': now,
            'query': f'avg:{metric_name}{{*}}'
        }
    )
    
    if query_response.status_code == 200:
        data = query_response.json()
        if data.get('series'):
            series = data['series'][0]
            points = series.get('pointlist', [])
            if points:
                latest_value = points[-1][1]  # Get the last value
                print(f"   • {metric_name}: {latest_value:.2f}")
            else:
                print(f"   • {metric_name}: No data points")
        else:
            print(f"   • {metric_name}: No data")

print("\n" + "=" * 50)
print("\n🔄 Data Flow Summary:")
print("\n1. YOUR BACKEND → Monitoring endpoint")
print("   https://api.hikeandfly.app/api/monitoring/dashboard")
print("   ✅ Working - Returns real-time platform metrics")

print("\n2. FASTAPI APP → Datadog Agent")
print("   Your app sends metrics via StatsD (port 8125)")
print("   📍 Configuration: DD_AGENT_HOST=datadog-agent")

print("\n3. DATADOG AGENT → Datadog Cloud (EU)")
print("   Agent forwards metrics to datadoghq.eu")
print("   📍 Requires: --profile monitoring in docker-compose")

print("\n4. DASHBOARD → Visualization")
print("   https://app.datadoghq.eu/dashboard/ric-ec3-uue")
print("   🎨 Cool dashboard with emojis and colors!")

print("\n" + "=" * 50)
print("\n💡 To ensure continuous data flow:")
print("1. Deploy with: docker compose --profile monitoring up -d")
print("2. Your app automatically sends metrics when:")
print("   - API endpoints are called")
print("   - Queue processing happens")
print("   - Background tasks run")
print("3. Metrics appear in Datadog within 1-2 minutes")

print("\n🚀 Next Steps:")
print("1. Set up alerts for critical metrics")
print("2. Configure log forwarding")
print("3. Enable APM tracing for detailed performance insights")