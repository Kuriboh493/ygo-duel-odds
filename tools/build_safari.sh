#!/bin/bash
# Builds the Safari version: a small macOS app that carries the web extension, which is how Safari installs extensions.
# Needs Xcode (the GitHub workflows run this on a macOS runner). Writes build/ygo-duel-odds-safari.zip.
# The app is ad-hoc signed, not signed by an Apple Developer account, so Safari only runs it with
# "Allow unsigned extensions" turned on (see the README).
set -euo pipefail
cd "$(dirname "$0")/.."
VERSION=$(python3 -c "import json; print(json.load(open('extension/manifest.json'))['version'])")
NAME="YGO Duel Odds"
rm -rf build/safari build/ygo-duel-odds-safari.zip
mkdir -p build/safari

xcrun safari-web-extension-converter extension \
  --project-location build/safari --app-name "$NAME" --bundle-identifier com.kuriboh493.ygoduelodds \
  --macos-only --copy-resources --no-open --no-prompt --force

xcodebuild -project "build/safari/$NAME/$NAME.xcodeproj" -scheme "$NAME" -configuration Release \
  -derivedDataPath build/safari/dd MARKETING_VERSION="$VERSION" CURRENT_PROJECT_VERSION="$VERSION" \
  CODE_SIGN_IDENTITY=- CODE_SIGN_STYLE=Manual DEVELOPMENT_TEAM= build

APP="build/safari/dd/Build/Products/Release/$NAME.app"
test -f "$APP/Contents/PlugIns/$NAME Extension.appex/Contents/Resources/manifest.json"
ditto -c -k --keepParent "$APP" build/ygo-duel-odds-safari.zip
echo "Built build/ygo-duel-odds-safari.zip ($VERSION)"
