import atexit
import importlib.util
import os
import shutil
import sys
import tempfile
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
app = importlib.import_module("treerot")

# Tests save settings: never touch the real ~/.treerot.json.
_SETTINGS_DIR = tempfile.mkdtemp(prefix="treerot-test-settings-")
atexit.register(shutil.rmtree, _SETTINGS_DIR, True)
app.SETTINGS_FILE = os.path.join(_SETTINGS_DIR, ".treerot.json")
app.OLD_SETTINGS_FILE = os.path.join(_SETTINGS_DIR, ".folder_activity_scanner.json")
# Nor the real list of background scans: a window opened by a test reads it.
app.JOBS_DIR = os.path.join(_SETTINGS_DIR, "jobs")

OLD = datetime(2019, 1, 1).timestamp()
NEW = datetime(2026, 1, 1).timestamp()


def make_tree(root, spec):
    """spec maps a relative path to a file's mtime, or None for a directory."""
    for rel, mtime in spec.items():
        path = os.path.join(root, *rel.split("/"))
        if mtime is None:
            os.makedirs(path, exist_ok=True)
            continue
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(b"x" * 100)
        os.utime(path, (mtime, mtime))


def scan_rows(root, d_from, created="off", excludes=None):
    folders, _ = app.scan_tree(root, excludes=excludes, stats={},
                               date_from_ts=d_from.timestamp(), created=created)
    return {os.path.relpath(r["info"].path, root).replace(os.sep, "/"): r
            for r in app.build_rows(folders, d_from, None)}
