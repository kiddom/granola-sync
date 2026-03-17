# granola-sync

Archives Granola meeting notes and transcripts to Google Drive nightly. Includes a Claude Code skill for manual runs and backfills.

## What it does

- Reads from the local Granola cache (`~/Library/Application Support/Granola/cache-v*.json`)
- Converts notes (Prosemirror JSON) and transcripts to markdown
- Writes one folder per day to Google Drive: `Granola Notes/YYYY-MM-DD/`
- Auto-detects the current Granola cache version — no manual updates needed when Granola upgrades

## Requirements

- macOS
- [Granola](https://granola.so) installed and signed in
- Python 3
- Google Drive for Desktop mounted at `~/Library/CloudStorage/GoogleDrive-YOUR_EMAIL/`

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/YOUR_ORG/granola-sync.git ~/granola-sync
```

### 2. Update the archive destination

Open `sync-granola.py` and update `ARCHIVE_DIR` to your own Google Drive path:

```python
ARCHIVE_DIR = Path("/Users/YOUR_USERNAME/Library/CloudStorage/GoogleDrive-YOUR_EMAIL@kiddom.co/My Drive/Granola Notes")
```

### 3. Make the shell script executable

```bash
chmod +x ~/granola-sync/sync-granola.sh
```

### 4. Set up the nightly launchd job (runs at 5:05pm)

```bash
cp ~/granola-sync/com.granola-sync.plist.template \
   ~/Library/LaunchAgents/com.YOUR_USERNAME.granola-sync.plist
```

Edit the plist and replace both placeholders (`YOUR_USERNAME` and `/PATH/TO/granola-sync`) with your actual values, then load it:

```bash
launchctl load ~/Library/LaunchAgents/com.YOUR_USERNAME.granola-sync.plist
```

### 5. Install the Claude Code skill (optional)

If you use Claude Code, the `/sync-granola` skill is included. It lets you trigger syncs and backfills conversationally. It will be available automatically when you open Claude Code from the `~/granola-sync` directory.

## Manual run

```bash
python3 ~/granola-sync/sync-granola.py
```

Logs are written to `granola-sync.log` in the repo directory when run via the shell wrapper.

## Backfilling missed days

Run directly with a patched lookback. For example, to backfill the last 7 days:

```bash
python3 -c "
code = open('$HOME/granola-sync/sync-granola.py').read()
code = code.replace('LOOKBACK_DAYS = 2', 'LOOKBACK_DAYS = 7')
exec(code)
"
```
