#!/usr/bin/env python3
"""
Create a cool-looking Datadog dashboard for HFSS monitoring
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
        # Header Banner
        {
            "definition": {
                "type": "image",
                "url": "https://images.unsplash.com/photo-1540979388789-6cee28a1cdc9?w=1200&h=100&fit=crop&crop=focalpoint",
                "sizing": "cover",
                "margin": "small",
                "has_background": False,
                "has_border": False
            },
            "layout": {"x": 0, "y": 0, "width": 12, "height": 2}
        },
        
        # Big Numbers Row - Key Metrics
        {
            "definition": {
                "type": "query_value",
                "requests": [{
                    "q": "avg:hfss.live.messages_per_second{$env}",
                    "aggregator": "last"
                }],
                "title": "📡 Messages/sec",
                "title_size": "16",
                "title_align": "center",
                "precision": 2,
                "autoscale": True,
                "custom_unit": "msg/s"
            },
            "layout": {"x": 0, "y": 2, "width": 3, "height": 2}
        },
        {
            "definition": {
                "type": "query_value",
                "requests": [{
                    "q": "avg:hfss.live.active_flights{$env}",
                    "aggregator": "last",
                    "conditional_formats": [
                        {"comparator": ">", "value": 50, "palette": "green_on_white"},
                        {"comparator": ">", "value": 20, "palette": "yellow_on_white"},
                        {"comparator": ">=", "value": 0, "palette": "gray_on_white"}
                    ]
                }],
                "title": "✈️ Active Flights",
                "title_size": "16",
                "title_align": "center",
                "precision": 0,
                "autoscale": False
            },
            "layout": {"x": 3, "y": 2, "width": 3, "height": 2}
        },
        {
            "definition": {
                "type": "query_value",
                "requests": [{
                    "q": "sum:hfss.queue.dlq_size{$env}",
                    "aggregator": "last",
                    "conditional_formats": [
                        {"comparator": ">", "value": 100, "palette": "white_on_red"},
                        {"comparator": ">", "value": 10, "palette": "white_on_yellow"},
                        {"comparator": "<=", "value": 10, "palette": "white_on_green"}
                    ]
                }],
                "title": "⚠️ Dead Letters",
                "title_size": "16",
                "title_align": "center",
                "precision": 0,
                "autoscale": False
            },
            "layout": {"x": 6, "y": 2, "width": 3, "height": 2}
        },
        {
            "definition": {
                "type": "check_status",
                "check": "hfss.platform.health",
                "grouping": "cluster",
                "title": "🟢 Platform Health",
                "title_size": "16",
                "title_align": "center",
                "tags": ["$env"]
            },
            "layout": {"x": 9, "y": 2, "width": 3, "height": 2}
        },
        
        # Live Activity Stream
        {
            "definition": {
                "type": "event_stream",
                "query": "tags:service:hfss-live $env",
                "event_size": "s",
                "title": "🎯 Live Activity Feed",
                "title_size": "16",
                "title_align": "left"
            },
            "layout": {"x": 0, "y": 4, "width": 6, "height": 4}
        },
        
        # Real-time Throughput Graph
        {
            "definition": {
                "type": "timeseries",
                "requests": [
                    {
                        "q": "avg:hfss.live.messages_per_second{$env}",
                        "display_type": "area",
                        "style": {
                            "palette": "cool",
                            "line_type": "solid",
                            "line_width": "normal"
                        },
                        "metadata": [{"alias": "Messages/sec"}]
                    }
                ],
                "title": "📈 Real-Time Message Throughput",
                "title_size": "16",
                "title_align": "left",
                "show_legend": True,
                "legend_layout": "horizontal",
                "legend_columns": ["avg", "min", "max", "value"],
                "yaxis": {"include_zero": True, "scale": "linear"},
                "markers": []
            },
            "layout": {"x": 6, "y": 4, "width": 6, "height": 4}
        },
        
        # Queue Health Heatmap
        {
            "definition": {
                "type": "heatmap",
                "requests": [{
                    "q": "avg:hfss.queue.pending{$env} by {queue_type}"
                }],
                "title": "🔥 Queue Heatmap",
                "title_size": "16",
                "title_align": "left"
            },
            "layout": {"x": 0, "y": 8, "width": 6, "height": 3}
        },
        
        # Database Performance
        {
            "definition": {
                "type": "timeseries",
                "requests": [
                    {
                        "q": "avg:hfss.database.connections_active{$env}",
                        "display_type": "line",
                        "style": {"palette": "purple", "line_width": "thick"},
                        "metadata": [{"alias": "Active"}]
                    },
                    {
                        "q": "avg:hfss.database.connections_idle{$env}",
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
                "yaxis": {"include_zero": True, "max": "200"},
                "markers": [
                    {
                        "value": "y = 180",
                        "display_type": "error dashed",
                        "label": "Warning Threshold"
                    }
                ]
            },
            "layout": {"x": 6, "y": 8, "width": 6, "height": 3}
        },
        
        # API Performance Distribution
        {
            "definition": {
                "type": "distribution",
                "requests": [{
                    "q": "avg:hfss.api.response_time{$env} by {endpoint}"
                }],
                "title": "⚡ API Response Time Distribution",
                "title_size": "16",
                "title_align": "left"
            },
            "layout": {"x": 0, "y": 11, "width": 6, "height": 3}
        },
        
        # GPS Tracker Status
        {
            "definition": {
                "type": "hostmap",
                "requests": {
                    "fill": {
                        "q": "avg:hfss.gps_tcp.active_connections{$env} by {device_id}"
                    }
                },
                "title": "🗺️ GPS Device Map",
                "title_size": "16",
                "title_align": "left",
                "no_metric_hosts": False,
                "no_group_hosts": True,
                "style": {
                    "palette": "green_to_orange",
                    "palette_flip": False
                }
            },
            "layout": {"x": 6, "y": 11, "width": 6, "height": 3}
        },
        
        # Top Lists
        {
            "definition": {
                "type": "toplist",
                "requests": [{
                    "q": "top(avg:hfss.database.table_size{$env} by {table}, 10)"
                }],
                "title": "📊 Largest Tables",
                "title_size": "16",
                "title_align": "left"
            },
            "layout": {"x": 0, "y": 14, "width": 4, "height": 3}
        },
        {
            "definition": {
                "type": "toplist",
                "requests": [{
                    "q": "top(sum:hfss.api.requests{$env} by {endpoint}.as_rate(), 10)"
                }],
                "title": "🎯 Busiest Endpoints",
                "title_size": "16",
                "title_align": "left"
            },
            "layout": {"x": 4, "y": 14, "width": 4, "height": 3}
        },
        {
            "definition": {
                "type": "toplist",
                "requests": [{
                    "q": "top(avg:hfss.live.points_processed{$env} by {device_id}, 10)"
                }],
                "title": "🏆 Most Active Devices",
                "title_size": "16",
                "title_align": "left"
            },
            "layout": {"x": 8, "y": 14, "width": 4, "height": 3}
        },
        
        # Alert Summary
        {
            "definition": {
                "type": "alert_graph",
                "alert_id": "",
                "viz_type": "timeseries",
                "title": "🚨 Alert Status",
                "title_size": "16",
                "title_align": "left"
            },
            "layout": {"x": 0, "y": 17, "width": 12, "height": 3}
        },
        
        # Info Cards
        {
            "definition": {
                "type": "note",
                "content": "# 🎮 Quick Actions\n\n[📊 View Metrics Explorer](https://app.datadoghq.eu/metric/explorer)\n\n[📝 View Logs](https://app.datadoghq.eu/logs)\n\n[🔍 APM Traces](https://app.datadoghq.eu/apm/traces)\n\n[⚙️ Settings](https://app.datadoghq.eu/account/settings)",
                "background_color": "vivid_blue",
                "font_size": "14",
                "text_align": "left",
                "vertical_align": "top",
                "show_tick": False,
                "has_padding": True
            },
            "layout": {"x": 0, "y": 20, "width": 3, "height": 2}
        },
        {
            "definition": {
                "type": "note",
                "content": "# 🎯 SLA Targets\n\n✅ **Uptime**: 99.9%\n\n⚡ **Response Time**: < 500ms\n\n📊 **Message Rate**: > 100/sec\n\n🔄 **Queue Lag**: < 1 min",
                "background_color": "vivid_green",
                "font_size": "14",
                "text_align": "left",
                "vertical_align": "top",
                "show_tick": False,
                "has_padding": True
            },
            "layout": {"x": 3, "y": 20, "width": 3, "height": 2}
        },
        {
            "definition": {
                "type": "note",
                "content": "# ⚠️ Alert Thresholds\n\n🔴 **Critical**: DLQ > 100\n\n🟡 **Warning**: Queue > 1000\n\n🔴 **Critical**: No data 5min\n\n🟡 **Warning**: DB > 80%",
                "background_color": "vivid_orange",
                "font_size": "14",
                "text_align": "left",
                "vertical_align": "top",
                "show_tick": False,
                "has_padding": True
            },
            "layout": {"x": 6, "y": 20, "width": 3, "height": 2}
        },
        {
            "definition": {
                "type": "note",
                "content": "# 📞 On-Call\n\n**Primary**: Team Lead\n\n**Backup**: DevOps\n\n**Escalation**: 15 min\n\n[📱 PagerDuty](https://app.pagerduty.com)",
                "background_color": "vivid_purple",
                "font_size": "14",
                "text_align": "left",
                "vertical_align": "top",
                "show_tick": False,
                "has_padding": True
            },
            "layout": {"x": 9, "y": 20, "width": 3, "height": 2}
        }
    ],
    "template_variables": [
        {
            "name": "env",
            "prefix": "env",
            "available_values": ["production", "development"],
            "default": "production"
        }
    ],
    "layout_type": "ordered",
    "reflow_type": "fixed",
    "notify_list": []
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
    print("  🔥 Heatmaps for queue visualization")
    print("  🗺️ Device mapping")
    print("  🏆 Top lists for key metrics")
    print("  🎮 Quick action buttons")
    print("  📊 SLA and threshold cards")
    print("  🎯 Environment selector (prod/dev)")
    print("\n💡 Pro tip: Use the env dropdown to switch between production and development!")
else:
    print(f"❌ Failed: {response.status_code}")
    print(response.text)