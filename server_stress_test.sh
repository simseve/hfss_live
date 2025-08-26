#!/bin/bash
# Heavy stress test to push server to its limits - 100 different flights

echo "🔥🔥🔥 HEAVY STRESS TEST - PUSHING SERVER TO FLAMES 🔥🔥🔥"
echo "=========================================================="
echo ""

TOKEN="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJwaWxvdF9pZCI6IjY4YWFkYmRjNWRhNTI1MDYwZWRhYWVjMiIsInJhY2VfaWQiOiI2OGFhZGJiODVkYTUyNTA2MGVkYWFlYmYiLCJwaWxvdF9uYW1lIjoiU2ltb25lIFNldmVyaW5pIiwiZXhwIjoxNzk2MTY5NTk5LCJyYWNlIjp7Im5hbWUiOiJIRlNTIEFwcCBUZXN0aW5nIiwiZGF0ZSI6IjIwMjUtMDEtMDEiLCJ0aW1lem9uZSI6IkV1cm9wZS9Sb21lIiwibG9jYXRpb24iOiJMYXZlbm8iLCJlbmRfZGF0ZSI6IjIwMjYtMTItMDEifSwiZW5kcG9pbnRzIjp7ImxpdmUiOiIvbGl2ZSIsInVwbG9hZCI6Ii91cGxvYWQifX0.MU5OrqbbTRX36Qves9wDx62btbBWkumVX_WYfmXqsYo"
URL="http://localhost:5012/tracking/live?token=$TOKEN"
USERS=100
ROUNDS=10

echo "📊 Configuration:"
echo "  Simulated flights: $USERS (each with unique flight_id)"
echo "  Rounds: $ROUNDS"
echo "  Total requests: $((USERS * ROUNDS))"
echo "  Points per request: 20"
echo "  Total points to write: $((USERS * ROUNDS * 20))"
echo ""

echo "🔍 Initial System State:"
docker stats hfsslive --no-stream | tail -1
echo ""

# Generate unique flight IDs for each user that persist across rounds
declare -a FLIGHT_IDS
for user in $(seq 1 $USERS); do
    FLIGHT_IDS[$user]="flight-$(uuidgen | cut -c1-8)-user-${user}"
done

echo "🚀 LAUNCHING HEAVY LOAD..."
echo "  Created $USERS unique flight IDs"
echo ""

for round in $(seq 1 $ROUNDS); do
    echo "🔥 Round $round/$ROUNDS - Sending $USERS concurrent requests..."
    
    # Launch all users simultaneously
    for user in $(seq 1 $USERS); do
        # Use the persistent flight ID for this user
        FLIGHT_ID="${FLIGHT_IDS[$user]}"
        
        # Generate 20 points with realistic movement (continuing from previous round)
        POINTS='['
        BASE_TIME=$(date -u -d "$((round * 20)) seconds ago" '+%s')
        
        for p in $(seq 0 19); do
            # Simulate flight path progression
            LAT=$(echo "45.607 + $user * 0.0001 + ($round * 20 + $p) * 0.00001" | bc -l)
            LON=$(echo "8.871 + $user * 0.0001 + ($round * 20 + $p) * 0.00001" | bc -l)
            ALT=$((500 + user + (round * 5) + p))
            BARO_ALT=$(echo "$ALT + $p * 0.1" | bc -l)
            TIME=$(date -u -d "@$((BASE_TIME + p))" '+%Y-%m-%dT%H:%M:%S.000Z')
            
            if [ $p -gt 0 ]; then POINTS="$POINTS,"; fi
            POINTS="$POINTS{\"lat\":$LAT,\"lon\":$LON,\"elevation\":$ALT,\"barometric_altitude\":$BARO_ALT,\"datetime\":\"$TIME\"}"
        done
        POINTS="$POINTS]"
        
        # Send request in background
        curl -s -X POST \
            -H "Content-Type: application/json" \
            -d "{\"track_points\":$POINTS,\"flight_id\":\"$FLIGHT_ID\",\"device_id\":\"device-$user\"}" \
            "$URL" \
            -o /dev/null -w "F${user}: %{http_code}/%{time_total}s " &
    done
    
    # Wait for all requests to complete
    wait
    echo ""
    echo "  ✅ Round $round complete"
    
    # Check system state
    echo -n "  System: "
    docker stats hfsslive --no-stream --format "CPU: {{.CPUPerc}} MEM: {{.MemUsage}}"
    
    # Brief pause between rounds (simulating 10-second intervals)
    if [ $round -lt $ROUNDS ]; then
        echo "  Waiting 10 seconds before next round..."
        sleep 10
    fi
done

echo ""
echo "📊 Final System State:"
docker stats hfsslive --no-stream | tail -1
echo ""

echo "🔍 Checking health:"
curl -s http://localhost:5012/health | python3 -c "
import sys, json
d=json.load(sys.stdin)
print('  Status:', d.get('status'))
print('  Redis:', d.get('redis', {}).get('status'))
print('  Database:', d.get('database', {}).get('status'))
pool = d.get('redis', {}).get('connection_pool', {})
if pool and 'error' not in pool:
    print('  Redis Connections:', pool.get('in_use_connections', 'N/A'), '/', pool.get('max_connections', 'N/A'))
" 2>/dev/null || echo "  Health check failed"

echo ""
echo "📈 Checking processing results:"
echo -n "  Recent batches processed: "
docker logs hfsslive --tail 200 2>&1 | grep "Successfully processed" | wc -l

echo -n "  Recent points written: "
docker logs hfsslive --tail 200 2>&1 | grep "Successfully processed" | grep -o "[0-9]* live points" | awk '{sum+=$1} END {print sum}'

echo ""
echo "🔥 Database activity:"
docker exec hfss-timescaledb psql -U py_ll_user -d hfss -t -c "
    SELECT 
        COUNT(DISTINCT flight_id) as flights,
        COUNT(*) as total_points,
        MAX(datetime) - MIN(datetime) as time_span
    FROM live_track_points 
    WHERE flight_id LIKE 'flight-%'
    AND datetime > NOW() - INTERVAL '10 minutes';
" 2>/dev/null | grep -v "^$" || echo "  Could not check database"

echo ""
echo "✅ Stress test complete!"
echo "  Simulated $USERS different flights"
echo "  Sent $((USERS * ROUNDS)) requests"
echo "  Total points attempted: $((USERS * ROUNDS * 20))"