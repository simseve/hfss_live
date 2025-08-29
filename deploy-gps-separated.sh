#!/bin/bash
# Deployment script for separated GPS TCP Server architecture

echo "Deploying HFSS Live with separated GPS TCP Server..."

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if .env file exists
if [ ! -f .env ]; then
    echo -e "${RED}Error: .env file not found${NC}"
    echo "Please create a .env file with required configuration"
    exit 1
fi

# Load environment variables
export $(cat .env | grep -v '^#' | xargs)

echo -e "${YELLOW}Configuration:${NC}"
echo "  GPS TCP Port: ${GPS_TCP_PORT:-9999}"
echo "  GPS TCP Enabled: ${GPS_TCP_ENABLED:-true}"
echo ""

# Function to check if network exists
check_network() {
    docker network inspect app-network >/dev/null 2>&1
    return $?
}

# Create network if it doesn't exist
if ! check_network; then
    echo -e "${YELLOW}Creating app-network...${NC}"
    docker network create app-network
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}Network created successfully${NC}"
    else
        echo -e "${RED}Failed to create network${NC}"
        exit 1
    fi
else
    echo -e "${GREEN}Network app-network already exists${NC}"
fi

# Build images
echo -e "${YELLOW}Building Docker images...${NC}"

# Build GPS TCP Server image
echo "Building GPS TCP Server image..."
docker build -f tcp_server/Dockerfile -t gps-tcp-server:latest .
if [ $? -ne 0 ]; then
    echo -e "${RED}Failed to build GPS TCP Server image${NC}"
    exit 1
fi

# Build main FastAPI image
echo "Building FastAPI application image..."
docker build -f Dockerfile -t hfsslive:latest .
if [ $? -ne 0 ]; then
    echo -e "${RED}Failed to build FastAPI image${NC}"
    exit 1
fi

echo -e "${GREEN}Images built successfully${NC}"

# Stop existing containers
echo -e "${YELLOW}Stopping existing containers...${NC}"
docker-compose -f docker-compose-gps.yml down

# Start services
echo -e "${YELLOW}Starting services...${NC}"
docker-compose -f docker-compose-gps.yml up -d

if [ $? -eq 0 ]; then
    echo -e "${GREEN}Services started successfully${NC}"
    echo ""
    echo "Services running:"
    docker-compose -f docker-compose-gps.yml ps
    
    echo ""
    echo -e "${GREEN}Deployment complete!${NC}"
    echo ""
    echo "Access points:"
    echo "  - FastAPI: http://localhost:5012"
    echo "  - GPS TCP Server: port ${GPS_TCP_PORT:-9999}"
    echo "  - Health check: http://localhost:5012/health"
    echo "  - GPS TCP status: http://localhost:5012/api/gps-tcp/external/status"
    echo ""
    echo "View logs:"
    echo "  - All services: docker-compose -f docker-compose-gps.yml logs -f"
    echo "  - GPS TCP only: docker-compose -f docker-compose-gps.yml logs -f gps-tcp-server"
    echo "  - FastAPI only: docker-compose -f docker-compose-gps.yml logs -f hfsslive"
else
    echo -e "${RED}Failed to start services${NC}"
    exit 1
fi