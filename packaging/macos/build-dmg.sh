#!/bin/bash
# Build a macOS .dmg from the PyInstaller output.
#
# Usage (on a Mac — there is no cross-compiling a .app from Windows):
#   npm run build --prefix frontend
#   uv run pyinstaller packaging/cie-helper.spec --noconfirm
#   ./packaging/macos/build-dmg.sh
#
# The frontend build is not optional and not skippable: the spec bundles
# frontend/dist exactly as it finds it on disk, so a stale UI ships in silence.
#
# The image is unsigned, so a copy dragged out of it keeps the quarantine flag
# the browser put on the download and Gatekeeper calls it damaged. Recipients
# clear it once, by pasting one line into Terminal:
#   xattr -rd com.apple.quarantine "/Applications/CIE Helper.app"
# The in-app updater needs none of that: it fetches the image itself, so
# nothing ever attaches a quarantine flag to it.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DIST_DIR="$REPO_ROOT/dist"

# Single source of truth for the version: [project].version in pyproject.toml
VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' "$REPO_ROOT/pyproject.toml" | head -1)"
if [[ -z "$VERSION" ]]; then
  echo "Could not read version from pyproject.toml" >&2
  exit 1
fi

# BUNDLE names it "CIE Helper.app", but find it rather than hardcode the name —
# renaming it in the spec should not silently break the packaging step.
APP_PATH="$(find "$DIST_DIR" -maxdepth 1 -name '*.app' -print -quit 2>/dev/null || true)"
if [[ -z "$APP_PATH" ]]; then
  echo "No .app in $DIST_DIR — run 'uv run pyinstaller packaging/cie-helper.spec --noconfirm' first." >&2
  exit 1
fi

# The bundled UI is the one thing a build can lose without failing, so check it
# is actually in there before shipping an app that opens on a blank window.
if [[ ! -f "$APP_PATH/Contents/Frameworks/frontend/dist/index.html" ]]; then
  echo "$(basename "$APP_PATH") has no frontend/dist — run 'npm run build --prefix frontend', then re-run PyInstaller." >&2
  exit 1
fi

OUT="$DIST_DIR/cie-helper-$VERSION-setup.dmg"

# Stage the bundle plus the /Applications shortcut users drag onto. The
# staging dir MUST live outside the repo: a packaging step that copies the
# source tree following symlinks would treat an `Applications -> /Applications`
# link inside it as a directory to recurse into and copy every installed app —
# a runaway that once ate ~200 GB.
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
echo "  xattr -rd com.apple.quarantine \"/Applications/$(basename "$APP_PATH")\""
