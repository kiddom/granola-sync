#!/bin/bash

LOG_FILE="/Users/stephaniebutler/.claude/scripts/granola-sync.log"

echo "$(date '+%Y-%m-%d %H:%M:%S') Starting Granola sync..." >> "$LOG_FILE"

python3 /Users/stephaniebutler/.claude/scripts/sync-granola.py >> "$LOG_FILE" 2>&1
EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') ERROR: script exited with code $EXIT_CODE" >> "$LOG_FILE"
fi

echo "$(date '+%Y-%m-%d %H:%M:%S') Sync complete (exit $EXIT_CODE)." >> "$LOG_FILE"
