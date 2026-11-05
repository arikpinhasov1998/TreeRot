#!/usr/bin/env bash
# Builds the Linux or macOS program into dist/release/
#   Linux:  treerot-linux-<arch>.tar.gz  (one program: window and command line)
#   macOS:  TreeRot-macos-<arch>.zip     (TreeRot.app + command line)
# On Windows use build_exe.bat instead.
set -euo pipefail
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"
if ! "$PY" -c "import tkinter; tkinter.Tcl()" >/dev/null 2>&1; then
  echo "Python's tkinter is missing; the window needs it."
  echo "  Linux: sudo apt install python3-tk   (Fedora/RHEL: sudo dnf install python3-tkinter)"
  echo "  macOS: use Python from python.org, or: brew install python-tk"
  exit 1
fi

if [ ! -x .venv-build/bin/python ]; then
  echo "=== Creating the build environment .venv-build ==="
  "$PY" -m venv .venv-build
fi
VPY=.venv-build/bin/python
echo "=== Installing the build tool ==="
"$VPY" -m pip install --upgrade pip >/dev/null
"$VPY" -m pip install -r requirements-build.txt

ARCH="$(uname -m)"
rm -rf dist/release
mkdir -p dist/release

case "$(uname -s)" in
  Linux)
    "$VPY" -m PyInstaller --noconfirm --clean --onefile \
      --name treerot treerot.py
    # a .tar.gz keeps the "executable" permission, a plain download would lose it
    tar -czf "dist/release/treerot-linux-$ARCH.tar.gz" -C dist treerot
    ;;
  Darwin)
    ICON_ARGS=""
    if [ -f app.icns ]; then ICON_ARGS="--icon app.icns"; fi
    # shellcheck disable=SC2086
    "$VPY" -m PyInstaller --noconfirm --clean --windowed --onedir $ICON_ARGS \
      --name TreeRot --osx-bundle-identifier io.github.arikpinhasov1998.treerot \
      treerot.py
    # PyInstaller leaves the app's version at 0.0.0. Changing Info.plist voids the signature, so sign again.
    VERSION="$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' treerot.py)"
    plutil -replace CFBundleShortVersionString -string "$VERSION" dist/TreeRot.app/Contents/Info.plist
    plutil -replace CFBundleVersion -string "$VERSION" dist/TreeRot.app/Contents/Info.plist
    codesign --force --deep --sign - dist/TreeRot.app
    # The CLI gets its own folders: on case-insensitive disks "treerot" and "TreeRot" are the same name.
    "$VPY" -m PyInstaller --noconfirm --onefile \
      --distpath dist/cli --workpath build/cli --specpath build/cli \
      --name treerot treerot.py
    rm -rf dist/pkg
    mkdir -p dist/pkg/TreeRot
    ditto dist/TreeRot.app dist/pkg/TreeRot/TreeRot.app
    cp dist/cli/treerot dist/pkg/TreeRot/
    # ditto keeps the app bundle intact (a plain zip can break it)
    ditto -c -k --keepParent dist/pkg/TreeRot \
      "dist/release/TreeRot-macos-$ARCH.zip"
    ;;
  *)
    echo "Unsupported system: $(uname -s). On Windows run build_exe.bat."
    exit 1
    ;;
esac

echo
echo "Done:"
ls -1 dist/release/
