#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="$SCRIPT_DIR/granola-sync.log"

echo "$(date '+%Y-%m-%d %H:%M:%S') Starting Granola sync..." >> "$LOG_FILE"
python3 "$SCRIPT_DIR/sync-granola.py" >> "$LOG_FILE" 2>&1
echo "$(date '+%Y-%m-%d %H:%M:%S') Sync complete." >> "$LOG_FILE"
