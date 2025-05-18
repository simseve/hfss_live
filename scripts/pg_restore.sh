#!/bin/bash

# PostgreSQL Restoration Script with Remote Fetch

# Configuration variables
# Remote server details
REMOTE_USER="ubuntu"
REMOTE_HOST="vilnius"
REMOTE_BACKUP_PATH="/home/ubuntu/db_backup/postgres"

DATA_DIR="/var/lib/postgresql/14/main"
TEMP_EXTRACT_DIR="/tmp/pg_restore_temp"
PG_USER="postgres"
PG_GROUP="postgres"
PG_VERSION="14" # Added: PostgreSQL version for config file restore

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



# 4. Extract the backup to the temporary directory
echo_status "Extracting backup archive to temporary directory..."
tar -xzf "$BACKUP_FILE" -C "$TEMP_EXTRACT_DIR"
if [ $? -ne 0 ]; then
  echo -e "${RED}Failed to extract the backup archive. Exiting.${NC}"
  exit 1
fi

# 5. Prepare the data directory
echo_status "Preparing data directory..."
if [ -d "$DATA_DIR" ]; then
  echo_status "Backing up existing data directory to ${DATA_DIR}_old"
  mv "$DATA_DIR" "${DATA_DIR}_old"
fi

echo_status "Creating new data directory..."
mkdir -p "$DATA_DIR"
chown "$PG_USER:$PG_GROUP" "$DATA_DIR"
chmod 700 "$DATA_DIR"

# 6. Copy the extracted backup to the data directory
echo_status "Copying extracted backup to data directory..."
cp -r "$TEMP_EXTRACT_DIR"/* "$DATA_DIR"/

# 7. Restore Configuration Files
echo_status "Restoring configuration files..."
CONFIG_SOURCE_DIR="${TEMP_EXTRACT_DIR}/config" # Config files are in a 'config' subdir

if [ -d "$CONFIG_SOURCE_DIR" ]; then
  echo_status "Configuration backup found. Restoring..."
  cp "$CONFIG_SOURCE_DIR/postgresql.conf" "/etc/postgresql/$PG_VERSION/main/postgresql.conf"
  cp "$CONFIG_SOURCE_DIR/pg_hba.conf"     "/etc/postgresql/$PG_VERSION/main/pg_hba.conf"
  cp "$CONFIG_SOURCE_DIR/pg_ident.conf"   "/etc/postgresql/$PG_VERSION/main/pg_ident.conf"
  if [ $? -ne 0 ]; then
     echo -e "${RED}Failed to restore configuration files.  Restoration may be incomplete.${NC}"
  fi
else
  echo_status "Configuration backup not found. Using default configuration."
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
  echo -e "${YELLOW}Possible solution: Look at PostgreSQL logs with: sudo -u postgres tail -n 50 /var/log/postgresql/postgresql-14-main.log${NC}"
  exit 1
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

# End of script
# Note: Ensure that the PostgreSQL service is enabled to start on boot