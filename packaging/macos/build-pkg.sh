#!/bin/bash
# Build a macOS .pkg installer from the `flet build macos` output.
#
# Usage (on the Mac, after `uv run flet build macos`):
#   ./packaging/macos/build-pkg.sh
#
# Why .pkg instead of .dmg: files installed by the macOS Installer do NOT
# inherit the com.apple.quarantine attribute, so the installed app launches
# with no Gatekeeper "damaged / unverified developer" friction and no xattr
# workarounds. The only hurdle is opening the unsigned .pkg itself — first
# time, users must right-click → Open, or on macOS 15+:
# System Settings → Privacy & Security → scroll down → "Open Anyway".
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

# Like the Inno Setup AppId on Windows: keep this identifier constant across
# versions so macOS treats new versions as upgrades of the same product.
IDENTIFIER="com.ambitions0x39e.cie-helper"
OUT="$DIST_DIR/cie-helper-$VERSION.pkg"

mkdir -p "$DIST_DIR"
pkgbuild \
  --component "$APP_PATH" \
  --install-location /Applications \
  --identifier "$IDENTIFIER" \
  --version "$VERSION" \
  "$OUT"

echo ""
echo "Built: $OUT"
echo "Reminder for recipients: first open needs right-click → Open"
echo "(macOS 15+: System Settings → Privacy & Security → Open Anyway)."
