#!/usr/bin/env bash
set -euo pipefail

# Build KeepItGoing macOS app from AppleScript source.
# Compiles, code-signs, and optionally notarizes.
#
# Usage:
#   ./scripts/build.sh                    # Build + sign
#   ./scripts/build.sh --no-sign          # Build without signing
#   ./scripts/build.sh --notarize         # Build + sign + notarize (requires Apple ID)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

APP_NAME="KeepItGoing-ClaudeChat"
BUNDLE_ID="com.twitchyvr.keepitgoing"
DIST_DIR="${REPO_ROOT}/dist"
GENERATOR_PATH="${HOME}/.claude/hooks/scripts/keepitgoing-generate.py"
SIGN_IDENTITY="Developer ID Application: Matthew Rogers (69LXV4BEHY)"
SIGN=true
NOTARIZE=false
TEAM_ID="69LXV4BEHY"

while [[ $# -gt 0 ]]; do
  case $1 in
    --generator-path) GENERATOR_PATH="$2"; shift 2 ;;
    --no-sign) SIGN=false; shift ;;
    --notarize) NOTARIZE=true; shift ;;
    --help|-h)
      echo "Usage: $0 [OPTIONS]"
      echo ""
      echo "Options:"
      echo "  --generator-path PATH   Path to keepitgoing-generate.py"
      echo "  --no-sign               Skip code signing"
      echo "  --notarize              Sign + notarize with Apple (requires app-specific password)"
      echo "  -h, --help              Show this help"
      exit 0
      ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

# Kill running instance
echo "Stopping running instance..."
osascript -e "tell application \"${APP_NAME}\" to quit" 2>/dev/null || true
sleep 1

# Patch and compile
TEMP_SCRIPT=$(mktemp /tmp/kig-build-XXXXX.applescript)
sed "s|/Users/mattrogers/.claude/hooks/scripts/keepitgoing-generate.py|${GENERATOR_PATH}|g" \
  "${REPO_ROOT}/src/main.applescript" > "${TEMP_SCRIPT}"

mkdir -p "${DIST_DIR}"
APP_PATH="${DIST_DIR}/${APP_NAME}.app"

# Remove old build
rm -rf "${APP_PATH}"

echo "Compiling AppleScript (stay-open applet)..."
osacompile -s -o "${APP_PATH}" "${TEMP_SCRIPT}"
rm -f "${TEMP_SCRIPT}"

# Set bundle identifier and stay-open flag in Info.plist
if [ -f "${APP_PATH}/Contents/Info.plist" ]; then
  /usr/libexec/PlistBuddy -c "Set :CFBundleIdentifier ${BUNDLE_ID}" "${APP_PATH}/Contents/Info.plist" 2>/dev/null || \
  /usr/libexec/PlistBuddy -c "Add :CFBundleIdentifier string ${BUNDLE_ID}" "${APP_PATH}/Contents/Info.plist"

  /usr/libexec/PlistBuddy -c "Set :CFBundleName ${APP_NAME}" "${APP_PATH}/Contents/Info.plist" 2>/dev/null || true
  /usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString 2.1.0" "${APP_PATH}/Contents/Info.plist" 2>/dev/null || \
  /usr/libexec/PlistBuddy -c "Add :CFBundleShortVersionString string 2.1.0" "${APP_PATH}/Contents/Info.plist"

  # Ensure stay-open is set (osacompile -s should do this, but belt-and-suspenders)
  /usr/libexec/PlistBuddy -c "Set :OSAAppletStayOpen true" "${APP_PATH}/Contents/Info.plist" 2>/dev/null || \
  /usr/libexec/PlistBuddy -c "Add :OSAAppletStayOpen bool true" "${APP_PATH}/Contents/Info.plist"
fi

# Code sign
if [ "$SIGN" = true ]; then
  echo "Code signing with: ${SIGN_IDENTITY}"
  codesign --force --deep --sign "${SIGN_IDENTITY}" \
    --options runtime \
    --entitlements /dev/stdin \
    "${APP_PATH}" <<'ENTITLEMENTS'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>com.apple.security.automation.apple-events</key>
    <true/>
</dict>
</plist>
ENTITLEMENTS

  echo "Verifying signature..."
  codesign --verify --deep --strict "${APP_PATH}"
  echo "Signature valid."
else
  echo "Skipping code signing (--no-sign)."
fi

# Notarize (optional — requires APPLE_ID and APP_PASSWORD env vars)
if [ "$NOTARIZE" = true ]; then
  if [ -z "${APPLE_ID:-}" ] || [ -z "${APP_PASSWORD:-}" ]; then
    echo ""
    echo "ERROR: Notarization requires APPLE_ID and APP_PASSWORD environment variables."
    echo ""
    echo "To set up:"
    echo "  1. Go to https://appleid.apple.com/account/manage"
    echo "  2. Generate an app-specific password"
    echo "  3. Export:"
    echo "     export APPLE_ID='your@email.com'"
    echo "     export APP_PASSWORD='xxxx-xxxx-xxxx-xxxx'"
    echo "  4. Run this script again with --notarize"
    exit 1
  fi

  echo "Creating zip for notarization..."
  ZIP_PATH="${DIST_DIR}/${APP_NAME}.zip"
  ditto -c -k --keepParent "${APP_PATH}" "${ZIP_PATH}"

  echo "Submitting to Apple for notarization..."
  xcrun notarytool submit "${ZIP_PATH}" \
    --apple-id "${APPLE_ID}" \
    --password "${APP_PASSWORD}" \
    --team-id "${TEAM_ID}" \
    --wait

  echo "Stapling notarization ticket..."
  xcrun stapler staple "${APP_PATH}"

  rm -f "${ZIP_PATH}"
  echo "Notarization complete."
fi

echo ""
echo "Build complete: ${APP_PATH}"
echo "Launch with: open '${APP_PATH}'"
