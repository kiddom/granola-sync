---
name: sync-granola
description: Archive Granola meeting notes and transcripts to Google Drive. Use when the user asks to sync, archive, or download Granola notes, or when the sync job appears to have stopped working.
---

Run the Granola sync script to archive meeting notes to Google Drive.

The script is at: ${CLAUDE_SKILL_DIR}/../../../sync-granola.py

Steps:
1. Run the script with the default 2-day lookback:
   `python3 /PATH/TO/sync-granola.py`
   Replace /PATH/TO with the actual repo path.

2. If the user wants to backfill a specific date range, run with a patched LOOKBACK_DAYS:
   ```
   python3 -c "
   code = open('/PATH/TO/sync-granola.py').read()
   code = code.replace('LOOKBACK_DAYS = 2', 'LOOKBACK_DAYS = N')
   exec(code)
   "
   ```
   Where N covers the number of days back needed.

3. If the script fails with a FileNotFoundError on the cache file:
   - Check ~/Library/Application Support/Granola/ for the latest cache-v*.json
   - The script auto-detects the version — if it still fails, the Granola app may not be installed or the cache hasn't been written yet (open Granola and wait a moment)

4. Report how many meetings were synced and which date folders were written to.

Archive destination is configured in the script (ARCHIVE_DIR). Default is Google Drive under Granola Notes/YYYY-MM-DD/.
