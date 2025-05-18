#!/bin/bash
# Configuration

PG_HOST="localhost"         # Database host
PG_PORT="5432"                      # Database port
PG_PASSWORD="ujqajEoqzJGnw0YRG2kA" # Password for postgres user
PG_VERSION="14" # Added: PostgreSQL version.  Crucial for config path.

BACKUP_PATH="/home/ubuntu/db_backup/postgres"
DATE=$(date +%Y-%m-%d)
ARCHIVE_NAME="postgres-full-backup-$DATE.tar.gz"
DROPBOX_PATH="HF/backups/postgres"
LOG_FILE="$BACKUP_PATH/backup.log"
RETENTION_DAYS=5

# Function to log messages
log_message() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

# Create backup directory with proper permissions
mkdir -p "$BACKUP_PATH"
TEMP_BACKUP_DIR="$BACKUP_PATH/temp_backup_$DATE"

# Remove temp directory if it exists and create a new one with proper permissions
if [ -d "$TEMP_BACKUP_DIR" ]; then
    rm -rf "$TEMP_BACKUP_DIR"
fi

# Create temp directory and ensure postgres user can write to it
mkdir -p "$TEMP_BACKUP_DIR"
sudo chmod 700 "$TEMP_BACKUP_DIR"
sudo chown postgres:postgres "$TEMP_BACKUP_DIR"

# Start backup process
log_message "Starting full PostgreSQL instance backup"

# Set password environment variable for postgres
export PGPASSWORD="$PG_PASSWORD"

# Perform physical backup using pg_basebackup
if sudo -u postgres bash -c "export PGPASSWORD='$PG_PASSWORD'; pg_basebackup -h $PG_HOST -p $PG_PORT -D $TEMP_BACKUP_DIR -Ft -z -P"; then
    log_message "Successfully created full PostgreSQL backup"

    # Ensure proper ownership for further processing
    sudo chown -R $(whoami):$(whoami) "$TEMP_BACKUP_DIR"

    # Create final archive
    tar -czf "$BACKUP_PATH/$ARCHIVE_NAME" -C "$TEMP_BACKUP_DIR" .
    log_message "Created archive: $ARCHIVE_NAME"

    # Clean up temporary directory
    rm -rf "$TEMP_BACKUP_DIR"
else
    log_message "ERROR: Failed to create PostgreSQL backup"
    rm -rf "$TEMP_BACKUP_DIR"
    exit 1
fi

# Unset the password environment variable
unset PGPASSWORD

# Calculate backup size
BACKUP_SIZE=$(du -sh "$BACKUP_PATH/$ARCHIVE_NAME" | cut -f1)
log_message "Backup size: $BACKUP_SIZE"

# Backup Configuration Files
log_message "Backing up PostgreSQL configuration files..."
CONFIG_BACKUP_DIR="$BACKUP_PATH/config" #create a config dir
mkdir -p "$CONFIG_BACKUP_DIR" #make the dir
#copy the files
if sudo cp "/etc/postgresql/$PG_VERSION/main/postgresql.conf" "$CONFIG_BACKUP_DIR/postgresql.conf" && \
   sudo cp "/etc/postgresql/$PG_VERSION/main/pg_hba.conf"     "$CONFIG_BACKUP_DIR/pg_hba.conf"     && \
   sudo cp "/etc/postgresql/$PG_VERSION/main/pg_ident.conf"   "$CONFIG_BACKUP_DIR/pg_ident.conf"; then
    log_message "Successfully backed up configuration files."
else
    log_message "WARNING: Failed to backup configuration files.  Backup may be incomplete."
fi


# Upload to Dropbox
log_message "Uploading backup to Dropbox..."
if rclone copy "$BACKUP_PATH/$ARCHIVE_NAME" "dropbox:${DROPBOX_PATH}" --progress --stats 1m --transfers 4; then
    log_message "Successfully uploaded backup to Dropbox"
else
    log_message "ERROR: Failed to upload backup to Dropbox"
    exit 1
fi

# Clean up old local backups
log_message "Cleaning up old local backups..."
find "$BACKUP_PATH" -name "postgres-full-backup-*.tar.gz" -mtime +$RETENTION_DAYS -exec rm -f {} \;

# Clean up old Dropbox backups
log_message "Cleaning up old Dropbox backups..."
rclone ls "dropbox:${DROPBOX_PATH}" | grep "postgres-full-backup-" | sort | head -n -$RETENTION_DAYS | while read -r size name; do
    if rclone delete "dropbox:${DROPBOX_PATH}/${name}"; then
        log_message "Deleted old Dropbox backup: ${name}"
    else
        log_message "WARNING: Failed to delete old Dropbox backup: ${name}"
    fi
done

log_message "Backup process completed successfully"
