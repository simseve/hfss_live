#!/usr/bin/env python3
"""Test flight separation logic"""

from datetime import datetime, timedelta, timezone
from utils.flight_separator import FlightSeparator

def test_scenarios():
    """Test various flight separation scenarios"""
    
    print("Testing Flight Separation Logic")
    print("=" * 60)
    
    # Scenario 1: No previous flight
    print("\n1. No previous flight:")
    should_create, reason = FlightSeparator.should_create_new_flight(
        device_id="test123",
        current_point={'datetime': datetime.now(timezone.utc)},
        last_flight=None,
        race_timezone="Europe/Rome"
    )
    print(f"   Should create new: {should_create}")
    print(f"   Reason: {reason}")
    assert should_create == True
    
    # Scenario 2: New day
    print("\n2. New day (crossed midnight):")
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    last_flight = {
        'last_fix': {
            'datetime': yesterday.isoformat(),
            'lat': 45.0,
            'lon': 10.0
        },
        'created_at': yesterday
    }
    should_create, reason = FlightSeparator.should_create_new_flight(
        device_id="test123",
        current_point={'datetime': datetime.now(timezone.utc)},
        last_flight=last_flight,
        race_timezone="Europe/Rome"
    )
    print(f"   Should create new: {should_create}")
    print(f"   Reason: {reason}")
    assert should_create == True
    assert reason == "new_day"
    
    # Scenario 3: Long inactivity (4 hours)
    print("\n3. Long inactivity (4 hours):")
    four_hours_ago = datetime.now(timezone.utc) - timedelta(hours=4)
    last_flight = {
        'last_fix': {
            'datetime': four_hours_ago.isoformat(),
            'lat': 45.0,
            'lon': 10.0
        },
        'created_at': four_hours_ago
    }
    should_create, reason = FlightSeparator.should_create_new_flight(
        device_id="test123",
        current_point={'datetime': datetime.now(timezone.utc)},
        last_flight=last_flight,
        race_timezone="Europe/Rome"
    )
    print(f"   Should create new: {should_create}")
    print(f"   Reason: {reason}")
    assert should_create == True
    assert reason.startswith("inactive_")
    
    # Scenario 4: Short gap (30 minutes) - continue same flight
    print("\n4. Short gap (30 minutes) - same flight:")
    thirty_min_ago = datetime.now(timezone.utc) - timedelta(minutes=30)
    last_flight = {
        'last_fix': {
            'datetime': thirty_min_ago.isoformat(),
            'lat': 45.0,
            'lon': 10.0
        },
        'created_at': thirty_min_ago
    }
    should_create, reason = FlightSeparator.should_create_new_flight(
        device_id="test123",
        current_point={'datetime': datetime.now(timezone.utc)},
        last_flight=last_flight,
        race_timezone="Europe/Rome"
    )
    print(f"   Should create new: {should_create}")
    print(f"   Reason: {reason}")
    assert should_create == False
    assert reason == "continue_existing"
    
    # Scenario 5: Landed state
    print("\n5. Landed for 15 minutes:")
    landed_time = datetime.now(timezone.utc) - timedelta(minutes=15)
    last_flight = {
        'last_fix': {
            'datetime': (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat(),
            'lat': 45.0,
            'lon': 10.0
        },
        'created_at': datetime.now(timezone.utc) - timedelta(hours=1),
        'flight_state': {
            'state': 'landed',
            'landed_at': landed_time.isoformat()
        }
    }
    should_create, reason = FlightSeparator.should_create_new_flight(
        device_id="test123",
        current_point={'datetime': datetime.now(timezone.utc)},
        last_flight=last_flight,
        race_timezone="Europe/Rome"
    )
    print(f"   Should create new: {should_create}")
    print(f"   Reason: {reason}")
    assert should_create == True
    assert reason == "landed"
    
    # Test flight ID suffix generation
    print("\n6. Flight ID suffix generation:")
    print(f"   New day suffix: {FlightSeparator.get_flight_id_suffix('new_day')}")
    print(f"   Inactive suffix: {FlightSeparator.get_flight_id_suffix('inactive_4h')}")
    print(f"   Landed suffix: {FlightSeparator.get_flight_id_suffix('landed')}")
    
    print("\n✅ All tests passed!")

if __name__ == "__main__":
    test_scenarios()