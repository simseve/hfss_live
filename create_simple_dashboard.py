#!/usr/bin/env python3
"""
Create a simple Datadog dashboard for HFSS monitoring
"""
import os
import requests
from dotenv import load_dotenv

load_dotenv()

DD_API_KEY = os.getenv('DD_API_KEY')
DD_APP_KEY = os.getenv('DD_APP_KEY')

dashboard = {
    "title": "HFSS Live Platform Monitoring",
    "description": "Real-time monitoring for HFSS Live tracking platform",
    "widgets": [
        # Platform Events Stream
        {
            "definition": {
                "type": "event_stream",
                "query": "tags:service:hfss-live OR tags:hfss",
                "event_size": "s",
                "title": "Platform Events",
                "title_size": "16",
                "title_align": "left"
            },
            "layout": {"x": 0, "y": 0, "width": 6, "height": 4}
        },
        # Queue Status
        {
            "definition": {
                "type": "query_value",
                "requests": [{
                    "q": "sum:hfss.queue.dlq_size{*}",
                    "aggregator": "last"
                }],
                "title": "Dead Letter Queue Items",
                "precision": 0
            },
            "layout": {"x": 6, "y": 0, "width": 2, "height": 2}
        },
        # Messages per second
        {
            "definition": {
                "type": "timeseries",
                "requests": [{
                    "q": "avg:hfss.live.messages_per_second{*}",
                    "display_type": "line",
                    "style": {"palette": "dog_classic"}
                }],
                "title": "Messages Per Second"
            },
            "layout": {"x": 8, "y": 0, "width": 4, "height": 2}
        },
        # Active Flights
        {
            "definition": {
                "type": "query_value",
                "requests": [{
                    "q": "avg:hfss.live.active_flights{*}",
                    "aggregator": "last"
                }],
                "title": "Active Flights",
                "precision": 0
            },
            "layout": {"x": 6, "y": 2, "width": 2, "height": 2}
        },
        # Queue Pending Items
        {
            "definition": {
                "type": "timeseries",
                "requests": [{
                    "q": "sum:hfss.queue.pending{*} by {queue_type}",
                    "display_type": "bars",
                    "style": {"palette": "warm"}
                }],
                "title": "Queue Pending Items by Type"
            },
            "layout": {"x": 8, "y": 2, "width": 4, "height": 2}
        },
        # Database Connections
        {
            "definition": {
                "type": "timeseries",
                "requests": [{
                    "q": "avg:hfss.database.connections_active{*}",
                    "display_type": "line",
                    "style": {"palette": "purple"}
                }],
                "title": "Database Active Connections"
            },
            "layout": {"x": 0, "y": 4, "width": 4, "height": 2}
        },
        # API Response Time
        {
            "definition": {
                "type": "timeseries",
                "requests": [{
                    "q": "avg:hfss.api.response_time{*} by {endpoint}",
                    "display_type": "line"
                }],
                "title": "API Response Times"
            },
            "layout": {"x": 4, "y": 4, "width": 4, "height": 2}
        },
        # GPS TCP Connections
        {
            "definition": {
                "type": "timeseries",
                "requests": [{
                    "q": "avg:hfss.gps_tcp.active_connections{*}",
                    "display_type": "line",
                    "style": {"palette": "green"}
                }],
                "title": "GPS TCP Active Connections"
            },
            "layout": {"x": 8, "y": 4, "width": 4, "height": 2}
        },
        # Platform Health Note
        {
            "definition": {
                "type": "note",
                "content": "## Key Metrics\n- **DLQ > 0**: Failed messages need attention\n- **Messages/sec < 0.1**: No data flowing\n- **DB Connections > 180**: Connection pool near limit\n\n[View Logs](https://app.datadoghq.eu/logs)",
                "background_color": "gray",
                "font_size": "14",
                "text_align": "left",
                "show_tick": False
            },
            "layout": {"x": 0, "y": 6, "width": 3, "height": 3}
        }
    ],
    "layout_type": "free"
}

# Create dashboard
headers = {
    'DD-API-KEY': DD_API_KEY,
    'DD-APPLICATION-KEY': DD_APP_KEY,
    'Content-Type': 'application/json'
}

response = requests.post(
    "https://api.datadoghq.eu/api/v1/dashboard",
    headers=headers,
    json=dashboard
)

if response.status_code in [200, 201]:
    result = response.json()
    dashboard_id = result.get('id')
    dashboard_url = f"https://app.datadoghq.eu/dashboard/{dashboard_id}"
    
    print("✅ Dashboard created successfully!")
    print(f"\n📊 Your HFSS Dashboard:")
    print(f"   {dashboard_url}")
    print(f"\n📌 Dashboard ID: {dashboard_id}")
    print("\n⚠️  Note:")
    print("  - Events are visible immediately")
    print("  - Metrics will appear when Datadog Agent is running in production")
    print("  - Use 'docker-compose --profile monitoring up' to enable full monitoring")
else:
    print(f"❌ Failed: {response.status_code}")
    print(response.text)