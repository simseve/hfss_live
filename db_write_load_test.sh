#!/bin/bash
# Database write load test - 100 different flights

echo "🔥 Database Write Load Test - 100 Different Flights"
echo "=================================================="
echo ""

# Generate 100 different flight IDs and send points
echo "📊 Generating and sending points for 100 flights..."

for i in $(seq 1 100); do
    FLIGHT_ID="load-test-$(uuidgen | cut -c1-8)-flight-$i"
    
    # Generate 10 points with slightly different timestamps
    POINTS='['
    for j in $(seq 0 9); do
        LAT=$(echo "45.607 + $i * 0.0001 + $j * 0.00001" | bc -l)
        LON=$(echo "8.871 + $i * 0.0001 + $j * 0.00001" | bc -l)
        ALT=$((500 + i + j))
        TIME=$(date -u -d "$j seconds ago" '+%Y-%m-%dT%H:%M:%S.000Z')
        
        if [ $j -gt 0 ]; then POINTS="$POINTS,"; fi
        POINTS="$POINTS{\"lat\":$LAT,\"lon\":$LON,\"elevation\":$ALT,\"barometric_altitude\":$ALT.5,\"datetime\":\"$TIME\"}"
    done
    POINTS="$POINTS]"
    
    # Send to API (will get 401 but might queue)
    curl -s -X POST \
        -H "Content-Type: application/json" \
        -d "{\"track_points\":$POINTS,\"flight_id\":\"$FLIGHT_ID\",\"device_id\":\"test-device-$i\"}" \
        http://localhost:5012/api/v2/live/add_live_track_points \
        -o /dev/null -w "Flight $i: %{http_code} in %{time_total}s\n" &
    
    # Every 10 flights, wait for completion
    if [ $((i % 10)) -eq 0 ]; then
        wait
        echo "  Sent $i flights..."
    fi
done

wait
echo ""
echo "✅ Sent 100 flights with 10 points each (1000 total points)"
echo ""

# Check database for results
echo "📊 Checking database for recent points..."
docker exec hfss-timescaledb psql -U py_ll_user -d hfss -t -c "
    SELECT 
        COUNT(*) as total_points,
        COUNT(DISTINCT flight_id) as unique_flights,
        MIN(datetime) as earliest,
        MAX(datetime) as latest
    FROM live_track_points 
    WHERE datetime > NOW() - INTERVAL '5 minutes'
    AND flight_id LIKE 'load-test-%';
" 2>/dev/null || echo "Could not check database"

echo ""
echo "📈 System status after load:"
docker stats hfsslive --no-stream | tail -1
curl -s http://localhost:5012/health | python3 -c "import sys, json; d=json.load(sys.stdin); print('Health:', d.get('status')); print('Redis:', d.get('redis', {}).get('status')); print('DB:', d.get('database', {}).get('status'))" 2>/dev/null