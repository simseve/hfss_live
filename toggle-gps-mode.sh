#!/bin/bash
# Script to toggle between embedded and separated GPS TCP server modes

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to display usage
usage() {
    echo -e "${BLUE}GPS TCP Server Mode Toggle Script${NC}"
    echo ""
    echo "Usage: $0 [embedded|separated|status]"
    echo ""
    echo "Modes:"
    echo "  embedded   - Run GPS TCP server inside FastAPI container (default)"
    echo "  separated  - Run GPS TCP server as separate Docker service"
    echo "  status     - Show current configuration"
    echo ""
    echo "Examples:"
    echo "  $0 embedded    # Switch to embedded mode"
    echo "  $0 separated   # Switch to separated mode"
    echo "  $0 status      # Check current mode"
    exit 1
}

# Function to check current mode
check_status() {
    echo -e "${BLUE}Checking GPS TCP Server Configuration...${NC}"
    echo ""
    
    # Check .env file
    if [ -f .env ]; then
        GPS_ENABLED=$(grep "^GPS_TCP_ENABLED=" .env | cut -d'=' -f2)
        GPS_PORT=$(grep "^GPS_TCP_PORT=" .env | cut -d'=' -f2)
        
        echo -e "Environment Configuration:"
        echo -e "  GPS_TCP_ENABLED: ${YELLOW}${GPS_ENABLED:-not set}${NC}"
        echo -e "  GPS_TCP_PORT: ${YELLOW}${GPS_PORT:-not set}${NC}"
    else
        echo -e "${RED}.env file not found${NC}"
    fi
    
    echo ""
    
    # Check which docker-compose file is being used
    if [ "$1" == "dev" ]; then
        COMPOSE_FILE="docker-compose-dev.yml"
    else
        COMPOSE_FILE="docker-compose.yml"
    fi
    
    # Check if GPS service is uncommented
    if grep -q "^  gps-tcp-server:" "$COMPOSE_FILE" 2>/dev/null; then
        echo -e "Docker Compose: ${GREEN}Separated mode ACTIVE${NC} in $COMPOSE_FILE"
        echo -e "  GPS TCP server configured as separate service"
    else
        echo -e "Docker Compose: ${YELLOW}Embedded mode${NC} in $COMPOSE_FILE"
        echo -e "  GPS TCP server runs inside FastAPI container"
    fi
    
    echo ""
    
    # Check running containers
    echo "Running Containers:"
    if docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | grep -E "(hfsslive|gps-tcp-server)"; then
        echo ""
    else
        echo -e "${YELLOW}No relevant containers running${NC}"
    fi
}

# Function to enable embedded mode
enable_embedded() {
    echo -e "${BLUE}Switching to EMBEDDED mode...${NC}"
    
    # Check which compose file to use
    if [ "$1" == "dev" ]; then
        COMPOSE_FILE="docker-compose-dev.yml"
    else
        COMPOSE_FILE="docker-compose.yml"
    fi
    
    # Update .env to enable GPS TCP in FastAPI
    if [ -f .env ]; then
        # Backup .env
        cp .env .env.backup
        
        # Update GPS_TCP_ENABLED to true
        if grep -q "^GPS_TCP_ENABLED=" .env; then
            sed -i.tmp 's/^GPS_TCP_ENABLED=.*/GPS_TCP_ENABLED=true/' .env
        else
            echo "GPS_TCP_ENABLED=true" >> .env
        fi
        rm -f .env.tmp
        
        echo -e "${GREEN}✓ Updated .env: GPS_TCP_ENABLED=true${NC}"
    else
        echo -e "${RED}Error: .env file not found${NC}"
        exit 1
    fi
    
    # Comment out gps-tcp-server service in docker-compose
    echo -e "Updating $COMPOSE_FILE..."
    
    # Use sed to comment out the GPS service if it's uncommented
    sed -i.backup '/^  gps-tcp-server:/,/^  [^ ]/ {
        /^  gps-tcp-server:/s/^  /  # /
        /^    /s/^    /  #   /
    }' "$COMPOSE_FILE"
    
    # Also comment out the gps-logs volume
    sed -i.backup 's/^  gps-logs:/  # gps-logs:/' "$COMPOSE_FILE"
    
    echo -e "${GREEN}✓ GPS TCP server service commented out in $COMPOSE_FILE${NC}"
    echo -e "${GREEN}✓ Embedded mode configured${NC}"
    echo ""
    echo -e "${YELLOW}Next steps:${NC}"
    echo "  1. Rebuild and restart services:"
    echo "     docker-compose -f $COMPOSE_FILE down"
    echo "     docker-compose -f $COMPOSE_FILE up -d --build"
}

# Function to enable separated mode
enable_separated() {
    echo -e "${BLUE}Switching to SEPARATED mode...${NC}"
    
    # Check which compose file to use
    if [ "$1" == "dev" ]; then
        COMPOSE_FILE="docker-compose-dev.yml"
    else
        COMPOSE_FILE="docker-compose.yml"
    fi
    
    # Update .env to disable GPS TCP in FastAPI
    if [ -f .env ]; then
        # Backup .env
        cp .env .env.backup
        
        # Update GPS_TCP_ENABLED to false
        if grep -q "^GPS_TCP_ENABLED=" .env; then
            sed -i.tmp 's/^GPS_TCP_ENABLED=.*/GPS_TCP_ENABLED=false/' .env
        else
            echo "GPS_TCP_ENABLED=false" >> .env
        fi
        rm -f .env.tmp
        
        echo -e "${GREEN}✓ Updated .env: GPS_TCP_ENABLED=false${NC}"
    else
        echo -e "${RED}Error: .env file not found${NC}"
        exit 1
    fi
    
    # Uncomment gps-tcp-server service in docker-compose
    echo -e "Updating $COMPOSE_FILE..."
    
    # Use sed to uncomment the GPS service
    sed -i.backup '/^  # gps-tcp-server:/,/^  # [^ ]/ {
        s/^  # gps-tcp-server:/  gps-tcp-server:/
        s/^  #   /    /
    }' "$COMPOSE_FILE"
    
    # Also uncomment the gps-logs volume
    sed -i.backup 's/^  # gps-logs:/  gps-logs:/' "$COMPOSE_FILE"
    
    echo -e "${GREEN}✓ GPS TCP server service uncommented in $COMPOSE_FILE${NC}"
    echo -e "${GREEN}✓ Separated mode configured${NC}"
    echo ""
    echo -e "${YELLOW}Next steps:${NC}"
    echo "  1. Build GPS TCP server image:"
    echo "     docker build -f tcp_server/Dockerfile -t gps-tcp-server:latest ."
    echo "  2. Restart services:"
    echo "     docker-compose -f $COMPOSE_FILE down"
    echo "     docker-compose -f $COMPOSE_FILE up -d --build"
}

# Main script logic
case "$1" in
    embedded)
        enable_embedded "$2"
        ;;
    separated)
        enable_separated "$2"
        ;;
    status)
        check_status "$2"
        ;;
    *)
        usage
        ;;
esac