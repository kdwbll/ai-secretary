#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
python_bin="${SECOND_BRAIN_BUILD_PYTHON:-python3}"
version="$(sed -n 's/^APP_VERSION = "\([^"]*\)"/\1/p' core/secretary/app.py)"
arch="$(uname -m)"
"$python_bin" -m PyInstaller --noconfirm --clean macos/SecondBrain.spec
stage="$(mktemp -d /tmp/secondbrain-dmg.XXXXXX)"
cp -R dist/SecondBrain.app "$stage/SecondBrain.app"
ln -s /Applications "$stage/Applications"
cp docs/install-macos.txt "$stage/README.txt"
mkdir -p dist-release
hdiutil create -volname "SecondBrain $version" -srcfolder "$stage" -ov -format UDZO \
    "dist-release/SecondBrain-macOS-$arch-$version.dmg"
