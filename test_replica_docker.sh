#!/bin/bash
# Test script for verifying replica routing in Docker deployment

echo "========================================"
echo "DOCKER REPLICA ROUTING TEST"
echo "========================================"

# Your test token
TOKEN="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJwaWxvdF9pZCI6IjY4YWFkYmRjNWRhNTI1MDYwZWRhYWVjMiIsInJhY2VfaWQiOiI2OGFhZGJiODVkYTUyNTA2MGVkYWFlYmYiLCJwaWxvdF9uYW1lIjoiU2ltb25lIFNldmVyaW5pIiwiZXhwIjoxNzk2MTY5NTk5LCJyYWNlIjp7Im5hbWUiOiJIRlNTIEFwcCBUZXN0aW5nIiwiZGF0ZSI6IjIwMjUtMDEtMDEiLCJ0aW1lem9uZSI6IkV1cm9wZS9Sb21lIiwibG9jYXRpb24iOiJMYXZlbm8iLCJlbmRfZGF0ZSI6IjIwMjYtMTItMDEifSwiZW5kcG9pbnRzIjp7ImxpdmUiOiIvbGl2ZSIsInVwbG9hZCI6Ii91cGxvYWQifX0.MU5OrqbbTRX36Qves9wDx62btbBWkumVX_WYfmXqsYo"

# Base URL - adjust if needed
BASE_URL="http://localhost:8000"

echo ""
echo "1. Checking Docker containers..."
docker ps | grep hfss

echo ""
echo "2. Checking application logs for database configuration..."
docker logs hfss_live_web_1 2>&1 | grep -E "Replica|Primary|database" | tail -10

echo ""
echo "3. Testing WRITE operation (should use PRIMARY)..."
echo "   Sending a test point..."

# Generate a test point with current timestamp
CURRENT_TIME=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
LAT=$(echo "45.89 + $(date +%S) / 1000" | bc -l)
LON=$(echo "8.63 + $(date +%S) / 1000" | bc -l)
ELEVATION=$((350 + $(date +%S)))

curl -X POST "${BASE_URL}/api/live?token=${TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{\"lat\": ${LAT}, \"lon\": ${LON}, \"elevation\": ${ELEVATION}, \"datetime\": \"${CURRENT_TIME}\"}" \
  -s -w "\n   HTTP Status: %{http_code}\n"

echo ""
echo "4. Testing READ operations (should use REPLICA)..."

echo "   a) Fetching flights..."
curl -X GET "${BASE_URL}/api/flights?race_id=68aadbb85da525060edaaebf" \
  -H "Authorization: Bearer ${TOKEN}" \
  -s -w "\n   HTTP Status: %{http_code}\n" | jq -r '. | length' 2>/dev/null | xargs -I {} echo "   Found {} flights"

echo ""
echo "   b) Fetching live users..."
OPENTIME=$(date -u +"%Y-%m-%dT00:00:00Z")
curl -X GET "${BASE_URL}/api/live/users?opentime=${OPENTIME}" \
  -H "Authorization: Bearer ${TOKEN}" \
  -s -w "\n   HTTP Status: %{http_code}\n" | jq -r '. | length' 2>/dev/null | xargs -I {} echo "   Found {} active users"

echo ""
echo "5. Monitoring database connections..."
echo "   Check docker logs during operations:"
echo "   docker logs -f hfss_live_web_1 | grep -E 'replica|primary|database'"

echo ""
echo "6. Testing WebSocket connection (should use REPLICA)..."
echo "   You can test with: wscat -c 'ws://localhost:8000/api/ws/track/68aadbb85da525060edaaebf?client_id=test&token=${TOKEN}'"

echo ""
echo "========================================"
echo "TEST COMPLETE"
echo ""
echo "To verify replica routing is working:"
echo "1. Check logs: docker logs hfss_live_web_1 | grep -i replica"
echo "2. Look for:"
echo "   - 'Replica enabled via USE_REPLICA=True'"
echo "   - 'Primary endpoint: ep-rapid-violet...'"
echo "   - 'Replica endpoint: ep-muddy-sky...'"
echo "3. Monitor Neon dashboard for connection distribution"
echo "========================================"