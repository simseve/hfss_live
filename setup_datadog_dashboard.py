#!/usr/bin/env python3
"""
Setup Datadog Dashboard for HFSS Live Platform
This creates a comprehensive dashboard in your Datadog account
"""
import os
import json
import requests
from dotenv import load_dotenv

load_dotenv()

def create_dashboard():
    """Create the HFSS dashboard in Datadog"""
    
    DD_API_KEY = os.getenv('DD_API_KEY')
    DD_APP_KEY = os.getenv('DD_APP_KEY')
    
    if not DD_API_KEY or not DD_APP_KEY:
        print("❌ DD_API_KEY and DD_APP_KEY must be set in .env")
        return False
    
    # Read dashboard configuration
    with open('datadog_dashboard.json', 'r') as f:
        dashboard_config = json.load(f)
    
    # Datadog API endpoint (EU site)
    url = "https://api.datadoghq.eu/api/v1/dashboard"
    
    headers = {
        'DD-API-KEY': DD_API_KEY,
        'DD-APPLICATION-KEY': DD_APP_KEY,
        'Content-Type': 'application/json'
    }
    
    # Create the dashboard
    response = requests.post(url, headers=headers, json=dashboard_config)
    
    if response.status_code in [200, 201]:
        dashboard = response.json()
        dashboard_id = dashboard.get('id')
        dashboard_url = f"https://app.datadoghq.eu/dashboard/{dashboard_id}"
        
        print("✅ Dashboard created successfully!")
        print(f"📊 Dashboard ID: {dashboard_id}")
        print(f"🔗 View at: {dashboard_url}")
        
        # Save dashboard ID for future updates
        with open('.datadog_dashboard_id', 'w') as f:
            f.write(dashboard_id)
        
        return dashboard_url
    else:
        print(f"❌ Failed to create dashboard: {response.status_code}")
        print(f"Response: {response.text}")
        return None

def create_monitors():
    """Create alert monitors for critical metrics"""
    
    DD_API_KEY = os.getenv('DD_API_KEY')
    DD_APP_KEY = os.getenv('DD_APP_KEY')
    
    monitors = [
        {
            "name": "HFSS: High Dead Letter Queue",
            "type": "metric alert",
            "query": "sum(last_5m):sum:hfss.queue.dlq_size{*} > 100",
            "message": "Dead Letter Queue has {{value}} items! Check processing errors. @all",
            "tags": ["service:hfss-live", "severity:high"],
            "options": {
                "thresholds": {"critical": 100, "warning": 50},
                "notify_no_data": False,
                "require_full_window": False
            }
        },
        {
            "name": "HFSS: No Live Data",
            "type": "metric alert",
            "query": "sum(last_5m):avg:hfss.live.messages_per_second{*} < 0.1",
            "message": "No live tracking data received for 5 minutes! @all",
            "tags": ["service:hfss-live", "severity:warning"],
            "options": {
                "thresholds": {"critical": 0.1},
                "notify_no_data": True,
                "no_data_timeframe": 10
            }
        },
        {
            "name": "HFSS: Database Connection Pool High",
            "type": "metric alert",
            "query": "avg(last_5m):avg:hfss.database.connections_active{*} > 180",
            "message": "Database connection pool is at {{value}} connections (90% of max)! @all",
            "tags": ["service:hfss-live", "severity:warning"],
            "options": {
                "thresholds": {"critical": 180, "warning": 160},
                "notify_no_data": False
            }
        },
        {
            "name": "HFSS: High API Error Rate",
            "type": "metric alert",
            "query": "sum(last_5m):sum:hfss.api.errors{*}.as_rate() > 0.05",
            "message": "API error rate is {{value}} errors/sec! Check logs. @all",
            "tags": ["service:hfss-live", "severity:high"],
            "options": {
                "thresholds": {"critical": 0.05, "warning": 0.01},
                "notify_no_data": False
            }
        }
    ]
    
    headers = {
        'DD-API-KEY': DD_API_KEY,
        'DD-APPLICATION-KEY': DD_APP_KEY,
        'Content-Type': 'application/json'
    }
    
    url = "https://api.datadoghq.eu/api/v1/monitor"
    
    print("\n📢 Creating Alert Monitors:")
    for monitor in monitors:
        response = requests.post(url, headers=headers, json=monitor)
        if response.status_code in [200, 201]:
            print(f"  ✅ {monitor['name']}")
        else:
            print(f"  ❌ Failed: {monitor['name']} - {response.status_code}")

if __name__ == "__main__":
    print("🚀 Setting up HFSS Datadog Dashboard\n")
    
    dashboard_url = create_dashboard()
    
    if dashboard_url:
        create_monitors()
        
        print("\n" + "="*50)
        print("📊 DASHBOARD SETUP COMPLETE!")
        print("="*50)
        print(f"\n🔗 Open your dashboard: {dashboard_url}")
        print("\n📌 Bookmark this URL for quick access")
        print("\n⚠️  Note: Metrics will appear as data flows in")
        print("   - Events are already visible")
        print("   - Metrics need DogStatsD agent running")
    else:
        print("\n❌ Dashboard setup failed. Check your API keys.")