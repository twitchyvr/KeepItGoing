#!/usr/bin/env bash
set -euo pipefail

# Uninstall KeepItGoing
# Removes installed files. Does NOT delete the repo or runtime state.

PREFIX="${HOME}/.claude"
BIN_DIR="${HOME}/bin"
APP_NAME="KeepItGoing-ClaudeChat"

echo "=== KeepItGoing Uninstaller ==="

# Stop the app
osascript -e "tell application \"${APP_NAME}\" to quit" 2>/dev/null || true

# Remove login item
osascript -e 'tell application "System Events" to delete login item "KeepItGoing-ClaudeChat"' 2>/dev/null || true

# Remove files (but don't touch the generator — other tools may use it)
echo "Removing kig CLI..."
rm -f "${BIN_DIR}/kig"

echo ""
echo "=== Uninstall complete ==="
echo ""
echo "Note: keepitgoing-generate.py and keepitgoing-state.py were NOT removed"
echo "from ${PREFIX}/hooks/scripts/ because Claude Code hooks may reference them."
echo "Remove manually if desired:"
echo "  rm ${PREFIX}/hooks/scripts/keepitgoing-generate.py"
echo "  rm ${PREFIX}/hooks/scripts/keepitgoing-state.py"
echo ""
echo "Runtime state in /tmp/claude-keepitgoing/ is ephemeral and will be"
echo "cleaned up automatically on reboot."
