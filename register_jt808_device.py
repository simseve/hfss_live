#!/usr/bin/env python3
"""
Register a JT808 GPS tracker device in the database
"""
import sys
import jwt
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from database.db_conf import get_db
SessionLocal = get_db
from database.models import DeviceRegistration, Race
from config import settings
import uuid

def register_device(
    serial_number: str,
    race_id: str,
    pilot_id: str,
    pilot_name: str,
    device_type: str = 'jt808'
):
    """Register a JT808 device for tracking"""
    
    db = next(SessionLocal())
    try:
        # Find the race
        race = db.query(Race).filter(Race.race_id == race_id).first()
        if not race:
            print(f"❌ Race '{race_id}' not found")
            return False
            
        # Check if device already registered
        existing = db.query(DeviceRegistration).filter(
            DeviceRegistration.serial_number == serial_number,
            DeviceRegistration.race_id == race_id
        ).first()
        
        if existing:
            print(f"Device {serial_number} already registered for race {race_id}")
            # Update to active
            existing.is_active = True
            existing.updated_at = datetime.now(timezone.utc)
            db.commit()
            print(f"✅ Reactivated existing registration")
            return True
        
        # Deactivate any other registrations for this device
        db.query(DeviceRegistration).filter(
            DeviceRegistration.serial_number == serial_number,
            DeviceRegistration.is_active == True
        ).update({"is_active": False, "updated_at": datetime.now(timezone.utc)})
        
        # Create tracking token (similar to Flymaster)
        token_data = {
            'race_id': race_id,
            'pilot_id': pilot_id,
            'pilot_name': pilot_name,
            'device_type': device_type,
            'exp': (datetime.now(timezone.utc) + timedelta(days=7)).timestamp()
        }
        
        token = jwt.encode(
            token_data,
            settings.SECRET_KEY,
            algorithm="HS256"
        )
        
        # Create new registration
        registration = DeviceRegistration(
            serial_number=serial_number,
            device_type=device_type,
            pilot_token=token,
            race_uuid=race.id,
            race_id=race_id,
            pilot_id=pilot_id,
            pilot_name=pilot_name,
            is_active=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        
        db.add(registration)
        db.commit()
        
        print(f"✅ Successfully registered device {serial_number}")
        print(f"   Race: {race_id}")
        print(f"   Pilot: {pilot_name} ({pilot_id})")
        print(f"   Type: {device_type}")
        print(f"   Active: True")
        print(f"   Token expires: {datetime.fromtimestamp(token_data['exp'], timezone.utc)}")
        
        return True
        
    except Exception as e:
        db.rollback()
        print(f"❌ Error registering device: {e}")
        return False
    finally:
        db.close()


def list_devices(race_id: str = None):
    """List registered devices"""
    db = next(SessionLocal())
    try:
        query = db.query(DeviceRegistration)
        if race_id:
            query = query.filter(DeviceRegistration.race_id == race_id)
        
        devices = query.order_by(DeviceRegistration.created_at.desc()).all()
        
        if not devices:
            print("No devices registered")
            return
            
        print(f"\n{'Serial Number':<15} {'Type':<10} {'Race':<15} {'Pilot':<20} {'Active':<8} {'Created'}")
        print("-" * 90)
        
        for device in devices:
            created = device.created_at.strftime("%Y-%m-%d %H:%M")
            print(f"{device.serial_number:<15} {device.device_type:<10} {device.race_id:<15} "
                  f"{device.pilot_name:<20} {'✓' if device.is_active else '✗':<8} {created}")
                  
    finally:
        db.close()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Register JT808 GPS tracker device')
    subparsers = parser.add_subparsers(dest='command', help='Commands')
    
    # Register command
    register_parser = subparsers.add_parser('register', help='Register a new device')
    register_parser.add_argument('serial_number', help='Device serial number (e.g., 9590046863)')
    register_parser.add_argument('race_id', help='Race ID')
    register_parser.add_argument('pilot_id', help='Pilot ID')
    register_parser.add_argument('pilot_name', help='Pilot name')
    register_parser.add_argument('--type', default='jt808', help='Device type (default: jt808)')
    
    # List command
    list_parser = subparsers.add_parser('list', help='List registered devices')
    list_parser.add_argument('--race', help='Filter by race ID')
    
    args = parser.parse_args()
    
    if args.command == 'register':
        register_device(
            args.serial_number,
            args.race_id,
            args.pilot_id,
            args.pilot_name,
            args.type
        )
    elif args.command == 'list':
        list_devices(args.race)
    else:
        # If no command, show help
        parser.print_help()
        print("\nExamples:")
        print("  Register device:")
        print("    python register_jt808_device.py register 9590046863 race1 pilot1 'John Doe'")
        print("\n  List devices:")
        print("    python register_jt808_device.py list")
        print("    python register_jt808_device.py list --race race1")