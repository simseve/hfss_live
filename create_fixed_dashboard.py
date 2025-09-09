#!/usr/bin/env python3
"""
Create a properly formatted Datadog dashboard for HFSS monitoring
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
        # Row 1: Events and Key Metrics
        {
            "definition": {
                "type": "event_stream",
                "query": "tags:service:hfss-live OR tags:hfss",
                "event_size": "s",
                "title": "Platform Events",
                "title_size": "16",
                "title_align": "left"
            },
            "layout": {"x": 0, "y": 0, "width": 47, "height": 30}
        },
        {
            "definition": {
                "type": "query_value",
                "requests": [{
                    "q": "sum:hfss.queue.dlq_size{*}",
                    "aggregator": "last",
                    "conditional_formats": [
                        {"comparator": ">", "value": 100, "palette": "red"},
                        {"comparator": ">", "value": 10, "palette": "yellow"},
                        {"comparator": "<=", "value": 10, "palette": "green"}
                    ]
                }],
                "title": "Dead Letter Queue",
                "title_size": "16",
                "title_align": "left",
                "precision": 0
            },
            "layout": {"x": 48, "y": 0, "width": 23, "height": 15}
        },
        {
            "definition": {
                "type": "query_value",
                "requests": [{
                    "q": "avg:hfss.live.active_flights{*}",
                    "aggregator": "last"
                }],
                "title": "Active Flights",
                "title_size": "16",
                "title_align": "left",
                "precision": 0
            },
            "layout": {"x": 72, "y": 0, "width": 23, "height": 15}
        },
        {
            "definition": {
                "type": "query_value",
                "requests": [{
                    "q": "avg:hfss.live.messages_per_second{*}",
                    "aggregator": "avg"
                }],
                "title": "Messages/sec",
                "title_size": "16",
                "title_align": "left",
                "precision": 2
            },
            "layout": {"x": 96, "y": 0, "width": 23, "height": 15}
        },
        
        # Row 2: Time Series Graphs
        {
            "definition": {
                "type": "timeseries",
                "requests": [{
                    "q": "avg:hfss.live.messages_per_second{*}",
                    "display_type": "line",
                    "style": {"palette": "blue", "line_type": "solid", "line_width": "normal"}
                }],
                "title": "Message Throughput",
                "title_size": "16",
                "title_align": "left",
                "show_legend": False,
                "yaxis": {"include_zero": True}
            },
            "layout": {"x": 48, "y": 16, "width": 71, "height": 25}
        },
        
        # Row 3: Queue and Database Monitoring
        {
            "definition": {
                "type": "timeseries",
                "requests": [{
                    "q": "sum:hfss.queue.pending{*} by {queue_type}",
                    "display_type": "bars",
                    "style": {"palette": "warm"}
                }],
                "title": "Queue Pending Items by Type",
                "title_size": "16",
                "title_align": "left",
                "show_legend": True,
                "legend_layout": "horizontal",
                "legend_columns": ["avg", "min", "max", "value"],
                "yaxis": {"include_zero": True}
            },
            "layout": {"x": 0, "y": 31, "width": 59, "height": 25}
        },
        {
            "definition": {
                "type": "timeseries",
                "requests": [{
                    "q": "sum:hfss.queue.dlq_size{*} by {queue_type}",
                    "display_type": "line",
                    "style": {"palette": "red"}
                }],
                "title": "Dead Letter Queue Trends",
                "title_size": "16",
                "title_align": "left",
                "show_legend": True,
                "yaxis": {"include_zero": True}
            },
            "layout": {"x": 60, "y": 31, "width": 59, "height": 25}
        },
        
        # Row 4: Infrastructure
        {
            "definition": {
                "type": "timeseries",
                "requests": [
                    {
                        "q": "avg:hfss.database.connections_active{*}",
                        "display_type": "line",
                        "style": {"palette": "purple"},
                        "metadata": [{"alias": "Active Connections"}]
                    },
                    {
                        "q": "avg:hfss.database.connections_idle{*}",
                        "display_type": "line",
                        "style": {"palette": "gray"},
                        "metadata": [{"alias": "Idle Connections"}]
                    }
                ],
                "title": "Database Connection Pool",
                "title_size": "16",
                "title_align": "left",
                "show_legend": True,
                "yaxis": {"include_zero": True}
            },
            "layout": {"x": 0, "y": 57, "width": 59, "height": 25}
        },
        {
            "definition": {
                "type": "timeseries",
                "requests": [{
                    "q": "avg:hfss.gps_tcp.active_connections{*}",
                    "display_type": "line",
                    "style": {"palette": "green"}
                }],
                "title": "GPS TCP Active Connections",
                "title_size": "16",
                "title_align": "left",
                "show_legend": False,
                "yaxis": {"include_zero": True}
            },
            "layout": {"x": 60, "y": 57, "width": 59, "height": 25}
        },
        
        # Row 5: API Performance
        {
            "definition": {
                "type": "timeseries",
                "requests": [{
                    "q": "avg:hfss.api.response_time{*} by {endpoint}",
                    "display_type": "line"
                }],
                "title": "API Response Times by Endpoint",
                "title_size": "16",
                "title_align": "left",
                "show_legend": True,
                "legend_layout": "horizontal",
                "yaxis": {"include_zero": False, "scale": "linear"}
            },
            "layout": {"x": 0, "y": 83, "width": 59, "height": 25}
        },
        {
            "definition": {
                "type": "timeseries",
                "requests": [{
                    "q": "sum:hfss.api.errors{*} by {status_family}.as_rate()",
                    "display_type": "bars",
                    "style": {"palette": "red"}
                }],
                "title": "API Error Rate",
                "title_size": "16",
                "title_align": "left",
                "show_legend": True,
                "yaxis": {"include_zero": True}
            },
            "layout": {"x": 60, "y": 83, "width": 59, "height": 25}
        },
        
        # Info Panel
        {
            "definition": {
                "type": "note",
                "content": "## 🚨 Alert Thresholds\n\n**Critical:**\n- DLQ > 100 items\n- No data for 5 minutes\n- DB connections > 180\n- API error rate > 5%\n\n**Warning:**\n- DLQ > 10 items\n- Queue pending > 1000\n- Latency > 1 second\n\n**Links:**\n- [View Logs](https://app.datadoghq.eu/logs)\n- [APM Traces](https://app.datadoghq.eu/apm/traces)",
                "background_color": "white",
                "font_size": "14",
                "text_align": "left",
                "vertical_align": "top",
                "show_tick": True,
                "tick_pos": "50%",
                "tick_edge": "left"
            },
            "layout": {"x": 0, "y": 109, "width": 30, "height": 35}
        },
        {
            "definition": {
                "type": "note",
                "content": "## 📊 Key Metrics\n\n**Live Tracking:**\n- Messages/sec: Incoming GPS data rate\n- Active flights: Currently tracked flights\n- Active devices: Unique devices sending data\n\n**Queues:**\n- Pending: Messages waiting to process\n- DLQ: Failed messages needing review\n- Processing: Currently being handled\n\n**Database:**\n- Max connections: 200\n- Target usage: < 80%",
                "background_color": "white",
                "font_size": "14",
                "text_align": "left",
                "vertical_align": "top",
                "show_tick": True,
                "tick_pos": "50%",
                "tick_edge": "left"
            },
            "layout": {"x": 31, "y": 109, "width": 30, "height": 35}
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

# First, try to delete the old dashboard if it exists
try:
    with open('.datadog_dashboard_id', 'r') as f:
        old_dashboard_id = f.read().strip()
        delete_response = requests.delete(
            f"https://api.datadoghq.eu/api/v1/dashboard/{old_dashboard_id}",
            headers=headers
        )
        if delete_response.status_code == 200:
            print(f"✅ Deleted old dashboard {old_dashboard_id}")
except:
    pass

# Create new dashboard
response = requests.post(
    "https://api.datadoghq.eu/api/v1/dashboard",
    headers=headers,
    json=dashboard
)

if response.status_code in [200, 201]:
    result = response.json()
    dashboard_id = result.get('id')
    dashboard_url = f"https://app.datadoghq.eu/dashboard/{dashboard_id}"
    
    # Save the new dashboard ID
    with open('.datadog_dashboard_id', 'w') as f:
        f.write(dashboard_id)
    
    print("✅ Dashboard created successfully!")
    print(f"\n📊 Your HFSS Dashboard (Fixed Layout):")
    print(f"   {dashboard_url}")
    print(f"\n📌 Dashboard ID: {dashboard_id}")
    print("\n✨ Features:")
    print("  - Properly spaced widgets (no overlapping)")
    print("  - Organized in logical sections")
    print("  - Color-coded alerts (green/yellow/red)")
    print("  - Key metrics at the top")
    print("  - Time series graphs for trends")
    print("  - Info panels with thresholds")
    print("\n⚠️  Note:")
    print("  - Events are visible immediately")
    print("  - Metrics appear when Datadog Agent runs")
else:
    print(f"❌ Failed: {response.status_code}")
    print(response.text)