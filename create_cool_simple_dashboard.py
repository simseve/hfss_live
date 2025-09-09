#!/usr/bin/env python3
"""
Create a cool-looking Datadog dashboard for HFSS monitoring
Simplified version compatible with current API
"""
import os
import requests
from dotenv import load_dotenv

load_dotenv()

DD_API_KEY = os.getenv('DD_API_KEY')
DD_APP_KEY = os.getenv('DD_APP_KEY')

dashboard = {
    "title": "🚁 HFSS Live Platform | Real-Time Monitoring",
    "description": "Complete operational visibility for HFSS Live tracking platform",
    "widgets": [
        # Big Numbers Row - Key Metrics
        {
            "definition": {
                "type": "query_value",
                "requests": [{
                    "q": "avg:hfss.live.messages_per_second{*}",
                    "aggregator": "last"
                }],
                "title": "📡 Messages/sec",
                "title_size": "16",
                "title_align": "center",
                "precision": 2,
                "autoscale": True
            },
            "layout": {"x": 0, "y": 0, "width": 30, "height": 15}
        },
        {
            "definition": {
                "type": "query_value",
                "requests": [{
                    "q": "avg:hfss.live.active_flights{*}",
                    "aggregator": "last",
                    "conditional_formats": [
                        {"comparator": ">", "value": 50, "palette": "green"},
                        {"comparator": ">", "value": 20, "palette": "yellow"},
                        {"comparator": ">=", "value": 0, "palette": "gray"}
                    ]
                }],
                "title": "✈️ Active Flights",
                "title_size": "16",
                "title_align": "center",
                "precision": 0,
                "autoscale": False
            },
            "layout": {"x": 30, "y": 0, "width": 30, "height": 15}
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
                "title": "⚠️ Dead Letters",
                "title_size": "16",
                "title_align": "center",
                "precision": 0,
                "autoscale": False
            },
            "layout": {"x": 60, "y": 0, "width": 30, "height": 15}
        },
        {
            "definition": {
                "type": "query_value",
                "requests": [{
                    "q": "avg:hfss.gps_tcp.active_connections{*}",
                    "aggregator": "last"
                }],
                "title": "🔌 GPS Connections",
                "title_size": "16",
                "title_align": "center",
                "precision": 0
            },
            "layout": {"x": 90, "y": 0, "width": 30, "height": 15}
        },
        
        # Live Activity Stream
        {
            "definition": {
                "type": "event_stream",
                "query": "tags:service:hfss-live",
                "event_size": "s",
                "title": "🎯 Live Activity Feed",
                "title_size": "16",
                "title_align": "left"
            },
            "layout": {"x": 0, "y": 16, "width": 60, "height": 40}
        },
        
        # Real-time Throughput Graph
        {
            "definition": {
                "type": "timeseries",
                "requests": [{
                    "q": "avg:hfss.live.messages_per_second{*}",
                    "display_type": "area",
                    "style": {
                        "palette": "cool"
                    }
                }],
                "title": "📈 Real-Time Message Throughput",
                "title_size": "16",
                "title_align": "left",
                "show_legend": True,
                "legend_layout": "horizontal",
                "legend_columns": ["avg", "min", "max", "value"],
                "yaxis": {"include_zero": True}
            },
            "layout": {"x": 61, "y": 16, "width": 59, "height": 40}
        },
        
        # Queue Health
        {
            "definition": {
                "type": "timeseries",
                "requests": [
                    {
                        "q": "sum:hfss.queue.pending{*} by {queue_type}",
                        "display_type": "bars",
                        "style": {"palette": "warm"}
                    },
                    {
                        "q": "sum:hfss.queue.dlq_size{*}",
                        "display_type": "line",
                        "style": {"palette": "red", "line_width": "thick"}
                    }
                ],
                "title": "🔥 Queue Status",
                "title_size": "16",
                "title_align": "left",
                "show_legend": True
            },
            "layout": {"x": 0, "y": 57, "width": 60, "height": 30}
        },
        
        # Database Performance
        {
            "definition": {
                "type": "timeseries",
                "requests": [
                    {
                        "q": "avg:hfss.database.connections_active{*}",
                        "display_type": "line",
                        "style": {"palette": "purple", "line_width": "thick"},
                        "metadata": [{"alias": "Active"}]
                    },
                    {
                        "q": "avg:hfss.database.connections_idle{*}",
                        "display_type": "line",
                        "style": {"palette": "gray", "line_width": "thin"},
                        "metadata": [{"alias": "Idle"}]
                    }
                ],
                "title": "💾 Database Connection Pool",
                "title_size": "16",
                "title_align": "left",
                "show_legend": True,
                "legend_layout": "horizontal",
                "yaxis": {"include_zero": True},
                "markers": [
                    {
                        "value": "y = 180",
                        "display_type": "error dashed",
                        "label": "Warning Threshold"
                    }
                ]
            },
            "layout": {"x": 61, "y": 57, "width": 59, "height": 30}
        },
        
        # API Performance
        {
            "definition": {
                "type": "timeseries",
                "requests": [{
                    "q": "avg:hfss.api.response_time{*} by {endpoint}",
                    "display_type": "line"
                }],
                "title": "⚡ API Response Times",
                "title_size": "16",
                "title_align": "left",
                "show_legend": True,
                "yaxis": {"include_zero": False}
            },
            "layout": {"x": 0, "y": 88, "width": 60, "height": 30}
        },
        
        # Top Lists
        {
            "definition": {
                "type": "toplist",
                "requests": [{
                    "q": "top(avg:hfss.database.table_size{*} by {table}, 10)"
                }],
                "title": "📊 Largest Tables",
                "title_size": "16",
                "title_align": "left"
            },
            "layout": {"x": 61, "y": 88, "width": 29, "height": 30}
        },
        {
            "definition": {
                "type": "toplist",
                "requests": [{
                    "q": "top(sum:hfss.api.requests{*} by {endpoint}.as_rate(), 10)"
                }],
                "title": "🎯 Busiest Endpoints",
                "title_size": "16",
                "title_align": "left"
            },
            "layout": {"x": 91, "y": 88, "width": 29, "height": 30}
        },
        
        # Info Cards
        {
            "definition": {
                "type": "note",
                "content": "# 🎮 Quick Actions\n\n[📊 View Metrics](https://app.datadoghq.eu/metric/explorer)\n\n[📝 View Logs](https://app.datadoghq.eu/logs)\n\n[🔍 APM Traces](https://app.datadoghq.eu/apm/traces)\n\n[⚙️ Settings](https://app.datadoghq.eu/account/settings)",
                "background_color": "blue",
                "font_size": "14",
                "text_align": "left",
                "vertical_align": "top",
                "show_tick": False,
                "has_padding": True
            },
            "layout": {"x": 0, "y": 119, "width": 30, "height": 20}
        },
        {
            "definition": {
                "type": "note",
                "content": "# 🎯 SLA Targets\n\n✅ **Uptime**: 99.9%\n\n⚡ **Response Time**: < 500ms\n\n📊 **Message Rate**: > 100/sec\n\n🔄 **Queue Lag**: < 1 min",
                "background_color": "green",
                "font_size": "14",
                "text_align": "left",
                "vertical_align": "top",
                "show_tick": False,
                "has_padding": True
            },
            "layout": {"x": 30, "y": 119, "width": 30, "height": 20}
        },
        {
            "definition": {
                "type": "note",
                "content": "# ⚠️ Alert Thresholds\n\n🔴 **Critical**: DLQ > 100\n\n🟡 **Warning**: Queue > 1000\n\n🔴 **Critical**: No data 5min\n\n🟡 **Warning**: DB > 80%",
                "background_color": "orange",
                "font_size": "14",
                "text_align": "left",
                "vertical_align": "top",
                "show_tick": False,
                "has_padding": True
            },
            "layout": {"x": 60, "y": 119, "width": 30, "height": 20}
        },
        {
            "definition": {
                "type": "note",
                "content": "# 📞 On-Call\n\n**Primary**: Team Lead\n\n**Backup**: DevOps\n\n**Escalation**: 15 min\n\n[📱 PagerDuty](https://app.pagerduty.com)",
                "background_color": "purple",
                "font_size": "14",
                "text_align": "left",
                "vertical_align": "top",
                "show_tick": False,
                "has_padding": True
            },
            "layout": {"x": 90, "y": 119, "width": 30, "height": 20}
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
    
    print("🎉 ✨ Cool Dashboard Created Successfully! ✨ 🎉")
    print(f"\n📊 Your HFSS Dashboard:")
    print(f"   {dashboard_url}")
    print(f"\n🆔 Dashboard ID: {dashboard_id}")
    print("\n🚀 Cool Features:")
    print("  🎨 Visual design with emojis and colors")
    print("  📈 Real-time graphs with gradients")
    print("  🔥 Queue status visualization")
    print("  💾 Database monitoring")
    print("  🏆 Top lists for key metrics")
    print("  🎮 Quick action buttons")
    print("  📊 SLA and threshold cards")
    print("\n💡 Pro tip: The dashboard will populate as metrics flow in!")
else:
    print(f"❌ Failed: {response.status_code}")
    print(response.text)