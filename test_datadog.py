#!/usr/bin/env python3
"""
Test script to verify Datadog integration is working
"""
import os
import sys
from dotenv import load_dotenv
import requests
import json
from datetime import datetime

# Load environment variables
load_dotenv()

def test_datadog_connection():
    """Test if we can connect to Datadog API"""
    dd_api_key = os.getenv('DD_API_KEY')
    dd_app_key = os.getenv('DD_APP_KEY')
    
    if not dd_api_key or not dd_app_key:
        print("❌ DD_API_KEY or DD_APP_KEY not found in environment")
        return False
    
    print(f"✅ Datadog keys found in environment")
    print(f"   API Key: {dd_api_key[:8]}...")
    print(f"   App Key: {dd_app_key[:8]}...")
    
    # Test API connectivity
    headers = {
        'DD-API-KEY': dd_api_key,
        'DD-APPLICATION-KEY': dd_app_key,
        'Content-Type': 'application/json'
    }
    
    # 1. Validate API key
    print("\n1. Testing API key validation...")
    validate_url = "https://api.datadoghq.com/api/v1/validate"
    try:
        response = requests.get(validate_url, headers=headers)
        if response.status_code == 200:
            print("   ✅ API key is valid")
        else:
            print(f"   ❌ API key validation failed: {response.status_code}")
            print(f"   Response: {response.text}")
            return False
    except Exception as e:
        print(f"   ❌ Error validating API key: {e}")
        return False
    
    # 2. Send a test event
    print("\n2. Sending test event to Datadog...")
    event_url = "https://api.datadoghq.com/api/v1/events"
    event_data = {
        "title": "HFSS Platform Test Event",
        "text": f"Test event from HFSS monitoring system at {datetime.now().isoformat()}",
        "priority": "normal",
        "tags": ["test", "hfss", "monitoring"],
        "alert_type": "info"
    }
    
    try:
        response = requests.post(event_url, headers=headers, json=event_data)
        if response.status_code in [200, 202]:
            print("   ✅ Test event sent successfully")
            result = response.json()
            if 'event' in result:
                print(f"   Event ID: {result['event'].get('id', 'N/A')}")
        else:
            print(f"   ❌ Failed to send event: {response.status_code}")
            print(f"   Response: {response.text}")
    except Exception as e:
        print(f"   ❌ Error sending event: {e}")
    
    # 3. Query recent events
    print("\n3. Querying recent events...")
    import time
    end_time = int(time.time())
    start_time = end_time - 3600  # Last hour
    
    query_url = f"https://api.datadoghq.com/api/v1/events?start={start_time}&end={end_time}&tags=hfss"
    
    try:
        response = requests.get(query_url, headers=headers)
        if response.status_code == 200:
            events = response.json().get('events', [])
            print(f"   ✅ Found {len(events)} HFSS events in the last hour")
            for event in events[:5]:  # Show first 5
                print(f"      - {event.get('title', 'N/A')} at {event.get('date_happened', 'N/A')}")
        else:
            print(f"   ❌ Failed to query events: {response.status_code}")
    except Exception as e:
        print(f"   ❌ Error querying events: {e}")
    
    # 4. Test metrics API (if DogStatsD is configured)
    print("\n4. Testing metrics submission...")
    try:
        from datadog import initialize, api, statsd
        
        initialize(
            api_key=dd_api_key,
            app_key=dd_app_key
        )
        
        # Send a test metric
        api.Metric.send(
            metric='hfss.test.metric',
            points=1,
            tags=['test:true', 'source:manual_test']
        )
        print("   ✅ Test metric sent (may take a few minutes to appear)")
        
    except ImportError:
        print("   ⚠️  Datadog library not installed (pip install datadog)")
    except Exception as e:
        print(f"   ❌ Error sending metric: {e}")
    
    # 5. Check for local DogStatsD agent
    print("\n5. Checking for local DogStatsD agent...")
    dd_host = os.getenv('DD_AGENT_HOST', 'localhost')
    dd_port = int(os.getenv('DD_DOGSTATSD_PORT', 8125))
    
    import socket
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(1)
        # Try to send a test metric to DogStatsD
        test_metric = b"hfss.test.connection:1|c|#test:true"
        sock.sendto(test_metric, (dd_host, dd_port))
        print(f"   ✅ DogStatsD agent appears to be listening on {dd_host}:{dd_port}")
    except socket.error:
        print(f"   ⚠️  No DogStatsD agent found on {dd_host}:{dd_port}")
        print("      (This is normal if Datadog Agent is not running locally)")
    finally:
        sock.close()
    
    return True

def check_hfss_events():
    """Check for HFSS-specific events in Datadog"""
    print("\n" + "="*60)
    print("CHECKING HFSS PLATFORM EVENTS IN DATADOG")
    print("="*60)
    
    dd_api_key = os.getenv('DD_API_KEY')
    dd_app_key = os.getenv('DD_APP_KEY')
    
    headers = {
        'DD-API-KEY': dd_api_key,
        'DD-APPLICATION-KEY': dd_app_key
    }
    
    # Search for different event types
    event_searches = [
        ("Platform startup", "HFSS Platform Started"),
        ("Test alerts", "Test Alert"),
        ("Queue alerts", "Queue"),
        ("Error events", "error")
    ]
    
    import time
    end_time = int(time.time())
    start_time = end_time - 86400  # Last 24 hours
    
    for search_name, search_term in event_searches:
        print(f"\nSearching for {search_name} events...")
        query_url = f"https://api.datadoghq.com/api/v1/events?start={start_time}&end={end_time}"
        
        try:
            response = requests.get(query_url, headers=headers)
            if response.status_code == 200:
                all_events = response.json().get('events', [])
                matching = [e for e in all_events if search_term.lower() in e.get('title', '').lower()]
                if matching:
                    print(f"   Found {len(matching)} matching events:")
                    for event in matching[:3]:
                        from datetime import datetime
                        timestamp = datetime.fromtimestamp(event.get('date_happened', 0))
                        print(f"   - {event.get('title')} at {timestamp.isoformat()}")
                        print(f"     Tags: {', '.join(event.get('tags', []))}")
                else:
                    print(f"   No {search_name} events found")
        except Exception as e:
            print(f"   Error: {e}")

if __name__ == "__main__":
    print("DATADOG INTEGRATION TEST")
    print("========================\n")
    
    if test_datadog_connection():
        check_hfss_events()
        print("\n✅ Datadog integration test completed")
        print("\n📊 Check your Datadog dashboard at:")
        print("   https://app.datadoghq.com/event/stream")
        print("   https://app.datadoghq.com/metric/explorer")
    else:
        print("\n❌ Datadog integration test failed")
        sys.exit(1)