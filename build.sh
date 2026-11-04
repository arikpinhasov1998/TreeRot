#!/usr/bin/env bash
# Builds the Linux or macOS program into dist/release/
#   Linux:  folder-activity-scanner-linux-<arch>.tar.gz   (one program: window and command line)
#   macOS:  FolderActivityScanner-macos-<arch>.zip        (FolderActivityScanner.app + command line)
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
      --name folder-activity-scanner folder_activity_scanner.py
    # a .tar.gz keeps the "executable" permission, a plain download would lose it
    tar -czf "dist/release/folder-activity-scanner-linux-$ARCH.tar.gz" -C dist folder-activity-scanner
    ;;
  Darwin)
    ICON_ARGS=""
    if [ -f app.icns ]; then ICON_ARGS="--icon app.icns"; fi
    # shellcheck disable=SC2086
    "$VPY" -m PyInstaller --noconfirm --clean --windowed --onedir $ICON_ARGS \
      --name FolderActivityScanner --osx-bundle-identifier io.github.folderactivityscanner \
      folder_activity_scanner.py
    "$VPY" -m PyInstaller --noconfirm --onefile \
      --name folder-activity-scanner folder_activity_scanner.py
    rm -rf dist/pkg
    mkdir -p dist/pkg/FolderActivityScanner
    ditto dist/FolderActivityScanner.app dist/pkg/FolderActivityScanner/FolderActivityScanner.app
    cp dist/folder-activity-scanner dist/pkg/FolderActivityScanner/
    # ditto keeps the app bundle intact (a plain zip can break it)
    ditto -c -k --keepParent dist/pkg/FolderActivityScanner \
      "dist/release/FolderActivityScanner-macos-$ARCH.zip"
    ;;
  *)
    echo "Unsupported system: $(uname -s). On Windows run build_exe.bat."
    exit 1
    ;;
esac

echo
echo "Done:"
ls -1 dist/release/
