#!/bin/bash
set -e

REPO="https://raw.githubusercontent.com/kiddom/granola-sync/main"
INSTALL_DIR="$HOME/granola-sync"

echo ""
echo "Granola Sync Setup"
echo "------------------"

# --- Email ---
read -rp "What's your Google email? (e.g. you@example.com): " USER_EMAIL
if [[ -z "$USER_EMAIL" ]]; then
  echo "Email is required. Exiting."
  exit 1
fi

# --- Google Drive path ---
DRIVE_DESKTOP="$HOME/Library/CloudStorage/GoogleDrive-${USER_EMAIL}/My Drive/Granola Notes"
if [[ -d "$HOME/Library/CloudStorage/GoogleDrive-${USER_EMAIL}" ]]; then
  ARCHIVE_DIR="$DRIVE_DESKTOP"
  echo "Found Google Drive for Desktop — notes will sync to: $ARCHIVE_DIR"
else
  echo ""
  echo "Google Drive for Desktop not detected."
  echo "You can still save notes locally and upload manually, or enter a custom folder path."
  DEFAULT_LOCAL="$HOME/Documents/Granola Notes"
  read -rp "Where should notes be saved? [${DEFAULT_LOCAL}]: " CUSTOM_DIR
  ARCHIVE_DIR="${CUSTOM_DIR:-$DEFAULT_LOCAL}"
fi

# --- Install ---
echo ""
echo "Installing to $INSTALL_DIR..."
mkdir -p "$INSTALL_DIR"

curl -fsSL "$REPO/sync-granola.py" -o "$INSTALL_DIR/sync-granola.py"
curl -fsSL "$REPO/sync-granola.sh" -o "$INSTALL_DIR/sync-granola.sh"
chmod +x "$INSTALL_DIR/sync-granola.sh"

# Set GRANOLA_ARCHIVE_DIR in the shell wrapper
sed -i '' "1a\\
export GRANOLA_ARCHIVE_DIR=\"$ARCHIVE_DIR\"
" "$INSTALL_DIR/sync-granola.sh"

# --- launchd ---
PLIST_LABEL="com.$(whoami).granola-sync"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_LABEL}.plist"

cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${PLIST_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>${INSTALL_DIR}/sync-granola.sh</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>17</integer>
        <key>Minute</key>
        <integer>5</integer>
    </dict>
</dict>
</plist>
EOF

launchctl load "$PLIST_PATH"

# --- First run ---
echo ""
echo "Running first sync..."
python3 "$INSTALL_DIR/sync-granola.py"

echo ""
echo "All done. Granola notes will archive to:"
echo "  $ARCHIVE_DIR"
echo "The sync runs automatically every day at 5:05pm."
echo ""
echo "To run manually at any time:"
echo "  python3 $INSTALL_DIR/sync-granola.py"
