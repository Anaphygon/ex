#!/bin/bash
# Builds Ex.app.  Usage: app/build.sh [release|debug] [OUTPUT_DIR]
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$APP_DIR")"
CONFIG="${1:-release}"
OUTPUT_DIR="${2:-$APP_DIR/build}"
VERSION="$(cat "$APP_DIR/VERSION")"
PYTHON="/opt/homebrew/bin/python3"

. "$APP_DIR/build-env.sh"
swift build --package-path "$APP_DIR" -c "$CONFIG" --product Ex 2>&1 | grep -E "error|warning: unre" || true
BINARY="$(swift build --package-path "$APP_DIR" -c "$CONFIG" --show-bin-path)/Ex"
[ -x "$BINARY" ] || { echo "build failed" >&2; exit 1; }

BUNDLE="$OUTPUT_DIR/Ex.app"
rm -rf "$BUNDLE"
mkdir -p "$BUNDLE/Contents/MacOS" "$BUNDLE/Contents/Resources"
cp "$BINARY" "$BUNDLE/Contents/MacOS/Ex"
cp "$PROJECT_DIR/integration/icon/Ex.icns" "$BUNDLE/Contents/Resources/Ex.icns"
"$PYTHON" -I "$PROJECT_DIR/integration/app_info.py" "$BUNDLE/Contents/Info.plist" "$VERSION"
# The engine travels inside the app so a downloaded Ex.app works on its own.
ENGINE="$BUNDLE/Contents/Resources/engine"
mkdir -p "$ENGINE/bin" "$ENGINE/ex"
cp "$PROJECT_DIR"/ex/*.py "$ENGINE/ex/"
cp "$PROJECT_DIR/bin/ex-engine" "$ENGINE/bin/ex-engine"
codesign --force --sign - "$BUNDLE" >/dev/null
echo "$BUNDLE"
