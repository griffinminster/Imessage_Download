#!/usr/bin/env bash
# Build "iMessage Exporter.app" via py2app.
#
# After: dist/iMessage Exporter.app — double-clickable, shareable.
#
# First launch on a recipient's Mac will be blocked by Gatekeeper
# ("unidentified developer"). They right-click → Open the first time,
# then it works normally forever.

set -euo pipefail

cd "$(dirname "$0")"

echo "→ installing build dependencies"
python3 -m pip install --quiet --upgrade py2app setuptools

echo "→ cleaning previous build artifacts"
rm -rf build dist

echo "→ running py2app"
python3 setup.py py2app

APP="dist/iMessage Exporter.app"
if [[ -d "$APP" ]]; then
    SIZE=$(du -sh "$APP" | cut -f1)
    echo
    echo "✓ built: $APP  ($SIZE)"
    echo
    echo "Distribute:"
    echo "  • zip it:           ditto -c -k --keepParent \"$APP\" \"iMessage Exporter.app.zip\""
    echo "  • or drag to /Applications and share the .zip"
    echo
    echo "First-launch on recipient's Mac:"
    echo "  1. Right-click the app → Open  (Gatekeeper bypass, one-time)"
    echo "  2. Grant Full Disk Access in System Settings → Privacy & Security"
    echo "  3. When prompted, allow Contacts access"
else
    echo "✗ build failed — no $APP found"
    exit 1
fi
