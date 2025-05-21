#!/bin/bash

# PostgreSQL Restoration Script for pg_basebackup with -Ft format

# Configuration variables
# Remote server details
REMOTE_USER="ubuntu"
REMOTE_HOST="vilnius"
REMOTE_BACKUP_PATH="/home/ubuntu/db_backup/postgres"

DATA_DIR="/var/lib/postgresql/14/main"
TEMP_EXTRACT_DIR="/tmp/pg_restore_temp"
PG_USER="postgres"
PG_GROUP="postgres"
PG_VERSION="14" # PostgreSQL version for config file restore

# Output colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to output status
echo_status() {
  echo -e "${YELLOW}[$(date '+%Y-%m-%d %H:%M:%S')]${NC} $1"
}

# Check if running as root
if [ "$(id -u)" -ne 0 ]; then
  echo -e "${RED}Error: This script must be run as root${NC}"
  exit 1
fi

# 1. Stop the PostgreSQL Server
echo_status "Stopping PostgreSQL server..."
systemctl stop postgresql
if [ $? -ne 0 ]; then
  echo -e "${RED}Failed to stop PostgreSQL server. Exiting.${NC}"
  exit 1
fi
echo_status "PostgreSQL server stopped successfully."

# 2. Create a temporary directory for extraction
echo_status "Creating temporary extraction directory..."
mkdir -p "$TEMP_EXTRACT_DIR"
chown "$PG_USER:$PG_GROUP" "$TEMP_EXTRACT_DIR"

# 3. Fetch the backup from the remote server
echo_status "Fetching backup from remote server ${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_BACKUP_PATH}..."

# List available backups on the remote server
remote_files=$(ssh ${REMOTE_USER}@${REMOTE_HOST} "ls -t ${REMOTE_BACKUP_PATH}/postgres-full-backup-*.tar.gz")
if [ -z "$remote_files" ]; then
    echo -e "${RED}No backups found on the remote server. Exiting.${NC}"
    exit 1
fi

# Display available backups and prompt for selection
echo -e "${YELLOW}Available backups on remote server:${NC}"
i=1
options=()
while IFS= read -r file; do
    filename=$(basename "$file")
    echo "  $i) $filename"
    options+=("$filename")
    i=$((i+1))
done <<< "$remote_files"

read -p "Enter the number of the backup to restore: " selected_number
if ! [[ "$selected_number" =~ ^[0-9]+$ ]]; then
    echo -e "${RED}Invalid input. Exiting.${NC}"
    exit 1
fi

if [ "$selected_number" -gt $(( ${#options[@]} )) ]; then
    echo -e "${RED}Invalid backup number. Exiting.${NC}"
    exit 1
fi
SELECTED_FILE="${options[$((selected_number-1))]}"
BACKUP_FILE="${TEMP_EXTRACT_DIR}/${SELECTED_FILE}" #local path

echo_status "Selected backup: $SELECTED_FILE"
echo_status "Copying $SELECTED_FILE from remote server..."
scp ${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_BACKUP_PATH}/"$SELECTED_FILE" "$BACKUP_FILE"
if [ $? -ne 0 ]; then
  echo -e "${RED}Failed to copy backup from remote server. Exiting.${NC}"
  exit 1
fi
echo_status "Backup copied successfully."

# 4. Prepare the data directory
echo_status "Preparing data directory..."
OLD_DATA_DIR="${DATA_DIR}_old"

if [ -d "$OLD_DATA_DIR" ]; then
  echo_status "Old data directory found: $OLD_DATA_DIR. Removing it..."
  rm -rf "$OLD_DATA_DIR"
  if [ $? -ne 0 ]; then
    echo -e "${RED}Failed to remove old data directory. Exiting.${NC}"
    exit 1
  fi
fi

if [ -d "$DATA_DIR" ]; then
  echo_status "Backing up existing data directory to $OLD_DATA_DIR"
  mv "$DATA_DIR" "$OLD_DATA_DIR"
fi

echo_status "Creating new data directory..."
mkdir -p "$DATA_DIR"
chown "$PG_USER:$PG_GROUP" "$DATA_DIR"
chmod 700 "$DATA_DIR"

# 5. Extract the backup directly to the data directory
echo_status "Extracting backup archive to data directory..."
tar -xzf "$BACKUP_FILE" -C "$DATA_DIR"
if [ $? -ne 0 ]; then
  echo -e "${RED}Failed to extract the backup archive to data directory. Exiting.${NC}"
  exit 1
fi

# 5a. Extract nested tar.gz files found in the data directory
echo_status "Processing nested tar.gz files in data directory..."
for tarfile in "$DATA_DIR"/*.tar.gz; do
  if [ -f "$tarfile" ]; then
    filename=$(basename "$tarfile")
    echo_status "Extracting nested archive: $filename"
    
    # Create a temp directory for extraction
    extract_temp="$DATA_DIR/extract_temp_$"
    mkdir -p "$extract_temp"
    
    # Extract to temp directory
    tar -xzf "$tarfile" -C "$extract_temp"
    
    if [ $? -ne 0 ]; then
      echo -e "${RED}Failed to extract nested archive: $filename. Continuing...${NC}"
    else
      # Move files to appropriate location
      if [[ "$filename" == "base.tar.gz" ]]; then
        echo_status "Moving base files to data directory..."
        cp -a "$extract_temp"/* "$DATA_DIR/"
      elif [[ "$filename" == "pg_wal.tar.gz" ]]; then
        echo_status "Moving WAL files to pg_wal directory..."
        mkdir -p "$DATA_DIR/pg_wal"
        cp -a "$extract_temp"/* "$DATA_DIR/pg_wal/"
      else
        echo_status "Moving files from $filename to data directory..."
        cp -a "$extract_temp"/* "$DATA_DIR/"
      fi
      
      # Remove the temp directory
      rm -rf "$extract_temp"
      
      # Remove the processed tar.gz file
      rm -f "$tarfile"
    fi
  fi
done

echo_status "All nested archives processed."

# 6. Handle TimescaleDB if present
echo_status "Checking for TimescaleDB configuration..."
if grep -q "timescaledb" "$DATA_DIR/postgresql.auto.conf" || grep -q "timescaledb" "$OLD_DATA_DIR/postgresql.conf" 2>/dev/null; then
  echo_status "TimescaleDB configuration found. Checking if it's installed on this server..."
  
  # Try to find any version of timescaledb library
  TIMESCALEDB_LIB=$(find /usr/lib/postgresql -name "timescaledb*.so" | head -n 1)
  
  if [ -z "$TIMESCALEDB_LIB" ]; then
    echo_status "TimescaleDB not installed. Temporarily disabling TimescaleDB in configuration..."
    
    # Modify postgresql.auto.conf if it exists
    if [ -f "$DATA_DIR/postgresql.auto.conf" ]; then
      sed -i "s/shared_preload_libraries\s*=\s*['\"].*timescaledb.*['\"]/shared_preload_libraries = ''/" "$DATA_DIR/postgresql.auto.conf"
    fi
    
    # Modify postgresql.conf if it exists
    if [ -f "$DATA_DIR/postgresql.conf" ]; then
      sed -i "s/shared_preload_libraries\s*=\s*['\"].*timescaledb.*['\"]/shared_preload_libraries = ''/" "$DATA_DIR/postgresql.conf"
    fi
    
    echo_status "TimescaleDB disabled in configuration. You may need to install it later: sudo apt install postgresql-14-timescaledb"
  else
    echo_status "TimescaleDB is installed: $TIMESCALEDB_LIB"
  fi
fi

# 7. Handle recovery if backup_label exists
echo_status "Checking for backup_label file..."
if [ -f "$DATA_DIR/backup_label" ]; then
  echo_status "Found backup_label file. This is a pg_basebackup backup taken during operation."
  echo_status "Removing backup_label to enable direct startup..."
  rm -f "$DATA_DIR/backup_label"
fi

# 8. Ensure correct permissions
echo_status "Setting correct permissions..."
chown -R "$PG_USER:$PG_GROUP" "$DATA_DIR"
chmod 700 "$DATA_DIR"

# 9. Remove postmaster.pid if present
echo_status "Removing postmaster.pid if present..."
rm -f "$DATA_DIR/postmaster.pid"

# 10. Start PostgreSQL Server
echo_status "Starting PostgreSQL server..."
systemctl start postgresql
if [ $? -ne 0 ]; then
  echo -e "${RED}Failed to start PostgreSQL server. Check logs for details.${NC}"
  echo -e "${YELLOW}Looking at PostgreSQL logs for clues...${NC}"
  sudo -u "$PG_USER" tail -n 50 /var/log/postgresql/postgresql-14-main.log
  
  echo_status "Trying minimal configuration approach..."
  # Create a minimal configuration
  cat > "$DATA_DIR/postgresql.conf" << EOF
# Minimal configuration for recovery
listen_addresses = 'localhost'
port = 5432
unix_socket_directories = '/var/run/postgresql'
shared_preload_libraries = ''
EOF
  chown "$PG_USER:$PG_GROUP" "$DATA_DIR/postgresql.conf"
  
  # Start PostgreSQL with this minimal configuration
  systemctl start postgresql
  if [ $? -ne 0 ]; then
    echo -e "${RED}All recovery attempts failed. Manual intervention required.${NC}"
    echo -e "${YELLOW}Suggestions:${NC}"
    echo -e "${YELLOW}1. Check PostgreSQL logs: sudo -u postgres tail -n 50 /var/log/postgresql/postgresql-14-main.log${NC}"
    echo -e "${YELLOW}2. Install TimescaleDB if needed: sudo apt install postgresql-14-timescaledb${NC}"
    echo -e "${YELLOW}3. Consider using pg_dump/pg_restore instead of file-level backup${NC}"
    exit 1
  else
    echo_status "PostgreSQL started with minimal configuration!"
  fi
else
  echo_status "PostgreSQL server started successfully."
fi

# 11. Verify Restoration
echo_status "Verifying restoration..."
sleep 5 # Give PostgreSQL a moment to start up
su - "$PG_USER" -c "psql -d postgres -c \"SELECT 'Restoration successful!' AS status;\""

if [ $? -eq 0 ]; then
  echo -e "${GREEN}PostgreSQL restoration completed successfully!${NC}"
  echo_status "To list all databases, run: sudo -u $PG_USER psql -c '\\l'"
else
  echo -e "${RED}Verification failed. Please check PostgreSQL logs.${NC}"
  echo -e "${YELLOW}Check logs with: sudo -u postgres tail -n 50 /var/log/postgresql/postgresql-14-main.log${NC}"
fi

# 12. Clean up
echo_status "Cleaning up temporary files..."
rm -rf "$TEMP_EXTRACT_DIR"

echo_status "Restoration process completed."