#!/bin/bash
# Builds a release Ex.app and packs it into app/build/Ex-<version>.dmg.
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERSION="$(cat "$APP_DIR/VERSION")"
OUTPUT="$APP_DIR/build/Ex-$VERSION.dmg"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

"$APP_DIR/build.sh" release "$STAGE" >/dev/null
ln -s /Applications "$STAGE/Applications"
mkdir -p "$(dirname "$OUTPUT")"
rm -f "$OUTPUT"
hdiutil create -quiet -volname "Ex $VERSION" -srcfolder "$STAGE" -format UDZO -fs HFS+ "$OUTPUT"
echo "$OUTPUT"
