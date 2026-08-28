#!/bin/bash
# Build a macOS .dmg from the `flet build macos` output.
#
# Usage (on the Mac, after `uv run flet build macos`):
#   ./packaging/macos/build-dmg.sh
#
# The image is unsigned, so a copy dragged out of it keeps the quarantine flag
# the browser put on the download and Gatekeeper calls it damaged. Recipients
# clear it once, by pasting one line into Terminal:
#   xattr -rd com.apple.quarantine /Applications/cie-helper.app
# The in-app updater needs none of that: it fetches the image itself, so
# nothing ever attaches a quarantine flag to it.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BUILD_DIR="$REPO_ROOT/build/macos"
DIST_DIR="$REPO_ROOT/dist"

# Single source of truth for the version: [project].version in pyproject.toml
VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' "$REPO_ROOT/pyproject.toml" | head -1)"
if [[ -z "$VERSION" ]]; then
  echo "Could not read version from pyproject.toml" >&2
  exit 1
fi

# flet names the .app after the project — auto-detect instead of hardcoding.
APP_PATH="$(find "$BUILD_DIR" -maxdepth 1 -name '*.app' -print -quit 2>/dev/null || true)"
if [[ -z "$APP_PATH" ]]; then
  echo "No .app found in $BUILD_DIR — run 'uv run flet build macos' first." >&2
  exit 1
fi

OUT="$DIST_DIR/cie-helper-$VERSION-setup.dmg"

# Stage the bundle plus the /Applications shortcut users drag onto. The
# staging dir MUST live outside the repo: `flet build` copies the app-source
# tree following symlinks, and an `Applications -> /Applications` link inside
# it makes the macOS packaging step recursively copy every installed app into
# the bundle — a runaway that once ate ~200 GB.
STAGING="$(mktemp -d)"
trap 'rm -rf "$STAGING"' EXIT
cp -R "$APP_PATH" "$STAGING/"
ln -s /Applications "$STAGING/Applications"

mkdir -p "$DIST_DIR"
hdiutil create \
  -volname "CIE Helper" \
  -srcfolder "$STAGING" \
  -format UDZO \
  -ov \
  "$OUT"

echo ""
echo "Built: $OUT"
echo "Drag target inside the image: $(basename "$APP_PATH") -> Applications"
echo "Reminder for recipients: after dragging, run"
echo "  xattr -rd com.apple.quarantine /Applications/$(basename "$APP_PATH")"
