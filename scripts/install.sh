#!/usr/bin/env bash
set -euo pipefail

# KeepItGoing Installer
# One command: copies scripts, builds signed app, installs CLI, sets up login item.
#
# Usage:
#   ./scripts/install.sh              # Full install
#   ./scripts/install.sh --no-sign    # Skip code signing
#   ./scripts/install.sh --prefix DIR # Custom install root

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

PREFIX="${HOME}/.claude"
BIN_DIR="${HOME}/bin"
APP_NAME="KeepItGoing-ClaudeChat"
NO_SIGN=""

while [[ $# -gt 0 ]]; do
  case $1 in
    --prefix) PREFIX="$2"; shift 2 ;;
    --no-sign) NO_SIGN="--no-sign"; shift ;;
    --help|-h)
      echo "Usage: $0 [OPTIONS]"
      echo "  --prefix DIR   Install root (default: ~/.claude)"
      echo "  --no-sign      Skip code signing"
      exit 0
      ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

HOOKS_DIR="${PREFIX}/hooks/scripts"
STATE_DIR="${PREFIX}/hooks/state"

echo ""
echo "  ╔══════════════════════════════════════╗"
echo "  ║     KeepItGoing — Installer          ║"
echo "  ╚══════════════════════════════════════╝"
echo ""
echo "  Prefix:  ${PREFIX}"
echo "  Scripts: ${HOOKS_DIR}"
echo "  CLI:     ${BIN_DIR}/kig"
echo ""

# 1. Create directories
mkdir -p "${HOOKS_DIR}" "${STATE_DIR}" "${BIN_DIR}" /tmp/claude-keepitgoing

# 2. Install Python scripts
echo "[1/5] Installing Python scripts..."
cp "${REPO_ROOT}/src/keepitgoing-generate.py" "${HOOKS_DIR}/keepitgoing-generate.py"
cp "${REPO_ROOT}/src/keepitgoing-state.py" "${HOOKS_DIR}/keepitgoing-state.py"
chmod +x "${HOOKS_DIR}/keepitgoing-generate.py" "${HOOKS_DIR}/keepitgoing-state.py"

# 3. Install kig CLI
echo "[2/5] Installing kig CLI..."
cp "${REPO_ROOT}/bin/kig" "${BIN_DIR}/kig"
chmod +x "${BIN_DIR}/kig"

# 4. Build signed app
echo "[3/5] Building macOS app..."
GENERATOR_PATH="${HOOKS_DIR}/keepitgoing-generate.py"
"${REPO_ROOT}/scripts/build.sh" --generator-path "${GENERATOR_PATH}" ${NO_SIGN}

# 5. Install user directives config (if not already present)
DIRECTIVES_PATH="${HOME}/.claude/keepitgoing-directives.json"
if [ ! -f "${DIRECTIVES_PATH}" ]; then
  echo "[4/5] Creating default directives config..."
  cp "${REPO_ROOT}/config/keepitgoing-directives.json.example" "${DIRECTIVES_PATH}"
else
  echo "[4/5] Directives config already exists, skipping."
fi

# 5.5 KIG modes: install Python runtime modules, seed libraries, run migration
KIG_HOME="${HOME}/.claude/kig"
KIG_SRC="${KIG_HOME}/_src"
mkdir -p "${KIG_HOME}/tabs" "${KIG_HOME}/legacy" "${KIG_SRC}/kig_seeds"

# Copy Python modules + seeds into a stable runtime location (bin/kig and
# main.applescript import from here, not from the repo).
cp "${REPO_ROOT}/src/kig_config.py"      "${KIG_SRC}/kig_config.py"
cp "${REPO_ROOT}/src/kig_scope.py"       "${KIG_SRC}/kig_scope.py"
cp "${REPO_ROOT}/src/kig_inject.py"      "${KIG_SRC}/kig_inject.py"
cp "${REPO_ROOT}/src/kig_modes.py"       "${KIG_SRC}/kig_modes.py"
cp "${REPO_ROOT}/src/kig_tab_state.py"   "${KIG_SRC}/kig_tab_state.py"
cp "${REPO_ROOT}/src/kig_migrate.py"     "${KIG_SRC}/kig_migrate.py"
cp "${REPO_ROOT}/src/kig_seeds/"*.json   "${KIG_SRC}/kig_seeds/"

# Legacy migration (idempotent — safe on every install)
python3 -c "
import sys
sys.path.insert(0, '${KIG_SRC}')
from pathlib import Path
from kig_migrate import migrate_legacy
migrate_legacy(claude_home=Path.home() / '.claude', kig_home=Path('${KIG_HOME}'))
"

# Delete old slash command (consolidated into /kig-inject)
rm -f "${HOME}/.claude/commands/kig-pin.md"

echo "      ✓ KIG modes runtime installed to ${KIG_SRC}"
echo "      ✓ Legacy files archived to ${KIG_HOME}/legacy/"

# Install CLI helpers for slash commands
cp "${REPO_ROOT}/bin/kig-inject-cmd.py"  "${BIN_DIR}/kig-inject-cmd.py"
cp "${REPO_ROOT}/bin/kig-library-cmd.py" "${BIN_DIR}/kig-library-cmd.py"
cp "${REPO_ROOT}/bin/kig-config-cmd.py"  "${BIN_DIR}/kig-config-cmd.py"
chmod +x "${BIN_DIR}/kig-inject-cmd.py" "${BIN_DIR}/kig-library-cmd.py" "${BIN_DIR}/kig-config-cmd.py"

# Install /kig-inject, /kig-library, /kig-config slash commands
CMD_DIR="${HOME}/.claude/commands"
mkdir -p "${CMD_DIR}"
cp "${REPO_ROOT}/config/kig-inject.md.tmpl"  "${CMD_DIR}/kig-inject.md"
cp "${REPO_ROOT}/config/kig-library.md.tmpl" "${CMD_DIR}/kig-library.md"
cp "${REPO_ROOT}/config/kig-config.md.tmpl"  "${CMD_DIR}/kig-config.md"
echo "      ✓ slash commands installed: /kig-inject, /kig-library, /kig-config"

# 6. Launch
echo "[5/5] Launching..."
APP_PATH="${REPO_ROOT}/dist/${APP_NAME}.app"
open "${APP_PATH}"

echo ""
echo "  ╔══════════════════════════════════════╗"
echo "  ║     Installation Complete            ║"
echo "  ╚══════════════════════════════════════╝"
echo ""
echo "  App:     ${APP_PATH}"
echo "  CLI:     kig on | kig off | kig status"
echo "  Logs:    /tmp/claude-keepitgoing/app.log"
echo "  Config:  ${DIRECTIVES_PATH}"
echo ""

# Check if ~/bin is in PATH
if ! echo "$PATH" | tr ':' '\n' | grep -q "^${BIN_DIR}$"; then
  echo "  NOTE: ${BIN_DIR} is not in your PATH."
  echo "  Add to ~/.zshrc:  export PATH=\"${BIN_DIR}:\$PATH\""
  echo ""
fi

# Offer to add as login item
echo "  To auto-start on login:"
echo "  osascript -e 'tell application \"System Events\" to make login item at end with properties {path:\"${APP_PATH}\", hidden:true}'"
echo ""
