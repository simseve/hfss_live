#!/usr/bin/env python3
"""
Create a modern cool-looking Datadog dashboard using formulas
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
                    "formulas": [{"formula": "query1"}],
                    "queries": [{
                        "data_source": "metrics",
                        "name": "query1",
                        "query": "avg:hfss.live.messages_per_second{*}",
                        "aggregator": "last"
                    }],
                    "response_format": "scalar"
                }],
                "title": "📡 Messages/sec",
                "title_size": "16",
                "title_align": "center",
                "precision": 2,
                "autoscale": True
            },
            "layout": {"x": 0, "y": 0, "width": 3, "height": 2}
        },
        {
            "definition": {
                "type": "query_value",
                "requests": [{
                    "formulas": [{"formula": "query1"}],
                    "queries": [{
                        "data_source": "metrics",
                        "name": "query1",
                        "query": "avg:hfss.live.active_flights{*}",
                        "aggregator": "last"
                    }],
                    "response_format": "scalar",
                    "conditional_formats": [
                        {"comparator": ">", "value": 50, "palette": "green"},
                        {"comparator": ">", "value": 20, "palette": "yellow"},
                        {"comparator": ">=", "value": 0, "palette": "gray"}
                    ]
                }],
                "title": "✈️ Active Flights",
                "title_size": "16",
                "title_align": "center",
                "precision": 0
            },
            "layout": {"x": 3, "y": 0, "width": 3, "height": 2}
        },
        {
            "definition": {
                "type": "query_value",
                "requests": [{
                    "formulas": [{"formula": "query1"}],
                    "queries": [{
                        "data_source": "metrics",
                        "name": "query1",
                        "query": "sum:hfss.queue.dlq_size{*}",
                        "aggregator": "last"
                    }],
                    "response_format": "scalar",
                    "conditional_formats": [
                        {"comparator": ">", "value": 100, "palette": "red"},
                        {"comparator": ">", "value": 10, "palette": "yellow"},
                        {"comparator": "<=", "value": 10, "palette": "green"}
                    ]
                }],
                "title": "⚠️ Dead Letters",
                "title_size": "16",
                "title_align": "center",
                "precision": 0
            },
            "layout": {"x": 6, "y": 0, "width": 3, "height": 2}
        },
        {
            "definition": {
                "type": "query_value",
                "requests": [{
                    "formulas": [{"formula": "query1"}],
                    "queries": [{
                        "data_source": "metrics",
                        "name": "query1",
                        "query": "avg:hfss.gps_tcp.active_connections{*}",
                        "aggregator": "last"
                    }],
                    "response_format": "scalar"
                }],
                "title": "🔌 GPS Connections",
                "title_size": "16",
                "title_align": "center",
                "precision": 0
            },
            "layout": {"x": 9, "y": 0, "width": 3, "height": 2}
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
            "layout": {"x": 0, "y": 2, "width": 6, "height": 4}
        },
        
        # Real-time Throughput Graph
        {
            "definition": {
                "type": "timeseries",
                "requests": [{
                    "formulas": [{"formula": "query1", "alias": "Messages/sec"}],
                    "queries": [{
                        "data_source": "metrics",
                        "name": "query1",
                        "query": "avg:hfss.live.messages_per_second{*}"
                    }],
                    "response_format": "timeseries",
                    "style": {
                        "palette": "cool",
                        "line_type": "solid",
                        "line_width": "normal"
                    },
                    "display_type": "area"
                }],
                "title": "📈 Real-Time Message Throughput",
                "title_size": "16",
                "title_align": "left",
                "show_legend": True,
                "legend_layout": "horizontal",
                "legend_columns": ["avg", "min", "max", "value"],
                "yaxis": {"include_zero": True}
            },
            "layout": {"x": 6, "y": 2, "width": 6, "height": 4}
        },
        
        # Queue Health
        {
            "definition": {
                "type": "timeseries",
                "requests": [
                    {
                        "formulas": [{"formula": "query1", "alias": "Queue Pending"}],
                        "queries": [{
                            "data_source": "metrics",
                            "name": "query1",
                            "query": "sum:hfss.queue.pending{*} by {queue_type}"
                        }],
                        "response_format": "timeseries",
                        "style": {"palette": "warm"},
                        "display_type": "bars"
                    },
                    {
                        "formulas": [{"formula": "query2", "alias": "Dead Letter Queue"}],
                        "queries": [{
                            "data_source": "metrics",
                            "name": "query2",
                            "query": "sum:hfss.queue.dlq_size{*}"
                        }],
                        "response_format": "timeseries",
                        "style": {"palette": "red", "line_width": "thick"},
                        "display_type": "line"
                    }
                ],
                "title": "🔥 Queue Status",
                "title_size": "16",
                "title_align": "left",
                "show_legend": True
            },
            "layout": {"x": 0, "y": 6, "width": 6, "height": 3}
        },
        
        # Database Performance
        {
            "definition": {
                "type": "timeseries",
                "requests": [
                    {
                        "formulas": [{"formula": "query1", "alias": "Active Connections"}],
                        "queries": [{
                            "data_source": "metrics",
                            "name": "query1",
                            "query": "avg:hfss.database.connections_active{*}"
                        }],
                        "response_format": "timeseries",
                        "style": {"palette": "purple", "line_width": "thick"},
                        "display_type": "line"
                    },
                    {
                        "formulas": [{"formula": "query2", "alias": "Idle Connections"}],
                        "queries": [{
                            "data_source": "metrics",
                            "name": "query2",
                            "query": "avg:hfss.database.connections_idle{*}"
                        }],
                        "response_format": "timeseries",
                        "style": {"palette": "gray", "line_width": "thin"},
                        "display_type": "line"
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
            "layout": {"x": 6, "y": 6, "width": 6, "height": 3}
        },
        
        # API Performance
        {
            "definition": {
                "type": "timeseries",
                "requests": [{
                    "formulas": [{"formula": "query1"}],
                    "queries": [{
                        "data_source": "metrics",
                        "name": "query1",
                        "query": "avg:hfss.api.response_time{*} by {endpoint}"
                    }],
                    "response_format": "timeseries",
                    "display_type": "line"
                }],
                "title": "⚡ API Response Times",
                "title_size": "16",
                "title_align": "left",
                "show_legend": True,
                "yaxis": {"include_zero": False}
            },
            "layout": {"x": 0, "y": 9, "width": 6, "height": 3}
        },
        
        # Top Lists
        {
            "definition": {
                "type": "toplist",
                "requests": [{
                    "formulas": [{
                        "formula": "query1",
                        "limit": {"count": 10, "order": "desc"}
                    }],
                    "queries": [{
                        "data_source": "metrics",
                        "name": "query1",
                        "query": "avg:hfss.database.table_size{*} by {table}",
                        "aggregator": "last"
                    }],
                    "response_format": "scalar"
                }],
                "title": "📊 Largest Tables",
                "title_size": "16",
                "title_align": "left"
            },
            "layout": {"x": 6, "y": 9, "width": 3, "height": 3}
        },
        {
            "definition": {
                "type": "toplist",
                "requests": [{
                    "formulas": [{
                        "formula": "query1",
                        "limit": {"count": 10, "order": "desc"}
                    }],
                    "queries": [{
                        "data_source": "metrics",
                        "name": "query1",
                        "query": "sum:hfss.api.requests{*} by {endpoint}.as_rate()",
                        "aggregator": "sum"
                    }],
                    "response_format": "scalar"
                }],
                "title": "🎯 Busiest Endpoints",
                "title_size": "16",
                "title_align": "left"
            },
            "layout": {"x": 9, "y": 9, "width": 3, "height": 3}
        },
        
        # Info Cards
        {
            "definition": {
                "type": "note",
                "content": "# 🎮 Quick Actions\n\n[📊 Metrics](https://app.datadoghq.eu/metric/explorer)\n[📝 Logs](https://app.datadoghq.eu/logs)\n[🔍 APM](https://app.datadoghq.eu/apm/traces)",
                "background_color": "blue",
                "font_size": "14",
                "text_align": "left",
                "vertical_align": "top",
                "show_tick": False,
                "has_padding": True
            },
            "layout": {"x": 0, "y": 12, "width": 3, "height": 2}
        },
        {
            "definition": {
                "type": "note",
                "content": "# 🎯 SLA Targets\n\n✅ **Uptime**: 99.9%\n⚡ **Response**: < 500ms\n📊 **Rate**: > 100/sec",
                "background_color": "green",
                "font_size": "14",
                "text_align": "left",
                "vertical_align": "top",
                "show_tick": False,
                "has_padding": True
            },
            "layout": {"x": 3, "y": 12, "width": 3, "height": 2}
        },
        {
            "definition": {
                "type": "note",
                "content": "# ⚠️ Alerts\n\n🔴 **DLQ** > 100\n🟡 **Queue** > 1000\n🔴 **No data** 5min",
                "background_color": "orange",
                "font_size": "14",
                "text_align": "left",
                "vertical_align": "top",
                "show_tick": False,
                "has_padding": True
            },
            "layout": {"x": 6, "y": 12, "width": 3, "height": 2}
        },
        {
            "definition": {
                "type": "note",
                "content": "# 📞 On-Call\n\n**Primary**: Team\n**Backup**: DevOps\n**Escalation**: 15m",
                "background_color": "purple",
                "font_size": "14",
                "text_align": "left",
                "vertical_align": "top",
                "show_tick": False,
                "has_padding": True
            },
            "layout": {"x": 9, "y": 12, "width": 3, "height": 2}
        }
    ],
    "layout_type": "ordered",
    "reflow_type": "fixed"
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
    print("  📈 Real-time graphs with cool gradients")
    print("  🔥 Queue status visualization")
    print("  💾 Database monitoring with thresholds")
    print("  🏆 Top lists for key metrics")
    print("  🎮 Quick action cards")
    print("  📊 SLA and alert threshold cards")
    print("\n💡 The dashboard uses modern formula-based queries!")
else:
    print(f"❌ Failed: {response.status_code}")
    print(response.text)