#!/usr/bin/env python3
"""Check flight sources for the race"""

from database.db_replica import get_replica_db
from database.models import Flight

race_id = "68aadbb85da525060edaaebf"

with next(get_replica_db()) as db:
    flights = db.query(Flight).filter(Flight.race_id == race_id).all()
    
    print(f"Found {len(flights)} flights for race {race_id}\n")
    
    for flight in flights:
        print(f"Flight ID: {flight.id[:8]}...")
        print(f"  Pilot: {flight.pilot_name}")
        print(f"  Source: '{flight.source}'")
        print(f"  Created: {flight.created_at}")
        print(f"  Last fix: {flight.last_fix.get('datetime') if flight.last_fix else 'None'}")
        print()