#!/bin/bash
# Script to verify Docker startup with replica configuration

echo "================================================"
echo "HFSS LIVE DOCKER STARTUP CHECK"
echo "================================================"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo ""
echo "1. Checking Docker Compose status..."
docker-compose ps

echo ""
echo "2. Checking environment variables in container..."
docker exec hfss_live_web_1 sh -c 'echo "USE_REPLICA=$USE_REPLICA"'
docker exec hfss_live_web_1 sh -c 'echo "DATABASE_URI exists: $([ ! -z "$DATABASE_URI" ] && echo Yes || echo No)"'
docker exec hfss_live_web_1 sh -c 'echo "DATABASE_REPLICA_URI exists: $([ ! -z "$DATABASE_REPLICA_URI" ] && echo Yes || echo No)"'

echo ""
echo "3. Checking application startup logs..."
echo "   Looking for database configuration..."
docker logs hfss_live_web_1 2>&1 | grep -A2 "Database connection check" | tail -5

echo ""
echo "   Looking for replica configuration..."
docker logs hfss_live_web_1 2>&1 | grep -E "Replica|USE_REPLICA" | tail -5

echo ""
echo "4. Testing health endpoint..."
HEALTH_RESPONSE=$(curl -s -w "\nSTATUS:%{http_code}" http://localhost:8000/health)
HTTP_STATUS=$(echo "$HEALTH_RESPONSE" | grep "STATUS:" | cut -d: -f2)

if [ "$HTTP_STATUS" = "200" ]; then
    echo -e "   ${GREEN}✅ Health check passed (HTTP $HTTP_STATUS)${NC}"
    echo "$HEALTH_RESPONSE" | grep -v "STATUS:" | jq -r '.database_status, .redis_status' 2>/dev/null
else
    echo -e "   ${RED}❌ Health check failed (HTTP $HTTP_STATUS)${NC}"
fi

echo ""
echo "5. Checking for startup errors..."
ERROR_COUNT=$(docker logs hfss_live_web_1 2>&1 | grep -i "error\|exception\|failed" | grep -v "INFO" | wc -l)
if [ "$ERROR_COUNT" -eq "0" ]; then
    echo -e "   ${GREEN}✅ No errors found in logs${NC}"
else
    echo -e "   ${YELLOW}⚠️  Found $ERROR_COUNT potential errors in logs${NC}"
    echo "   Recent errors:"
    docker logs hfss_live_web_1 2>&1 | grep -i "error\|exception\|failed" | grep -v "INFO" | tail -3
fi

echo ""
echo "6. Database connection test..."
docker exec hfss_live_web_1 python -c "
from database.db_replica import test_replica_connection
success, message = test_replica_connection()
print(f'   Replica test: {message}')
" 2>/dev/null || echo "   Could not test from within container"

echo ""
echo "================================================"
echo "STARTUP CHECK COMPLETE"
echo ""
echo "Quick commands:"
echo "  Watch logs:  docker logs -f hfss_live_web_1"
echo "  Restart:     docker-compose restart"
echo "  Rebuild:     docker-compose up -d --build"
echo "================================================"