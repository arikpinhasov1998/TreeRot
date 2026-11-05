#!/usr/bin/env python3
"""
TreeRot - find the rot in your folder tree
------------------------------------------
Created by Arik Pinhasov, https://github.com/arikpinhasov1998
Scans a folder tree (local disk, mounted/UNC network share, NAS) and shows an
expandable tree where every folder is colored:

    GREEN  = used in the period (a From date and an optional To date)
    RED    = NOT used in the period
    GRAY   = empty folder / unreadable

"Used" means a FILE anywhere inside the folder was MODIFIED or CREATED in the period
(default), whatever the folder's own date says. Creation time is read on Windows and
macOS; Linux does not expose it (see --created). Alternatively the GUI can color by the
folder's own timestamp only.

Open the GUI:    python treerot.py
Run headless:    python treerot.py PATH [options]
                 (no display and no tkinter needed - for servers, SSH, cron, Task Scheduler)

Headless examples:
    python treerot.py /srv/share --from 2024-10-28 --format tree --depth 3
    python treerot.py /srv/share --years 2 --show red -o unused.csv
    python treerot.py "\\\\server\\share" --exclude-common --format summary
    python treerot.py /srv/share --precount --progress lines -o report.csv
    python treerot.py /srv/share --format summary --report share_report.html
    python treerot.py /srv/share --format summary --report share_report.pdf --report-tree 3
Run with --help for every option.

Exclusions (skipped entirely - not scanned, not counted) can be:
    a name or wildcard      .snapshot   node_modules   *backup*
    a path relative to root Projects\\Old   (wildcards allowed)
    an absolute path        \\\\server\\share\\Projects\\Old

Requires only the Python 3.8+ standard library (tkinter ships with Python).
"""

import argparse
import atexit
import contextlib
import csv
import errno
import fnmatch
import json
import ntpath
import os
import queue
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from datetime import datetime, timedelta

# --------------------------------------------------------------------------
# Core scanning logic (no GUI dependencies)
# --------------------------------------------------------------------------


QUOTE = chr(34)                       # the double-quote character, used to trim pasted paths
__version__ = "1.2.0"
GREEN, RED, GRAY = "green", "red", "gray"
COLOR_LABEL = {GREEN: "USED in the period", RED: "NOT used in the period",
               GRAY: "EMPTY / ERROR"}


# Windows and macOS (and the BSDs) report a real file creation time; Linux does not.
CREATED_NATIVE = sys.platform in ("win32", "darwin") or "bsd" in sys.platform


def file_created(st, mode):
    """
    Creation time of a file from its stat result, or None.
    mode "auto":  the real creation time where the OS has one (Windows, macOS), else None.
    mode "ctime": like auto, but on Linux fall back to the change time (ctime). A copied-in
                  file gets a new ctime, but so does a rename or a permission change.
    mode "off":   never use creation time.
    """
    if mode == "off":
        return None
    b = getattr(st, "st_birthtime", None)         # Windows (Python 3.12+), macOS, BSD
    if b:
        return b
    if sys.platform == "win32" or mode == "ctime":
        return st.st_ctime                        # creation time on Windows before 3.12
    return None


class FolderInfo:
    __slots__ = (
        "path", "depth", "own_mtime", "newest_file_mtime",
        "direct_files", "total_files", "total_size", "error", "parent",
        "range_files", "range_size", "direct_size", "unreadable", "unreadable_below", "excluded_dirs",
        "error_op", "error_errno", "error_win_code", "error_msg", "error_count",
    )

    def __init__(self, path, depth, parent):
        self.path = path
        self.depth = depth
        self.parent = parent            # parent path or None
        self.own_mtime = None           # folder's own timestamp
        self.newest_file_mtime = None   # last file activity below (later of modified/created)
        self.direct_files = 0
        self.total_files = 0            # recursive
        self.total_size = 0             # recursive, bytes
        self.range_files = 0            # recursive count of files modified/created in the period
        self.range_size = 0             # recursive bytes of files modified/created in the period
        self.direct_size = 0            # bytes of files directly in this folder (not below)
        self.unreadable = False         # the folder could not be opened/listed at all
        self.unreadable_below = 0       # recursive count of unreadable sub-folders
        self.excluded_dirs = 0          # direct sub-folders skipped because of exclusions
        self.error = ""
        self.error_op = ""              # stat / scandir / read / entry
        self.error_errno = None
        self.error_win_code = None
        self.error_msg = ""
        self.error_count = 0


COMMON_EXCLUDES = [
    "$RECYCLE.BIN", "System Volume Information", ".snapshot", "~snapshot",
    "#snapshot", "#recycle", "@Recycle", "@eaDir", ".Trash-*", "lost+found",
]

APP_NAME = "TreeRot"
CREDIT = "Created by Arik Pinhasov"
CREDIT_URL = "https://github.com/arikpinhasov1998"
ICON_PNG_B64 = 'iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAYAAACqaXHeAAADAUlEQVR42u2bv2sUQRTH5w+5v8DGYHVcGWwsLNfCKhAEsRJyYmMdq8NCsAhioaIQJEiKSOwUOSVY+gPBBDlBJSAo2I/7XXLLMuyPmb33Yza3Bw+OC2Hv+7l5896bN8+Yhte/v7+GqU1Sm6ZmO2LTk+88NG1f6T8nqc06JLrKoCEJET5IbfsUCHcNmgY+4menUHxxNQyWVXw9BI1lv37pQmYa7lC24Yl+ib2dx3Z0ZpAZ3itASIoARJf+0c/Pdnx3IwfwbHzN/jn8IO4KxTgv9uB3R2/t+adX7LmbqzmAh6MV+yW5aH8fvJKGMDQnCYPIA++/f2LPPkgycwF8Wh1l9uPRliSAiZHK8K7vb+bi6wDAvt0ai2WMRkN8EwBJCEZDvA8AKQhGQ7wvAAkIbAA2X9+rFB8CAPb9zu1uAdj9+KJWfCgA2PHeTjcAIMlBnKcGgDyBI1kykn6/CACu/cBQZ3k+4tsCgFFni6QALj+/wQ7g69W1OAGE/PqLAKBeBUba90MAoC7AxgdDKOTYC8gAhIj3AVAW9gBk/veoAPjE/RAACHlVz6LOC4zG8l+kGqR2AxIAPolPqAuUPQd7gc8qEQcQKr5tOYzPmiCJAwgNfyFRADEfuz8MvzhHODQaG+CieQDlRtgD6AF0EAD2BthSAoiuGMIBiCQA6r5BtHlA3ckQwh9VRWikzwF8AcwFIvtzEyBKVzASJ8ChANxTYMDgOimOshp0/bxYA0RZDbYpiJrK4eIJsOsCVIUQKYBQN2jaAyASwuHrnI0SQ9kPkEqEKPsD/alw3xfoO0P0vUEuAJ3oDbp3gagAcN0dYrsf0OQKIQA4L0mwAWhqk/sC4GqLi1yRqYsKvgC47w6yX5KqqhN8AHDdChEFUAWhTW+wswDKINQBkBIvCsCFUAVAUvwcwFQDQhkAafHzq7IT4YdmEFwACuLzy9JDhQfHMDBh87E6jVmhCADM+pEZzaEpZQDb6mNzigDimB08ePMyB4D36uI1RmchXFB88+hsPzy9hOPz/wGvgFbabsQh1AAAAABJRU5ErkJggg=='

SETTINGS_FILE = os.path.join(os.path.expanduser("~"), ".treerot.json")
OLD_SETTINGS_FILE = os.path.join(os.path.expanduser("~"), ".folder_activity_scanner.json")


def load_settings():
    for path, migrating in ((SETTINGS_FILE, False), (OLD_SETTINGS_FILE, True)):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        if migrating:
            save_settings(data)
        return data
    return {}


def save_settings(data):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except OSError:
        pass


def totals_key(root, excludes, follow_symlinks):
    """Identifies 'the same scan' so the last run's totals can drive the next progress bar."""
    r = os.path.normcase(os.path.normpath(root))
    return json.dumps([r, sorted(excludes or []), bool(follow_symlinks)])


def last_totals(settings, key):
    t = (settings.get("last_totals") or {}).get(key)
    if isinstance(t, list) and len(t) >= 2:
        try:
            return int(t[0]), int(t[1])
        except (TypeError, ValueError):
            return None
    return None


def remember_totals(settings, key, folders, files):
    hist = dict(settings.get("last_totals") or {})
    hist.pop(key, None)
    hist[key] = [folders, files, datetime.now().strftime("%Y-%m-%d %H:%M")]
    while len(hist) > 50:                      # keep the 50 most recent scans
        hist.pop(next(iter(hist)))
    settings["last_totals"] = hist


def make_excluder(root, excludes):
    """
    Return is_excluded(path, name). Each exclude entry may be:
      * absolute path / UNC path  -> that folder and everything below it
      * relative path (has / or \\) -> matched against the path relative to the scan root
      * plain name or wildcard    -> matched against every folder's own name
    """
    abs_set, rel_pats, name_pats = set(), [], []
    for raw in excludes or []:
        p = raw.strip().strip(QUOTE)
        if not p:
            continue
        if os.path.isabs(p) or p.startswith("\\\\"):
            abs_set.add(os.path.normcase(os.path.normpath(p)))
        elif "/" in p or "\\" in p:
            rel_pats.append(os.path.normcase(os.path.normpath(p)))
        else:
            name_pats.append(p.lower())
    if not (abs_set or rel_pats or name_pats):
        return lambda path, name: False
    root_n = os.path.normcase(os.path.normpath(root))

    def is_excluded(path, name):
        n = os.path.normcase(os.path.normpath(path))
        if n in abs_set:
            return True
        name_lower = name.lower()
        for pat in name_pats:
            if fnmatch.fnmatchcase(name_lower, pat):
                return True
        if rel_pats and n.startswith(root_n):
            rel = n[len(root_n):].lstrip("\\/")
            for pat in rel_pats:
                if fnmatch.fnmatchcase(rel, pat):
                    return True
        return False

    return is_excluded


def record_error(info, op, exc, target=None):
    """Remember the first problem on a folder in detail, and count the rest."""
    info.error_count += 1
    if info.error:
        return
    msg = exc.strerror or str(exc)
    if target:
        msg = f"{target}: {msg}"
    info.error_op = op
    info.error_errno = getattr(exc, "errno", None)
    # noinspection SpellCheckingInspection
    info.error_win_code = getattr(exc, "winerror", None)   # only exists on Windows
    info.error_msg = msg
    info.error = f"{op}: {msg}"


def _codes(*names):
    return {getattr(errno, n) for n in names if hasattr(errno, n)}


def explain_os_error(code, win_code):
    """Plain-language likely cause for an OSError (empty string if nothing useful to add)."""
    if win_code == 5 or code in _codes("EACCES", "EPERM"):
        return ("Access denied - the account running this tool has no read permission on this "
                "folder. Ask the share/NAS admin for read access, run the tool as a user who "
                "has it, or exclude the folder.")
    if win_code == 206 or code in _codes("ENAMETOOLONG"):
        return ("The path is too long for this system (Windows limit is 260 characters unless "
                "long paths are enabled). Scan from a deeper starting folder or enable long paths.")
    if win_code in (53, 55, 59, 64, 67, 1219, 1231) or code in _codes(
            "ENETUNREACH", "ENETDOWN", "EHOSTUNREACH", "ECONNRESET", "ECONNABORTED", "ENOTCONN"):
        return ("The network share became unreachable or disconnected during the scan. "
                "Check the connection and rescan.")
    if win_code == 121 or code in _codes("ETIMEDOUT"):
        return "The file server did not respond in time (timeout). Rescan, or try off-peak hours."
    if code in _codes("ESTALE"):
        return "Stale NFS file handle - the folder changed on the server. Remount the share and rescan."
    if code in _codes("ELOOP"):
        return "Symbolic-link loop detected."
    if win_code in (2, 3) or code in _codes("ENOENT"):
        return ("The folder was deleted or renamed while the scan was running, or its path "
                "could not be resolved.")
    if code in _codes("ENOTDIR"):
        return "This item is no longer a folder (it was replaced while the scan was running)."
    if code in _codes("EIO") or win_code in (23, 1117):
        return "I/O error - this can indicate a disk or network fault, or a damaged folder."
    return ""


def error_detail(i):
    """Lines describing the first OS error recorded on folder `i`."""
    code = f"errno {i.error_errno}" if i.error_errno is not None else ""
    if i.error_win_code:
        code += (", " if code else "") + f"Windows error {i.error_win_code}"
    lines = [f"System message ({i.error_op}{', ' + code if code else ''}): {i.error_msg}"]
    hint = explain_os_error(i.error_errno, i.error_win_code)
    if hint:
        lines.append("Likely cause: " + hint)
    if i.error_count > 1:
        lines.append(f"{i.error_count - 1:,} more problem(s) occurred in this folder.")
    return lines


def count_tree(root, cancel_event=None, progress_cb=None, follow_symlinks=False, excludes=None):
    """
    Optional fast first pass so progress can be exact: counts folders and files without
    reading any file details. Returns (folders, files), or None if canceled.
    It still lists every folder once, so on a network share it can add 50-100% to the run time.
    """
    if not root.startswith("\\\\"):
        root = os.path.abspath(root)
    is_excluded = make_excluder(root, excludes)
    stack = [root]
    n_folders = n_files = 0
    last = 0.0
    path = root
    while stack:
        if cancel_event is not None and cancel_event.is_set():
            return None
        path = stack.pop()
        n_folders += 1
        try:
            with os.scandir(path) as it:
                for entry in it:
                    try:
                        if entry.is_dir(follow_symlinks=follow_symlinks):
                            if not is_excluded(entry.path, entry.name):
                                stack.append(entry.path)
                        elif entry.is_file(follow_symlinks=False):
                            n_files += 1
                    except OSError:
                        pass
        except OSError:
            pass
        now = time.monotonic()
        if progress_cb and now - last > 0.25:
            last = now
            progress_cb({"phase": "count", "folders": n_folders, "files": n_files,
                         "current": path})
    if progress_cb:
        progress_cb({"phase": "count", "folders": n_folders, "files": n_files, "current": ""})
    return n_folders, n_files


AWAKE_NOTE = "Could not stop this computer from going to sleep. A sleeping computer pauses the scan."
_AWAKE_CHILDREN = {}           # helper processes holding the computer awake right now
_AWAKE_LOCK = threading.Lock()


def awake_watcher_args(pid, interval=5):
    """A POSIX shell loop that ends by itself once process `pid` is gone (busybox has no
    `tail --pid`). It is what systemd-inhibit runs, so a TreeRot killed with SIGKILL or SIGTERM
    does not leave the inhibitor open: the lock lasts at most `interval` seconds longer."""
    return ["sh", "-c", 'while kill -0 "$0" 2>/dev/null; do sleep "$1"; done',
            str(int(pid)), str(interval)]


def _stop_helper(child, grouped=False):
    """Ends a helper. A grouped one leads its own process group, which is ended whole, since
    systemd-inhibit forks its command and ending only the parent would orphan it."""
    try:
        if grouped:
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except Exception:
                child.terminate()
        else:
            child.terminate()
        try:
            child.wait(2)            # reap it, so no zombie is left behind
        except subprocess.TimeoutExpired:      # ignored SIGTERM: end it for certain
            if grouped:
                try:
                    os.killpg(child.pid, getattr(signal, "SIGKILL", signal.SIGTERM))
                except Exception:
                    child.kill()
            else:
                child.kill()
            child.wait(2)
    except Exception:
        pass


def release_all_awake():
    """Ends every helper process still keeping the computer awake. The window calls this when
    it closes, and it runs at exit, so no caffeinate or systemd-inhibit outlives the program."""
    with _AWAKE_LOCK:
        children = list(_AWAKE_CHILDREN.items())
        _AWAKE_CHILDREN.clear()
    for child, grouped in children:
        _stop_helper(child, grouped)


atexit.register(release_all_awake)


@contextlib.contextmanager
def keep_awake(platform=None, popen=None, which=None, windows_api=None):
    """
    Stops the computer sleeping while the block runs. Yields a note, empty when it worked.
    On Windows the setting belongs to the calling thread, so use this on the scanning thread.
    """
    platform = platform or sys.platform
    popen = popen or subprocess.Popen
    which = which or shutil.which
    child, note, grouped = None, "", False
    try:
        if platform == "win32":
            if windows_api is None:
                import ctypes
                windows_api = ctypes.windll.kernel32.SetThreadExecutionState
            windows_api(0x80000001)                       # ES_CONTINUOUS | ES_SYSTEM_REQUIRED
        elif platform == "darwin" and which("caffeinate"):
            child = popen(["caffeinate", "-i", "-w", str(os.getpid())],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif platform != "darwin" and which("systemd-inhibit") and which("sleep"):
            grouped = True
            child = popen(["systemd-inhibit", "--what=sleep", f"--who={APP_NAME}",
                           "--why=Scanning a folder tree"] + awake_watcher_args(os.getpid()),
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                          start_new_session=True)
        else:
            note = AWAKE_NOTE
        if child is not None:
            try:                     # a helper that quits at once (no D-Bus, no polkit) is no help
                child.wait(0.2)
                child, note = None, AWAKE_NOTE
            except subprocess.TimeoutExpired:
                pass                 # still running: it holds the computer awake
    except Exception:
        note = AWAKE_NOTE
    if child is not None:
        with _AWAKE_LOCK:
            _AWAKE_CHILDREN[child] = grouped
    try:
        yield note
    finally:
        try:
            if platform == "win32" and windows_api is not None and not note:
                windows_api(0x80000000)                   # ES_CONTINUOUS: back to normal
        except Exception:
            pass
        if child is not None:
            with _AWAKE_LOCK:
                _AWAKE_CHILDREN.pop(child, None)
            _stop_helper(child, grouped)


def scan_tree(root, cancel_event=None, progress_cb=None, follow_symlinks=False,
              excludes=None, stats=None, date_from_ts=None, date_to_ts=None, totals=None,
              totals_exact=True, created="auto"):
    """
    Walk `root` iteratively and return ({path: FolderInfo}, canceled).
    Files are NOT stored individually, only aggregated, so memory scales with
    the number of folders, not files.

    `excludes` - list of names / wildcards / paths to skip entirely (see make_excluder).
    `stats`    - optional dict; stats["excluded"] receives the number of skipped folders.
    `date_from_ts` / `date_to_ts` - period bounds as timestamps (None = open-ended);
                 files whose mtime falls inside are counted in FolderInfo.range_files.
    `totals`   - (folders, files) from count_tree() for exact progress, or from the last
                 finished scan of the same path (then pass totals_exact=False). Without it the
                 progress fraction is ESTIMATED from the shape of the tree: every folder's
                 share of the work is split evenly between itself and its sub-folders.
                 This costs nothing extra, always ends at exactly 100%, but can move
                 unevenly when one sub-folder is much bigger than its siblings.
    `created`  - "auto" / "ctime" / "off": also count a file as active when it was CREATED in
                 the period (see file_created). A copied file keeps its old modified date but
                 gets a new creation date, so without this a freshly copied folder looks unused.
    `progress_cb(dict)` is called about 4 times a second with phase, folders, files,
                 bytes, fraction (0..1), exact, total_folders, total_files, current.
    """
    if not root.startswith("\\\\"):
        root = os.path.abspath(root)
    is_excluded = make_excluder(root, excludes)
    n_excluded = 0
    folders = {}
    stack = [(root, 0, None, 1.0)]       # path, depth, parent, share of the total work
    n_folders = n_files = n_bytes = 0
    done_w = 0.0
    last_report = 0.0

    def report(current, final=False):
        if totals:
            tot = totals[0] + totals[1]
            frac = min(0.999, (n_folders + n_files) / tot) if tot else 0.999
        else:
            frac = min(0.999, done_w)
        progress_cb({"phase": "scan", "folders": n_folders, "files": n_files, "bytes": n_bytes,
                     "fraction": 1.0 if final else frac,
                     "exact": bool(totals) and totals_exact, "has_totals": bool(totals),
                     "total_folders": totals[0] if totals else None,
                     "total_files": totals[1] if totals else None, "current": current})

    canceled = False
    while stack:
        if cancel_event is not None and cancel_event.is_set():
            canceled = True             # stop, but still total up what was scanned (below)
            break
        path, depth, parent, weight = stack.pop()
        info = FolderInfo(path, depth, parent)
        folders[path] = info

        try:
            info.own_mtime = os.stat(path).st_mtime
        except OSError as e:
            record_error(info, "stat", e)

        newest = None
        subdirs = []
        try:
            it = os.scandir(path)
        except OSError as e:
            info.unreadable = True
            record_error(info, "scandir", e)
        else:
            try:
                with it:
                    for entry in it:
                        try:
                            if entry.is_dir(follow_symlinks=follow_symlinks):
                                if is_excluded(entry.path, entry.name):
                                    n_excluded += 1
                                    info.excluded_dirs += 1
                                    continue
                                subdirs.append(entry.path)
                            elif entry.is_file(follow_symlinks=False):
                                st = entry.stat(follow_symlinks=False)
                                info.direct_files += 1
                                info.total_files += 1
                                info.total_size += st.st_size
                                info.direct_size += st.st_size
                                n_bytes += st.st_size
                                m = st.st_mtime
                                c = file_created(st, created)
                                if ((date_from_ts is None or m >= date_from_ts)
                                        and (date_to_ts is None or m <= date_to_ts)) or (
                                        c is not None
                                        and (date_from_ts is None or c >= date_from_ts)
                                        and (date_to_ts is None or c <= date_to_ts)):
                                    info.range_files += 1
                                    info.range_size += st.st_size
                                n_files += 1
                                if c is not None and c > m:
                                    m = c               # last activity = later of modified/created
                                if newest is None or m > newest:
                                    newest = m
                        except OSError as e:
                            record_error(info, "entry", e, target=entry.name)
            except OSError as e:          # listing broke part-way (e.g. connection dropped)
                record_error(info, "read", e)

        info.newest_file_mtime = newest
        n_folders += 1
        if subdirs:
            share = weight / (len(subdirs) + 1)
            done_w += share
            stack.extend((d, depth + 1, path, share) for d in subdirs)
        else:
            done_w += weight

        now = time.monotonic()
        if progress_cb and now - last_report > 0.25:
            last_report = now
            report(path)

    if progress_cb and not canceled:
        report("", final=True)
    if stats is not None:
        stats["excluded"] = n_excluded

    # Roll children up into parents: deepest folders first.
    for info in sorted(folders.values(), key=lambda f: f.depth, reverse=True):
        if info.parent is None:
            continue
        p = folders[info.parent]
        p.total_files += info.total_files
        p.total_size += info.total_size
        p.range_files += info.range_files
        p.range_size += info.range_size
        p.unreadable_below += info.unreadable_below + (1 if info.unreadable else 0)
        if info.newest_file_mtime is not None and (
            p.newest_file_mtime is None or info.newest_file_mtime > p.newest_file_mtime
        ):
            p.newest_file_mtime = info.newest_file_mtime

    return folders, canceled


def parse_date(text, end_of_day=False):
    """'YYYY-MM-DD' -> datetime (local). Blank -> None. Raises ValueError if malformed."""
    text = (text or "").strip()
    if not text:
        return None
    d = datetime.strptime(text, "%Y-%m-%d")
    return d.replace(hour=23, minute=59, second=59) if end_of_day else d


def describe_period(d_from, d_to):
    if d_from and d_to:
        return f"{d_from:%Y-%m-%d} to {d_to:%Y-%m-%d}"
    if d_from:
        return f"since {d_from:%Y-%m-%d}"
    if d_to:
        return f"until {d_to:%Y-%m-%d}"
    return "any date"


def classify(info, lo, hi):
    """Return (own_recent, content_recent, status). lo/hi are timestamps or None."""
    own_recent = (info.own_mtime is not None
                  and (lo is None or info.own_mtime >= lo)
                  and (hi is None or info.own_mtime <= hi))
    content_recent = info.range_files > 0
    if info.unreadable or (info.error and info.own_mtime is None
                           and info.newest_file_mtime is None):
        status = "Error"
    elif content_recent:
        status = "Active"
    elif info.total_files == 0:
        status = "Empty (no files)" + (" - folder touched recently" if own_recent else "")
    else:
        status = "Stale"
    return own_recent, content_recent, status


def fmt_ts(ts):
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else ""


def fmt_size(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def fmt_duration(sec):
    if sec is None:
        return "--:--:--"
    sec = int(round(sec))
    h, rem = divmod(sec, 3600)
    m, s_ = divmod(rem, 60)
    return f"{h}:{m:02d}:{s_:02d}"


def _round_est(n):
    """Round an estimate to 2 significant digits so it does not look more precise than it is."""
    n = int(n)
    if n < 100:
        return n
    mag = 10 ** (len(str(n)) - 2)
    return int(round(n / mag) * mag)


def pct_text(part, whole):
    if not whole:
        return "0%"
    f = part / whole
    if 0 < f < 0.005:
        return "<1%"
    return f"{f:.0%}"


class ProgressMeter:
    """Turns raw progress reports into percent, elapsed and time left (used by GUI and CLI)."""

    def __init__(self):
        self.t_start = time.monotonic()
        self.t_scan = None
        self._finish = None
        self.last = None

    def update(self, p):
        now = time.monotonic()
        self.last = p
        v = {"elapsed": now - self.t_start, "remaining": None, "fraction": None,
             "approx": True}
        if p["phase"] == "scan":
            if self.t_scan is None:
                self.t_scan = now - 0.25          # first report arrives ~0.25 s after start
            f = p["fraction"]
            v["fraction"] = f
            v["approx"] = not p["exact"]
            scan_el = now - self.t_scan
            if f >= 1.0:
                v["remaining"] = 0.0
            elif f >= (0.005 if p.get("has_totals") else 0.02) and scan_el >= 2.0:
                raw = now + scan_el * (1 - f) / f
                # smooth the predicted finish time so "time left" counts down steadily
                self._finish = raw if self._finish is None else 0.85 * self._finish + 0.15 * raw
                v["remaining"] = max(0.0, self._finish - now)
        return v


def progress_parts(p, v, sep):
    """Return (percent, counts, times) texts for one progress report."""
    if p["phase"] == "count":
        return ("counting",
                f"Counting first for exact progress: {p['folders']:,} folders{sep}"
                f"{p['files']:,} files found",
                f"elapsed {fmt_duration(v['elapsed'])}")
    f = v["fraction"]
    ap = "~" if v["approx"] else ""
    if f >= 1.0:
        pct = "100%"
    else:
        pct = f"{ap}{f * 100:.0f}%" if v["approx"] else f"{f * 100:.1f}%"
    if p.get("has_totals"):
        t = "" if p["exact"] else "~"
        counts = (f"folders {p['folders']:,} / {t}{p['total_folders']:,}{sep}"
                  f"files {p['files']:,} / {t}{p['total_files']:,}")
        if not p["exact"]:
            counts += f"{sep}totals from the last scan"
    elif 0.02 <= f < 1.0:
        counts = (f"folders {p['folders']:,} of ~{_round_est(p['folders'] / f):,}{sep}"
                  f"files {p['files']:,} of ~{_round_est(p['files'] / f):,}")
    else:
        counts = f"folders {p['folders']:,}{sep}files {p['files']:,}"
    counts += f"{sep}{fmt_size(p['bytes'])} read"
    if f >= 1.0:
        left = "done"
    elif v["remaining"] is None:
        left = "left: estimating..."
    else:
        left = f"left {ap}{fmt_duration(v['remaining'])}"
    return pct, counts, f"elapsed {fmt_duration(v['elapsed'])}{sep}{left}"


SUMMARY_NAMES = {GREEN: "USED (green)", RED: "NOT USED (red)", GRAY: "EMPTY / ERROR (gray)"}


def storage_breakdown(rows, folder_basis=False):
    """
    Split ALL scanned bytes between the three colors without double counting: every file is
    counted once, under the color of the folder that directly contains it.
    """
    out = {c: {"folders": 0, "files": 0, "bytes": 0} for c in (GREEN, RED, GRAY)}
    unreadable = 0
    for r in rows:
        c = color_of(r, folder_basis)
        i = r["info"]
        b = out[c]
        b["folders"] += 1
        b["files"] += i.direct_files
        b["bytes"] += i.direct_size
        if c == GRAY and (i.unreadable or r["status"] == "Error"):
            unreadable += 1
    out[GRAY]["unreadable"] = unreadable
    out[GRAY]["empty"] = out[GRAY]["folders"] - unreadable
    return out


def color_of(r, folder_basis=False):
    i = r["info"]
    if folder_basis:
        if i.own_mtime is None:
            return GRAY
        return GREEN if r["own_recent"] else RED
    if r["status"] == "Error" or i.total_files == 0:
        return GRAY
    return GREEN if r["content_recent"] else RED


def reason_for(r, folder_basis=False):
    """Return (label, [lines]) explaining why a folder has its color."""
    i, period, nsub = r["info"], r["period"], r["nsub"]
    color = color_of(r, folder_basis)
    lines = []
    if color == GRAY:
        if folder_basis:
            lines.append("The folder's own modified date could not be read, so it cannot be judged.")
        elif i.unreadable:
            lines.append("This folder could not be opened, so its contents are unknown "
                         "and nothing inside it was counted.")
        elif r["status"] == "Error":
            lines.append("Information about this folder could not be read, so it cannot be judged.")
        elif nsub == 0 and i.excluded_dirs == 0:
            lines.append("Empty folder: it contains no files and no sub-folders.")
        elif nsub == 0:
            lines.append(f"No files counted: its {i.excluded_dirs:,} sub-folder(s) were "
                         "excluded from the scan.")
        else:
            t = (f"No files anywhere inside: it only holds {nsub:,} sub-folder(s) and all of "
                 "them are empty or unreadable.")
            if i.excluded_dirs:
                t += f" ({i.excluded_dirs:,} more sub-folder(s) were excluded from the scan.)"
            lines.append(t)
    elif color == GREEN:
        if folder_basis:
            lines.append(f"The folder itself was modified {fmt_ts(i.own_mtime)}, which is inside the period ({period}).")
        else:
            lines.append(f"{i.range_files:,} of {i.total_files:,} file(s) inside were "
                         f"{r.get('activity', 'modified')} within the period ({period}), even if "
                         f"the folder's own date is older. Last file activity: "
                         f"{fmt_ts(i.newest_file_mtime)}.")
    else:
        if folder_basis:
            lines.append(f"The folder itself was last modified {fmt_ts(i.own_mtime)}, "
                         f"outside the period ({period}).")
        else:
            lines.append(f"None of the {i.total_files:,} file(s) inside were "
                         f"{r.get('activity', 'modified')} within the period ({period}). "
                         f"Last file activity: {fmt_ts(i.newest_file_mtime)}.")
            if r.get("activity", "modified") == "modified" and not CREATED_NATIVE:
                lines.append("Note: file creation dates are not checked on Linux, so files "
                             "copied in recently with an old modified date are not detected "
                             "(see the 'created' option).")
    if i.error:
        if not i.unreadable and color != GRAY:
            lines.append(f"Warning: {i.error_count:,} item(s) in this folder could not be read, "
                         "so its totals may be incomplete.")
        lines.extend(error_detail(i))
    if i.unreadable_below and not folder_basis:
        lines.append(f"Warning: {i.unreadable_below:,} sub-folder(s) below this one could not be "
                     "opened, so files inside them were NOT counted and this result may be "
                     "incomplete. Look for the gray folders underneath.")
    return COLOR_LABEL[color], lines


def csv_reason(r):
    label, lines = reason_for(r)
    return f"{label}: " + " | ".join(lines)


def reason_text(r, folder_basis=False, with_path=False):
    label, lines = reason_for(r, folder_basis)
    out = ([r["info"].path] if with_path else []) + [label] + ["- " + ln for ln in lines]
    return "\n".join(out)


FILE_PAGE = 1000                      # files shown per "Show more" in the window


def _in_period(ts, lo, hi):
    return ts is not None and (lo is None or ts >= lo) and (hi is None or ts <= hi)


def list_folder_files(path, lo, hi, created, activity, period, progress=None):
    """
    Reads the files directly in one folder, as they are on disk now.
    Returns (rows, error_text). Uses the same date rules as scan_tree and, like it,
    skips symbolic links. progress, if given, is called with no arguments after each entry
    is read (from the calling thread, so it must not touch Tk).
    """
    rows = []
    try:
        with os.scandir(path) as it:
            for entry in it:
                if progress is not None:
                    progress()
                row = {"path": entry.path, "name": entry.name, "size": None, "mtime": None,
                       "created": None, "color": GRAY, "reason": ""}
                try:
                    if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
                        continue
                    st = entry.stat(follow_symlinks=False)
                except OSError as e:
                    why = explain_os_error(e.errno, getattr(e, "winerror", None))
                    row["reason"] = ("This file could not be read, so it cannot be judged. "
                                     + (why or (e.strerror or str(e))))
                    rows.append(row)
                    continue
                c = file_created(st, created)
                row.update(size=st.st_size, mtime=st.st_mtime, created=c)
                dates = f"Modified {fmt_ts(st.st_mtime)}"
                if c is not None:
                    dates += f", created {fmt_ts(c)}"
                if _in_period(st.st_mtime, lo, hi) or _in_period(c, lo, hi):
                    row["color"] = GREEN
                    row["reason"] = f"This file was {activity} within the period ({period}). {dates}."
                else:
                    row["color"] = RED
                    row["reason"] = f"This file was {activity} outside the period ({period}). {dates}."
                rows.append(row)
    except OSError as e:
        why = explain_os_error(e.errno, getattr(e, "winerror", None))
        return [], "The files in this folder could not be listed. " + (why or (e.strerror or str(e)))
    return rows, ""


def _file_activity(row):
    return max(row["mtime"] or 0, row["created"] or 0)


def sort_file_rows(rows, label):
    if label.startswith("Size"):
        return sorted(rows, key=lambda r: -(r["size"] or 0))
    if label.startswith("Name"):
        return sorted(rows, key=lambda r: r["name"].lower())
    if "oldest" in label:
        return sorted(rows, key=_file_activity)
    return sorted(rows, key=lambda r: -_file_activity(r))


def filter_file_rows(rows, label):
    if label == "All":
        return list(rows)
    want = RED if label.startswith("Red") else GRAY if label.startswith("Gray") else GREEN
    return [r for r in rows if r["color"] == want]


CSV_HEADERS = [
    "Folder path", "Depth", "Folder modified", "Folder modified in period?",
    "Last file activity, modified or created (recursive)",
    "Any file modified/created in period?",
    "Status", "Files (direct)", "Files (recursive)",
    "Files modified/created in period (recursive)",
    "Size bytes (recursive)", "Error", "Reason",
]


def build_rows(folders, d_from, d_to, activity="modified"):
    lo = d_from.timestamp() if d_from else None
    hi = d_to.timestamp() if d_to else None
    period = describe_period(d_from, d_to)
    nsub = {}
    for f in folders.values():
        if f.parent is not None:
            nsub[f.parent] = nsub.get(f.parent, 0) + 1
    rows = []
    for info in sorted(folders.values(), key=lambda f: f.path.lower()):
        own_recent, content_recent, status = classify(info, lo, hi)
        rows.append({
            "info": info,
            "own_recent": own_recent,
            "content_recent": content_recent,
            "status": status,
            "nsub": nsub.get(info.path, 0),
            "period": period,
            "activity": activity,
        })
    return rows


def row_to_csv(r):
    i = r["info"]
    return [
        i.path, i.depth, fmt_ts(i.own_mtime), "Yes" if r["own_recent"] else "No",
        fmt_ts(i.newest_file_mtime), "Yes" if r["content_recent"] else "No",
        r["status"], i.direct_files, i.total_files, i.range_files, i.total_size, i.error,
        csv_reason(r),
    ]


def write_csv(path, rows):
    # utf-8-sig so Excel opens non-ASCII folder names correctly
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(CSV_HEADERS)
        for r in rows:
            w.writerow(row_to_csv(r))


# --------------------------------------------------------------------------
# GUI
# --------------------------------------------------------------------------

BG = {GREEN: "#c9eccf", RED: "#f6c4c4", GRAY: "#e6e6e6"}
DUMMY = "::__placeholder__"
def file_manager_command(path, is_file, platform):
    """Command that shows path in the file manager. A file is only revealed, never run.
    An argv list, except a Windows file: one prebuilt string, because list quoting would wrap
    the whole /select switch in quotes and Explorer would ignore it (run without a shell).
    None means: use os.startfile (a folder on Windows)."""
    if platform.startswith("win"):
        return f'explorer /select,"{path}"' if is_file else None
    if platform == "darwin":
        return ["open", "-R", path] if is_file else ["open", path]
    return ["xdg-open", os.path.dirname(path) if is_file else path]


LISTING_TIMEOUT = 30                  # seconds before a silent folder listing is abandoned
MAX_ABANDONED = 16                    # abandoned listing threads allowed to pile up
FILE_THREADS = 4                      # file listings read at the same time
FILE_IID, MORE_IID, FILEERR_IID = "file::", "more::", "fileerr::"


# ---- background scans (Windows): a one-time scheduled task that outlives the RDP session
JOBS_DIR = os.path.join(os.path.expanduser("~"), ".treerot", "jobs")
TASK_NS = "http://schemas.microsoft.com/windows/2004/02/mit/task"
TASK_PREFIX = "TreeRot-"                # every task this program creates, and only those; flat,
                                        # as a standard user may not be able to create a task folder
STATUS_SUFFIX = ".status.json"          # a job's status file is its report's name plus this
STARTING_GRACE_SECONDS = 300            # no status after this long: the task did not get going
SCHTASKS_TIMEOUT = 60                   # seconds; schtasks answers at once when it answers at all
JOBS_REFRESH_MS = 5000                  # how often the open panel looks at the scans again
JOB_LIVE = ("starting", "silent", "running", "stalled")     # may still have a process to end
CREATING_LIMIT_SECONDS = 900            # a password prompt older than this was left or abandoned
JOB_LABELS = {"creating": "Password", "starting": "Starting", "silent": "Not started", "running": "Running",
              "stalled": "Stopped?", "ended": "Ended", "finished": "Finished", "failed": "Failed"}
_JOB_ID = re.compile(r"\d{8}-\d{6}-[0-9a-f]{4}\Z")
# What XML 1.0 can carry, without line breaks: the task's command line has no way to hold them.
_NOT_TASK_TEXT = re.compile("[^\t\x20-\ud7ff\ue000-\ufffd\U00010000-\U0010ffff]")


# Task Scheduler may expand these in a command line, which would silently change the value.
_CMD_SPECIAL = re.compile('["%&^|<>\x00-\x1f]')    # what cmd.exe could read as something else
_TASK_EXPANDS = re.compile(r"%[^%]+%|\$\([^)]*\)")


class BackgroundError(Exception):
    pass


def background_available():
    return sys.platform == "win32"


def is_mapped_drive(path, drive_type=None):
    """True for a drive letter that points at a network share. Those don't exist in a background task."""
    if path[:4] in ("\\\\?\\", "\\\\.\\"):
        path = path[4:]
    if len(path) < 2 or path[1] != ":" or not path[0].isalpha():
        return False
    if drive_type is None:
        if sys.platform != "win32":
            return False
        import ctypes
        drive_type = ctypes.windll.kernel32.GetDriveTypeW
    return drive_type(path[0].upper() + ":\\") == 4          # DRIVE_REMOTE


def check_background_folder(root):
    """Why this folder can't be scanned in the background, or None. May be slow: not on the Tk thread."""
    root = _full_path(root)              # "data" or "\\data" may be on a mapped current drive
    if is_mapped_drive(root):
        return ("Mapped drive letters do not exist in a background task. Enter the full network "
                "path instead, for example \\\\server\\share.")
    if not os.path.isdir(root):
        return "That folder does not exist or is not reachable."
    return None


def _full_path(path):
    """A task does not start in this program's folder, so every path in it must be a full one."""
    if path.startswith("\\\\"):
        return path
    if re.match(r"[A-Za-z]:[\\/]", path):
        return ntpath.normpath(path)
    return os.path.abspath(path)


def _is_report_name(path):
    return os.path.splitext(path)[1].lower() in (".html", ".pdf")


def _same_path(a, b):
    return os.path.normcase(_full_path(a)) == os.path.normcase(_full_path(b))


def background_args(date_from, date_to, excludes, created=True, follow_symlinks=False, precount=False):
    """The scan settings as command-line arguments. --exclude=VALUE is one argument, so an
    exclusion that starts with a dash is still an exclusion, not an unknown option."""
    args = ["--format", "summary", "-q"]
    if date_from:
        args += ["--from", date_from]
    if date_to:
        args += ["--to", date_to]
    args += ["--exclude=" + ex for ex in excludes]
    if not created:
        args += ["--created", "off"]
    if follow_symlinks:
        args.append("--follow-symlinks")
    if precount:
        args.append("--precount")
    return args


def background_command(root, args, status_file):
    """The program and arguments to run the shell version: the sibling CLI exe, or this script."""
    if getattr(sys, "frozen", False):
        exe = os.path.join(os.path.dirname(sys.executable), "TreeRot-cli.exe")
        if not os.path.isfile(exe):
            raise BackgroundError(f"TreeRot-cli.exe must be in the same folder as TreeRot.exe ({exe}).")
        prefix = []
    else:
        exe, prefix = sys.executable, [os.path.abspath(__file__)]
        if not exe or not os.path.isfile(exe):
            raise BackgroundError("Could not find the Python program that is running TreeRot, "
                                  "so a background task could not be set up.")
    return exe, prefix + [root] + list(args) + ["--progress", "none", "--status-file", status_file]


def build_task_xml(exe, arguments, user, logon_type="Password"):
    """The task definition. It has no trigger on purpose: /Run starts it on demand, so no start
    time can pass while the user types the password, and a quick scan is never run a second
    time by a trigger that comes due after it ended."""
    import xml.etree.ElementTree as ET

    for value in [exe, user] + list(arguments):
        if _NOT_TASK_TEXT.search(value):
            raise BackgroundError(f"A background task cannot carry this text: {ascii(value)}")
    line = subprocess.list2cmdline(arguments)
    for text in (exe, line):
        found = _TASK_EXPANDS.search(text)
        if found:
            raise BackgroundError(
                f"A background task cannot carry {found.group()} in a path or exclusion: Windows "
                "could replace it with something else before the scan sees it. Rename it or "
                "leave it out, or run the scan in this window.")

    def add(parent, tag, text=None, **attrs):
        node = ET.SubElement(parent, tag, attrs)
        node.text = text
        return node
    task = ET.Element("Task", {"version": "1.2", "xmlns": TASK_NS})
    info = add(task, "RegistrationInfo")
    add(info, "Description", f"{APP_NAME} background scan")
    who = add(add(task, "Principals"), "Principal", id="Author")
    add(who, "UserId", user)
    add(who, "LogonType", logon_type)
    add(who, "RunLevel", "LeastPrivilege")
    settings = add(task, "Settings")
    for tag, text in (("MultipleInstancesPolicy", "IgnoreNew"),
                      ("DisallowStartIfOnBatteries", "false"),
                      ("StopIfGoingOnBatteries", "false"),
                      ("AllowStartOnDemand", "true"),
                      ("Enabled", "true"),
                      ("ExecutionTimeLimit", "PT0S"),
                      ("Priority", "7")):
        add(settings, tag, text)
    run = add(add(task, "Actions", Context="Author"), "Exec")
    add(run, "Command", exe)
    add(run, "Arguments", line)
    return '<?xml version="1.0" encoding="UTF-16"?>\n' + ET.tostring(task, encoding="unicode")


def write_task_xml(path, xml_text):
    with open(path, "w", encoding="utf-16") as f:
        f.write(xml_text)


def schtasks_exe(platform=None, environ=None):
    """schtasks by its full path on Windows: the name alone would also find a schtasks.exe in the
    current folder, and that program would be the one asking for the password."""
    if (platform or sys.platform) != "win32":
        return "schtasks"
    env = os.environ if environ is None else environ
    return ntpath.join(env.get("SystemRoot") or "C:\\Windows", "System32", "schtasks.exe")


def cmd_exe(platform=None, environ=None):
    if (platform or sys.platform) != "win32":
        return "cmd.exe"
    env = os.environ if environ is None else environ
    return ntpath.join(env.get("SystemRoot") or "C:\\Windows", "System32", "cmd.exe")


def task_create_command(task, xml_name, user, platform=None, environ=None):
    """The line that creates the task, as one exact string. cmd.exe is there for one thing: if
    schtasks fails, Windows' own message stays on screen until a key is pressed. Nothing can be
    captured instead: any redirect makes the console prompt vanish under a windowed TreeRot.exe.
    cmd reads every character here, so only names it cannot misread go on the line; the XML
    file is found through the working folder, not by its path."""
    if _CMD_SPECIAL.search(user):
        raise BackgroundError(
            f"Your Windows user name ({user}) has a character that cannot be passed safely to "
            "Windows' password prompt. The README shows how to set this up by hand.")
    shell, exe = cmd_exe(platform, environ), schtasks_exe(platform, environ)
    if _CMD_SPECIAL.search(shell + exe + task + xml_name):
        raise BackgroundError(f"The Windows folder or task name cannot be passed safely: {shell}")
    return (f'"{shell}" /d /c ""{exe}" /Create /TN {task} /XML {xml_name} /RU "{user}" /RP * '
            '|| (pause & exit /b 1)"')


def windows_user():
    env = os.environ
    user = env.get("USERNAME", "")
    if not user:
        raise BackgroundError("Could not tell which Windows user you are (USERNAME is not set).")
    return f"{env['USERDOMAIN']}\\{user}" if env.get("USERDOMAIN") else user


def _only_on_windows():
    if sys.platform != "win32":
        raise BackgroundError("Background scans need Windows Task Scheduler.")


def _console_run(command, cwd):
    """Runs the line from task_create_command in its own visible console so Windows itself can
    ask for the password. Nothing is redirected: the prompt must reach the screen and the typing
    must reach schtasks, never this program."""
    _only_on_windows()
    return subprocess.run(command, cwd=cwd, creationflags=0x00000010)     # CREATE_NEW_CONSOLE


def _quiet_run(cmd):
    _only_on_windows()
    try:
        return subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True,
                              timeout=SCHTASKS_TIMEOUT, creationflags=0x08000000)  # CREATE_NO_WINDOW
    except subprocess.TimeoutExpired:      # no answer is not an answer: never a return code
        raise BackgroundError("Windows Task Scheduler did not answer. Try again in a moment.")


def _windows_text(res):
    """What schtasks printed, if it was captured. It writes in the console's code page."""
    out = getattr(res, "stderr", b"") or getattr(res, "stdout", b"") or b""
    try:
        return out.decode("oem", "replace").strip()
    except LookupError:                 # there is no such codec outside Windows
        return out.decode("utf-8", "replace").strip()


def _job_path(job_id):
    return os.path.join(JOBS_DIR, job_id + ".json")


def _save_job(job):
    """Replaces the record whole, so the panel never reads half of one."""
    path = _job_path(job["id"])
    tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(job, f)
        os.replace(tmp, path)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _forget_job(job_id):
    try:
        os.remove(_job_path(job_id))
    except FileNotFoundError:
        pass


def _still_creating(job):
    started = job.get("started")
    return (bool(job.get("creating")) and isinstance(started, (int, float))
            and time.time() - started < CREATING_LIMIT_SECONDS)


def _names_our_task(job):
    """A task name is ours only if it is exactly the name this program gives that job id."""
    job_id = job.get("id")
    return (isinstance(job_id, str) and _JOB_ID.match(job_id) is not None
            and job.get("task") == TASK_PREFIX + job_id)


def _own_record(job):
    """The record on disk for a job, proving the task is one this program created. Nothing is
    ever done to a task without it."""
    if _names_our_task(job):
        try:
            with open(_job_path(job["id"]), encoding="utf-8") as f:
                record = json.load(f)
        except (OSError, ValueError):
            record = None
        if isinstance(record, dict) and _names_our_task(record) and record["task"] == job["task"]:
            return record
    raise BackgroundError("This is not a task TreeRot has a record of, so it was left alone.")


def _delete_task(task, run):
    """Deletes the task, or raises unless it is certainly gone. schtasks gives the same exit code
    and a translated message for "not found" and for any other trouble, so "gone" means only
    this: Windows listed its tasks, and this one is not among them. On any doubt the record
    stays, or a task holding a stored password would be left with nothing pointing at it."""
    exe = schtasks_exe()
    res = run([exe, "/Delete", "/TN", task, "/F"])
    if res.returncode == 0:
        return
    tasks = run([exe, "/Query", "/FO", "CSV", "/NH"])
    if tasks.returncode != 0 or tasks.stdout is None or task.encode("ascii") in tasks.stdout:
        raise BackgroundError(f"Windows would not delete the background task. {_windows_text(res)}".strip())


def _refuse_if_in_use(status_file):
    """Another scan that may still be alive could write the same report."""
    for other in load_jobs():
        if _same_path(other["status_file"], status_file) and job_state(other)[0] in JOB_LIVE + ("creating",):
            raise BackgroundError(
                "Another background scan is writing this report. End it or choose another "
                "file. Background scans shows it.")


def _clear_the_way(status_file, job_id, runner):
    """Called once the new task exists and before anything starts it: it has no trigger, so
    only /Run can. A status file left at this path could pass for this run's result (a scan
    stopped by bad arguments never writes one), so it goes first or nothing starts. Waiting
    until now means canceling the password prompt loses nothing from the earlier scan."""
    for other in load_jobs():
        if other["id"] != job_id and _same_path(other["status_file"], status_file):
            remove_job(other, runner=runner)    # its report is about to be replaced
    try:
        os.remove(status_file)
    except FileNotFoundError:
        pass
    except OSError as e:
        raise BackgroundError(f"The old status file {status_file} could not be removed, so its "
                              f"result could be mistaken for this scan's. {e}")


def _take_back(job, run, why):
    """The task exists but must not stay. Returns the error to show."""
    try:
        _delete_task(job["task"], run)
        _forget_job(job["id"])
        return why
    except (BackgroundError, OSError) as e:
        job.pop("creating", None)
        try:
            _save_job(job)               # no longer waiting for the prompt: Remove must work
        except OSError:
            pass
        return BackgroundError(f"{why} The task could not be removed either ({e}). "
                               "Remove it under Background scans.")


def start_background_scan(root, args, report, runner=None):
    """
    Creates and starts a Windows scheduled task for the scan. Windows' console prompt collects
    the password (/RP *), so this program never sees it. Returns the job record.
    Slow on a slow share and waits for the user: never call it on the Tk thread.
    """
    root, report = _full_path(root), _full_path(report)   # a short path can hide a mapped drive
    if is_mapped_drive(root):
        raise BackgroundError("Mapped drive letters do not exist in a background task. Enter the "
                              "folder's full network path instead, for example \\\\server\\share.")
    if is_mapped_drive(report):
        raise BackgroundError("Mapped drive letters do not exist in a background task. Save the "
                              "report by its full network path instead, for example "
                              "\\\\server\\share\\report.html.")
    if not _is_report_name(report):
        raise BackgroundError("A background scan's report must be a .html or .pdf file.")
    if not os.path.isdir(os.path.dirname(report)):
        raise BackgroundError(f"The report's folder does not exist or is not reachable: {report}")
    status_file = report + STATUS_SUFFIX
    user = windows_user()
    exe, arguments = background_command(root, list(args) + ["--report", report], status_file)
    xml_text = build_task_xml(exe, arguments, user)
    _refuse_if_in_use(status_file)

    job_id = f"{datetime.now():%Y%m%d-%H%M%S}-{os.urandom(2).hex()}"
    task = TASK_PREFIX + job_id
    xml_name = job_id + ".xml"
    command = task_create_command(task, xml_name, user)
    if _full_path(JOBS_DIR).startswith("\\\\"):
        raise BackgroundError(f"Background scans cannot keep their files on a network path "
                              f"({JOBS_DIR}): the password window would not find them.")
    job = {"id": job_id, "task": task, "root": root, "report": report, "status_file": status_file,
           "started": time.time(), "creating": True}
    os.makedirs(JOBS_DIR, exist_ok=True)
    _save_job(job)                       # first, so no task ever exists without a record
    create = runner or _console_run
    run = runner or _quiet_run
    xml_path = os.path.join(JOBS_DIR, xml_name)
    try:
        write_task_xml(xml_path, xml_text)
        res = create(command, cwd=JOBS_DIR)
        if res.returncode != 0:
            raise BackgroundError(
                "The background task could not be created. The reason is in the console window "
                "that asked for your password. The README shows how to set this up by hand.")
    except Exception:
        _forget_job(job_id)
        raise
    finally:
        try:
            os.remove(xml_path)
        except OSError:
            pass
    try:
        _clear_the_way(status_file, job_id, runner)
        del job["creating"]
        _save_job(job)
        res = run([schtasks_exe(), "/Run", "/TN", task])
        if res.returncode != 0:
            raise BackgroundError("The background task was created but could not be started. "
                                  + _windows_text(res))
    except (BackgroundError, OSError) as e:
        raise _take_back(job, run, e)
    return job


def load_jobs():
    """The saved job records. A file that is not exactly a record of ours is skipped: a record
    says which file the panel will open, so its report must be a report."""
    jobs = []
    try:
        names = sorted(os.listdir(JOBS_DIR))
    except OSError:
        return jobs
    for n in names:
        if n.endswith(".json"):
            try:
                with open(os.path.join(JOBS_DIR, n), encoding="utf-8") as f:
                    job = json.load(f)
            except (OSError, ValueError):
                continue
            if (isinstance(job, dict) and _names_our_task(job) and n == job["id"] + ".json"
                    and all(isinstance(job.get(k), str) for k in ("root", "report", "status_file"))
                    and _is_report_name(job["report"])
                    and job["status_file"] == job["report"] + STATUS_SUFFIX):
                jobs.append(job)
    return jobs


def _report_in(status, job):
    """The report of a finished scan, if it is there. The status file sits next to the report,
    often on a share others can write to, so it may only confirm the path this job recorded:
    what it names gets opened."""
    if status is None or status["state"] != "finished":
        return None
    path = status.get("report")
    if not isinstance(path, str) or not path or not _same_path(path, job["report"]):
        return None
    return path if os.path.isfile(path) else None


def job_row(job):
    """(state, text for the panel, report path or None), from one read of the status file.
    state: creating | starting | silent | running | stalled | ended | finished | failed.
    Reads the status file, maybe on a dead share: never call it on the Tk thread."""
    if job.get("creating"):              # any status file there is still an earlier scan's
        if _still_creating(job):
            return "creating", "Waiting for your password in the console window.", None
        return ("silent", "The password window was not answered, or TreeRot was closed "
                          "while it was open.", None)
    s = read_status(job["status_file"])
    if s is not None and s["state"] == "finished":
        report = _report_in(s, job)
        if report:
            return "finished", f"Finished. Report: {report}", report
        return "finished", "Finished, but the report file was not found.", None
    if s is not None and s["state"] == "failed":
        return "failed", str(s.get("error") or "The scan failed."), None
    if job.get("ended"):
        return "ended", "You ended this scan.", None
    if s is None:
        started = job.get("started")
        if isinstance(started, (int, float)) and time.time() - started > STARTING_GRACE_SECONDS:
            return ("silent", "The scan did not start, or failed before it could write its status. "
                              "The report's folder may also be out of reach.", None)
        return ("starting", "Waiting for the task to start. If this stays, it failed before it "
                            "could write its status.", None)
    if status_is_stale(s):
        return ("stalled", "The scan seems to have stopped: no news for over "
                           f"{STATUS_STALE_SECONDS // 60} minutes. The computer may have restarted, "
                           "or the share may have stopped answering.", None)
    parts = (s.get("percent"), s.get("counts"), s.get("times"))
    return "running", "  ".join(str(x) for x in parts if x) or "Running.", None


def job_state(job):
    """Returns (state, text for the panel). See job_row."""
    return job_row(job)[:2]


def job_report(job):
    """The report to open: only for a finished scan, and only if the file exists."""
    return _report_in(read_status(job["status_file"]), job)


def end_job(job, runner=None):
    """Stops the scan by ending its task. The record stays so the panel can say what happened."""
    record = _own_record(job)
    if record.get("task_removed"):
        return
    res = (runner or _quiet_run)([schtasks_exe(), "/End", "/TN", record["task"]])
    if res.returncode != 0:
        raise BackgroundError(f"The background task could not be ended. {_windows_text(res)}".strip())
    record["ended"] = True
    _save_job(record)


def remove_job(job, runner=None):
    """Deletes the scheduled task and the job record. The report and its status stay."""
    record = _own_record(job)
    if not record.get("task_removed"):
        _delete_task(record["task"], runner or _quiet_run)
    _forget_job(record["id"])


def clean_finished_jobs(runner=None):
    """
    Tasks that are over are deleted on the next launch, which also drops the password Windows
    stored for them. The job record stays until the user presses Remove, so someone who logged
    off still sees the result and can open the report.
    Slow work: never call it on the Tk thread.
    """
    for job in load_jobs():
        if job.get("task_removed") or job_state(job)[0] not in ("finished", "failed", "ended"):
            continue
        try:
            _delete_task(job["task"], runner or _quiet_run)
            job["task_removed"] = True
            if os.path.isfile(_job_path(job["id"])):     # not if Remove came first
                _save_job(job)
        except (BackgroundError, OSError):
            pass                         # still there: the next launch tries again


def gui_unavailable(reason):
    sys.stderr.write(
        f"Cannot open the graphical interface: {reason}\n\n"
        "To run without a GUI (servers, SSH, cron), give a folder path, for example:\n"
        "    python treerot.py /srv/share --format tree\n"
        "Run with --help to see all options.\n")
    sys.exit(3)


def run_gui(preload=None, on_ready=None):
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk
    except ImportError as e:
        gui_unavailable(f"tkinter is not installed ({e}). Linux: install python3-tk. "
                        "macOS with Homebrew: brew install python-tk.")

    class App(tk.Tk):
        def __init__(self):
            super().__init__()
            self.title(f"{APP_NAME} {__version__}")
            try:                                   # Tk before 8.6 cannot read PNG; the window then has no icon
                self.iconphoto(True, tk.PhotoImage(data=ICON_PNG_B64))
            except tk.TclError:
                pass
            self.geometry("1250x720")
            self.minsize(950, 480)

            self.rows = []
            self.by_path = {}
            self.child_rows = {}
            self.root_path = None
            self.visible = None       # None = everything visible
            self.matching = []
            self.q = queue.Queue()
            self.cancel_event = threading.Event()
            self.awake_note = ""
            self.report_cancel = threading.Event()   # a PDF export has its own flag
            self._report_thread = None
            self.period_text = ""
            self.file_rows = {}       # tree iid -> file row
            self.file_cache = {}      # folder path -> (sorted and filtered rows, number shown)
            self.file_loading = set()
            self.file_gen = 0         # results from an older tree are ignored
            self.file_queue = []      # folders waiting for one of the listing slots
            self.file_active = 0      # responsive listings running (at most FILE_THREADS)
            self.file_token = 0
            self._press_row = None    # row under the mouse button when it went down
            self.file_live = {}       # token -> (generation, folder) of a listing holding a slot
            self.file_abandoned = set()   # tokens of listings that timed out, thread still blocked
            self.scan_ctx = None      # dates and rules of the scan, for listing files live
            self.n_excluded = 0
            self.scan_elapsed = None
            self.meter = None
            self.settings = load_settings()
            self._bg_token = 0        # the newest "Run in background" press; older checks are ignored
            self._bg_starting = False # a task is being created (the password prompt may be open)
            self._jobs_ui = None      # the Background scans panel, while it is open
            self._jobs_gen = 0

            self._build_ui()
            self.path_var.set(self.settings.get("path", ""))
            self._quick_period("Last 2 years")
            for ex in self.settings.get("excludes", []):
                self.ex_list.insert("end", ex)
            self.protocol("WM_DELETE_WINDOW", self._on_close)
            self._clear_summary()
            self._poll_job = self.after(100, self._poll)
            if background_available():
                self._clean_finished_jobs()

        # ---- UI construction
        def _build_ui(self):
            top = ttk.Frame(self, padding=8)
            top.pack(fill="x")

            ttk.Label(top, text="Folder / share:").grid(row=0, column=0, sticky="w")
            self.path_var = tk.StringVar()
            ttk.Entry(top, textvariable=self.path_var).grid(
                row=0, column=1, sticky="ew", padx=6)
            ttk.Button(top, text="Browse...", command=self._browse).grid(row=0, column=2)

            ttk.Label(top, text="Period:").grid(row=1, column=0, sticky="w", pady=(6, 0))
            opts = ttk.Frame(top)
            opts.grid(row=1, column=1, columnspan=2, sticky="w", pady=(6, 0), padx=6)
            self.from_var = tk.StringVar()
            self.to_var = tk.StringVar()
            ttk.Label(opts, text="From").pack(side="left")
            ttk.Entry(opts, textvariable=self.from_var, width=11).pack(side="left", padx=(4, 0))
            ttk.Button(opts, text="Pick", width=5,
                       command=lambda: self._pick_date(self.from_var)).pack(side="left", padx=(2, 12))
            ttk.Label(opts, text="To (optional)").pack(side="left")
            ttk.Entry(opts, textvariable=self.to_var, width=11).pack(side="left", padx=(4, 0))
            ttk.Button(opts, text="Pick", width=5,
                       command=lambda: self._pick_date(self.to_var)).pack(side="left", padx=(2, 12))
            ttk.Label(opts, text="Quick set:").pack(side="left")
            qs = ttk.Combobox(opts, state="readonly", width=13, values=[
                "Last 1 year", "Last 2 years", "Last 3 years", "Last 5 years", "Last 10 years"])
            qs.pack(side="left", padx=4)
            qs.bind("<<ComboboxSelected>>", lambda e: self._quick_period(qs.get()))
            self.symlink_var = tk.BooleanVar(value=False)
            ttk.Checkbutton(opts, text="Follow symlinks (risk of loops)",
                            variable=self.symlink_var).pack(side="left", padx=16)
            ttk.Label(top, foreground="#666666",
                      text="YYYY-MM-DD; leave 'To' empty for no end date. Green = a file inside "
                           "was modified or created in the period, even if the folder wasn't touched."
                      ).grid(row=2, column=1, columnspan=2, sticky="w", padx=6)
            self.created_var = tk.BooleanVar(
                value=bool(self.settings.get("count_created", CREATED_NATIVE)))
            ttk.Checkbutton(
                top, variable=self.created_var,
                text=("Files CREATED in the period count too (catches files copied in with "
                      "an old modified date)" if CREATED_NATIVE else
                      "Files CREATED in the period count too (Linux: uses change time, which "
                      "renames and permission changes also update)")
                ).grid(row=3, column=1, columnspan=2, sticky="w", padx=6, pady=(2, 0))
            top.columnconfigure(1, weight=1)

            exf = ttk.LabelFrame(
                self, text="Exclude folders (skipped during the scan, not counted anywhere)",
                padding=6)
            exf.pack(fill="x", padx=8, pady=(4, 6))
            lb_frame = ttk.Frame(exf)
            lb_frame.pack(side="left", fill="x", expand=True)
            self.ex_list = tk.Listbox(lb_frame, height=3, selectmode="extended",
                                      activestyle="none")
            ex_sb = ttk.Scrollbar(lb_frame, orient="vertical", command=self.ex_list.yview)
            self.ex_list.configure(yscrollcommand=ex_sb.set)
            self.ex_list.pack(side="left", fill="x", expand=True)
            ex_sb.pack(side="left", fill="y")
            exb = ttk.Frame(exf)
            exb.pack(side="left", padx=(8, 0))
            ttk.Button(exb, text="Add folder...", command=self._ex_add_folder
                       ).grid(row=0, column=0, sticky="ew", padx=2, pady=1)
            ttk.Button(exb, text="Add name / pattern...", command=self._ex_add_pattern
                       ).grid(row=0, column=1, sticky="ew", padx=2, pady=1)
            ttk.Button(exb, text="Add common system folders", command=self._ex_add_common
                       ).grid(row=1, column=0, sticky="ew", padx=2, pady=1)
            ttk.Button(exb, text="Remove selected", command=self._ex_remove
                       ).grid(row=1, column=1, sticky="ew", padx=2, pady=1)

            button_row = ttk.Frame(self, padding=(8, 0))
            button_row.pack(fill="x")
            self.scan_btn = ttk.Button(button_row, text="Scan", command=self._start)
            self.scan_btn.pack(side="left")
            self.cancel_btn = ttk.Button(button_row, text="Cancel", command=self._cancel,
                                         state="disabled")
            self.cancel_btn.pack(side="left", padx=6)
            self.export_btn = ttk.Button(button_row, text="Export CSV...",
                                         command=self._export, state="disabled")
            self.export_btn.pack(side="left")
            self.report_btn = ttk.Button(button_row, text="Export report...",
                                         command=self._export_report, state="disabled")
            self.report_btn.pack(side="left", padx=(6, 0))
            self.bg_btn = self.jobs_btn = None
            if background_available():
                self.bg_btn = ttk.Button(button_row, text="Run in background...",
                                         command=self._run_background)
                self.bg_btn.pack(side="left", padx=(6, 0))
                self.jobs_btn = ttk.Button(button_row, text="Background scans",
                                           command=self._jobs_panel)
                self.jobs_btn.pack(side="left", padx=(6, 0))
            self.precount_var = tk.BooleanVar(value=bool(self.settings.get("precount", False)))
            ttk.Checkbutton(button_row, text="Count first (exact progress, slower)",
                            variable=self.precount_var).pack(side="left", padx=(14, 0))
            ttk.Button(button_row, text="About", command=self._about).pack(side="left", padx=(14, 0))

            # legend
            leg = ttk.Frame(button_row)
            leg.pack(side="right")
            for txt, col in (("Used in period", GREEN), ("NOT used", RED),
                             ("Empty / error", GRAY)):
                tk.Label(leg, text=f"  {txt}  ", bg=BG[col], relief="solid", bd=1
                         ).pack(side="left", padx=3)

            prog = ttk.Frame(self, padding=(8, 6, 8, 0))
            prog.pack(fill="x")
            self.prog_bar = ttk.Progressbar(prog, mode="determinate", maximum=100)
            self.prog_bar.grid(row=0, column=0, sticky="ew")
            self.prog_pct_var = tk.StringVar(value="")
            ttk.Label(prog, textvariable=self.prog_pct_var, width=9, anchor="e",
                      font=("TkDefaultFont", 10, "bold")).grid(row=0, column=1, padx=(8, 0))
            self.prog_var = tk.StringVar(value="Ready.")
            ttk.Label(prog, textvariable=self.prog_var, anchor="w").grid(
                row=1, column=0, columnspan=2, sticky="ew", pady=(2, 0))
            prog.columnconfigure(0, weight=1)

            opt2 = ttk.Frame(self, padding=(8, 6, 8, 0))
            opt2.pack(fill="x")
            ttk.Label(opt2, text="Color by:").pack(side="left")
            self.basis_var = tk.StringVar(value="Files inside (recursive)")
            cb = ttk.Combobox(opt2, textvariable=self.basis_var, state="readonly", width=34,
                              values=["Files inside (recursive)",
                                      "Folder's own date only (ignores files)"])
            cb.pack(side="left", padx=(4, 14))
            cb.bind("<<ComboboxSelected>>", lambda e: self._refresh_tree())

            ttk.Label(opt2, text="Show:").pack(side="left")
            self.filter_var = tk.StringVar(value="All")
            cb = ttk.Combobox(opt2, textvariable=self.filter_var, state="readonly", width=22,
                              values=["All", "Red only (not used)", "Green only (used)",
                                      "Gray only (empty / error)"])
            cb.pack(side="left", padx=(4, 14))
            cb.bind("<<ComboboxSelected>>", lambda e: self._refresh_tree())

            ttk.Label(opt2, text="Sort siblings by:").pack(side="left")
            self.sort_var = tk.StringVar(value="Size (largest first)")
            cb = ttk.Combobox(opt2, textvariable=self.sort_var, state="readonly", width=24,
                              values=["Size (largest first)", "Name (A-Z)",
                                      "Last file activity (oldest first)",
                                      "Last file activity (newest first)"])
            cb.pack(side="left", padx=4)
            cb.bind("<<ComboboxSelected>>", lambda e: self._refresh_tree())

            opt3 = ttk.Frame(self, padding=(8, 6, 8, 0))
            opt3.pack(fill="x")
            ttk.Button(opt3, text="Expand to unused (red)",
                       command=self._expand_to_red).pack(side="left")
            ttk.Button(opt3, text="Expand all", command=self._expand_all
                       ).pack(side="left", padx=6)
            ttk.Button(opt3, text="Collapse all", command=self._collapse_all
                       ).pack(side="left")
            ttk.Label(opt3, text="Show levels:").pack(side="left", padx=(14, 4))
            self.levels_var = tk.StringVar(value="")
            self.levels_cb = ttk.Combobox(opt3, textvariable=self.levels_var, state="readonly",
                                          width=10, values=["1", "2", "3", "4", "5", "Unlimited"])
            self.levels_cb.pack(side="left")
            self.levels_cb.bind("<<ComboboxSelected>>",
                                lambda e: self._show_levels(self.levels_var.get()))

            sum_frame = ttk.Frame(self, padding=(8, 8, 8, 4))
            sum_frame.pack(fill="x")
            boxes = ttk.Frame(sum_frame)
            boxes.pack(fill="x")
            self.sum_boxes = {}
            for col in (GREEN, RED, GRAY):
                lbl = tk.Label(boxes, text="", bg=BG[col], fg="black", relief="solid", bd=1,
                               anchor="w", justify="left", padx=8, pady=4)
                lbl.pack(side="left", fill="x", expand=True, padx=(0, 6))
                self.sum_boxes[col] = lbl
            self.summary_var = tk.StringVar(value="")
            ttk.Label(sum_frame, textvariable=self.summary_var, justify="left",
                      wraplength=1150, padding=(0, 4, 0, 0)).pack(fill="x")

            cols = ("newest", "own", "files", "in_period", "size", "pct")
            frame = ttk.Frame(self, padding=(8, 0, 8, 8))
            frame.pack(fill="both", expand=True)
            self.tree = ttk.Treeview(frame, columns=cols, selectmode="browse")
            self.tree.heading("#0", text="Folder / file")
            self.tree.column("#0", width=430, stretch=True)
            for c, (t, w, a) in {
                "newest": ("Last file activity", 175, "center"),
                "own": ("Folder modified", 135, "center"),
                "files": ("Files", 80, "e"),
                "in_period": ("In period", 80, "e"),
                "size": ("Size", 90, "e"),
                "pct": ("% of parent", 140, "w"),
            }.items():
                self.tree.heading(c, text=t)
                self.tree.column(c, width=w, anchor=a, stretch=False)
            vs = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
            hs = ttk.Scrollbar(frame, orient="horizontal", command=self.tree.xview)
            self.tree.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
            self.tree.grid(row=0, column=0, sticky="nsew")
            vs.grid(row=0, column=1, sticky="ns")
            hs.grid(row=1, column=0, sticky="ew")
            frame.rowconfigure(0, weight=1)
            frame.columnconfigure(0, weight=1)

            for col in (GREEN, RED, GRAY):
                self.tree.tag_configure(col, background=BG[col], foreground="black")

            self._tip_iid = None
            self._tip_job = None
            self._tip_win = None
            self.tree.bind("<Motion>", self._tip_motion)
            self.tree.bind("<Leave>", self._tip_leave)
            for b in ("<ButtonPress>", "<MouseWheel>", "<Button-4>", "<Button-5>", "<KeyPress>"):
                self.tree.bind(b, self._tip_leave, add="+")
            self.tree.bind("<<TreeviewOpen>>", self._on_open)
            self.tree.bind("<<TreeviewClose>>", self._on_close_node)
            self.tree.bind("<<TreeviewSelect>>", self._on_select)
            self.tree.bind("<ButtonPress-1>", self._on_press, add="+")
            self.tree.bind("<ButtonRelease-1>", self._on_click, add="+")
            self.tree.bind("<Return>", self._on_activate_key, add="+")
            self.tree.bind("<space>", self._on_activate_key, add="+")
            for b in ("<Button-3>", "<Button-2>", "<Control-Button-1>"):
                self.tree.bind(b, self._context_menu)
            self.menu = tk.Menu(self, tearoff=0)
            self.menu.add_command(label="Copy path", command=self._copy_path)
            self.menu.add_command(label="Copy reason", command=lambda: self._copy_reason(False))
            self.menu.add_command(label="Copy path + reason",
                                  command=lambda: self._copy_reason(True))
            self.menu.add_command(label="Open in file manager", command=self._open_path)
            self.menu.add_separator()
            self.menu.add_command(label="Exclude this folder (applies on next scan)",
                                  command=self._exclude_selected)

            self.status_var = tk.StringVar(value="Pick a folder or network share and click Scan.")
            ttk.Label(self, textvariable=self.status_var, relief="sunken",
                      anchor="w", padding=4).pack(fill="x", side="bottom")

        # ---- period / dates
        def _quick_period(self, label):
            n = int(label.split()[1])
            d = datetime.now()
            try:
                start = d.replace(year=d.year - n)
            except ValueError:               # 29 Feb
                start = d.replace(year=d.year - n, day=28)
            self.from_var.set(f"{start:%Y-%m-%d}")
            self.to_var.set("")

        def _pick_date(self, var):
            import calendar
            try:
                cur = datetime.strptime(var.get().strip(), "%Y-%m-%d")
            except ValueError:
                cur = datetime.now()
            st = {"y": cur.year, "m": cur.month}
            win = tk.Toplevel(self)
            win.title("Pick a date")
            win.transient(self)
            win.resizable(False, False)
            win.geometry(f"+{self.winfo_rootx() + 120}+{self.winfo_rooty() + 60}")
            head = ttk.Frame(win)
            head.pack(fill="x", padx=6, pady=(6, 2))
            title = ttk.Label(head, anchor="center", width=16)
            body = ttk.Frame(win)
            body.pack(padx=6, pady=(0, 4))

            def draw():
                for w in body.winfo_children():
                    w.destroy()
                title.config(text=f"{calendar.month_name[st['m']]} {st['y']}")
                for c, n in enumerate(("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su")):
                    ttk.Label(body, text=n, anchor="center", width=4).grid(row=0, column=c)
                for r, week in enumerate(calendar.monthcalendar(st["y"], st["m"]), start=1):
                    for c, d in enumerate(week):
                        if d:
                            ttk.Button(body, text=str(d), width=4,
                                       command=lambda d=d: choose(d)).grid(row=r, column=c)

            def shift(dm):
                m = st["m"] - 1 + dm
                st["y"] += m // 12
                st["m"] = m % 12 + 1
                draw()

            def choose(d):
                var.set(f"{st['y']:04d}-{st['m']:02d}-{d:02d}")
                win.destroy()

            ttk.Button(head, text="<<", width=3, command=lambda: shift(-12)).pack(side="left")
            ttk.Button(head, text="<", width=3, command=lambda: shift(-1)).pack(side="left")
            title.pack(side="left", expand=True)
            ttk.Button(head, text=">", width=3, command=lambda: shift(1)).pack(side="left")
            ttk.Button(head, text=">>", width=3, command=lambda: shift(12)).pack(side="left")
            foot = ttk.Frame(win)
            foot.pack(fill="x", padx=6, pady=(0, 6))
            ttk.Button(foot, text="Clear", command=lambda: (var.set(""), win.destroy())
                       ).pack(side="left")
            ttk.Button(foot, text="Cancel", command=win.destroy).pack(side="right")
            draw()

        # ---- exclusions
        def _ex_add(self, value):
            value = value.strip().strip(QUOTE)
            if value and value not in self.ex_list.get(0, "end"):
                self.ex_list.insert("end", value)

        def _ex_add_folder(self):
            d = filedialog.askdirectory(
                title="Select a folder to exclude",
                initialdir=self.path_var.get() or None)
            if d:
                self._ex_add(os.path.normpath(d) if not d.startswith("\\\\") else d)

        def _ex_add_pattern(self):
            from tkinter import simpledialog
            v = simpledialog.askstring(
                "Add exclusion",
                "Folder name, wildcard, or relative path.\n\n"
                "Examples:   .snapshot     *backup*     Projects\\Old\n"
                "A name matches folders with that name at ANY depth.",
                parent=self)
            if v:
                self._ex_add(v)

        def _ex_add_common(self):
            for c in COMMON_EXCLUDES:
                self._ex_add(c)

        def _ex_remove(self):
            for idx in reversed(self.ex_list.curselection()):
                self.ex_list.delete(idx)

        def _save_settings(self):
            self.settings.update({               # merge, so the scan history is kept
                "path": self.path_var.get().strip(),
                "excludes": list(self.ex_list.get(0, "end")),
                "precount": bool(self.precount_var.get()),
                "count_created": bool(self.created_var.get()),
            })
            save_settings(self.settings)

        REPORT_JOIN_SECONDS = 10

        def _end_report(self):
            """Stops a running export: asks it to cancel, waits a little, and if its worker is
            still busy ends the browser and removes the temp folder from here."""
            self.report_cancel.set()
            t = self._report_thread
            if t is not None and t.is_alive() and t is not threading.current_thread():
                t.join(self.REPORT_JOIN_SECONDS)
                if t.is_alive():
                    _end_live_exports()

        def destroy(self):
            try:                         # not frozen-looking while a browser is being ended
                self.withdraw()
            except tk.TclError:
                pass
            self._end_report()           # the browser must not outlive the window
            self._end_scan()
            try:                         # no stray callback may fire into a dead interpreter
                self.after_cancel(self._poll_job)
            except (tk.TclError, AttributeError):
                pass
            super().destroy()

        def _end_scan(self):
            """A scan still running when the window closes is canceled, and the computer is let
            go of at once: no caffeinate or systemd-inhibit may outlive the window."""
            self.cancel_event.set()
            t = getattr(self, "_scan_thread", None)
            if t is not None and t.is_alive():
                t.join(2)
            release_all_awake()

        def _on_close(self):
            try:
                self._save_settings()
                self.destroy()
            except tk.TclError:          # window already gone
                pass

        def report_callback_exception(self, exc, val, tb):
            # Ctrl+C / IDE "Stop" while the window is open: close quietly, no traceback.
            if issubclass(exc, KeyboardInterrupt):
                self._on_close()
            else:
                super().report_callback_exception(exc, val, tb)

        # ---- scanning
        def _browse(self):
            d = filedialog.askdirectory(title="Select folder or mounted share")
            if d:
                self.path_var.set(d)

        def _start(self):
            if self._report_thread is not None and self._report_thread.is_alive():
                messagebox.showinfo("Report in progress",
                                    "Wait for the report to finish, or cancel it, before scanning.")
                return
            root = self.path_var.get().strip().strip(QUOTE)
            if not root or not os.path.isdir(root):
                messagebox.showerror("Invalid path",
                                     "That folder does not exist or is not reachable.")
                return
            try:
                d_from = parse_date(self.from_var.get())
                d_to = parse_date(self.to_var.get(), end_of_day=True)
            except ValueError:
                messagebox.showerror("Invalid date", "Use the format YYYY-MM-DD, e.g. 2024-10-28.")
                return
            if d_from is None and d_to is None:
                messagebox.showerror("Missing period", "Enter at least a From date.")
                return
            if d_from and d_to and d_from > d_to:
                messagebox.showerror("Invalid period", "The From date is after the To date.")
                return
            self.period_text = describe_period(d_from, d_to)
            lo = d_from.timestamp() if d_from else None
            hi = d_to.timestamp() if d_to else None

            self.cancel_event.clear()
            self.rows = []
            self.tree.delete(*self.tree.get_children())
            self._clear_summary()
            self.meter = ProgressMeter()
            precount = self.precount_var.get()
            self.prog_bar.stop()
            self.prog_bar.config(mode="determinate", value=0)
            self.prog_pct_var.set("")
            self.prog_var.set("Starting...")
            self.scan_btn.config(state="disabled")
            self.cancel_btn.config(state="normal")
            self.export_btn.config(state="disabled")
            self.report_btn.config(state="disabled")
            self.status_var.set("Scanning...")
            self.awake_note = ""
            self.t0 = time.monotonic()
            follow = self.symlink_var.get()
            excludes = list(self.ex_list.get(0, "end"))
            self._save_settings()
            self._totals_key = totals_key(root, excludes, follow)
            if self.created_var.get():
                created_mode, activity = ("auto" if CREATED_NATIVE else "ctime"), "modified or created"
            else:
                created_mode, activity = "off", "modified"
            self.scan_ctx = {"lo": lo, "hi": hi, "created": created_mode, "activity": activity}
            self.file_gen += 1        # late file listings from the previous scan are dropped
            self.file_queue, self.file_loading = [], set()
            self.scan_meta = {
                "root": root, "excludes": excludes, "excluded_count": 0,
                "scanned_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "elapsed": None, "canceled": False, "activity": activity,
                "computer": socket.gethostname(),
            }

            def scan_body():
                stats = {}

                def report(p):
                    self.q.put(("progress", p))

                totals, exact = None, True
                if precount:
                    totals = count_tree(root, self.cancel_event, report,
                                        follow_symlinks=follow, excludes=excludes)
                    if totals is None:                       # canceled while counting
                        self.q.put(("done", [], self.period_text, True, 0))
                        return
                else:
                    totals, exact = last_totals(self.settings, self._totals_key), False
                folders, canceled = scan_tree(
                    root, self.cancel_event, report,
                    follow_symlinks=follow, excludes=excludes, stats=stats,
                    date_from_ts=lo, date_to_ts=hi, totals=totals, totals_exact=exact,
                    created=created_mode)
                rows = build_rows(folders, d_from, d_to, activity)
                self.q.put(("done", rows, self.period_text, canceled,
                            stats.get("excluded", 0)))

            def work():
                try:
                    with keep_awake() as note:      # on this thread: Windows ties it to the thread
                        if note:
                            self.q.put(("note", note))
                        scan_body()
                except Exception as e:
                    self.q.put(("error", str(e)))

            self._scan_thread = threading.Thread(target=work, daemon=True)
            self._scan_thread.start()

        def _cancel(self):
            self.cancel_event.set()
            self.report_cancel.set()
            self.status_var.set("Canceling...")

        def _poll(self):
            try:
                while True:
                    try:
                        msg = self.q.get_nowait()
                    except queue.Empty:
                        break
                    try:
                        self._handle_msg(msg)
                    except Exception as e:      # one bad message must not stop the polling
                        traceback.print_exc()
                        try:
                            self.status_var.set(f"Unexpected error: {e}")
                        except Exception:
                            pass
            finally:
                self._poll_job = self.after(100, self._poll)

        def _handle_msg(self, msg):
            if msg[0] == "progress":
                p = msg[1]
                v = self.meter.update(p)
                pct, counts, times = progress_parts(p, v, "  \u00b7  ")
                if p["phase"] == "count":
                    if str(self.prog_bar.cget("mode")) != "indeterminate":
                        self.prog_bar.config(mode="indeterminate")
                        self.prog_bar.start(15)
                else:
                    if str(self.prog_bar.cget("mode")) != "determinate":
                        self.prog_bar.stop()
                        self.prog_bar.config(mode="determinate")
                    self.prog_bar["value"] = v["fraction"] * 100
                self.prog_pct_var.set(pct)
                self.prog_var.set(f"{counts}     {times}")
                cur = p.get("current") or ""
                cur = (cur[:100] + "...") if len(cur) > 103 else cur
                self.status_var.set(
                    ("Counting: " if p["phase"] == "count" else "Scanning: ") + cur
                    + (f"  |  {self.awake_note}" if self.awake_note else ""))
            elif msg[0] == "done":
                _, rows, cutoff, canceled, n_excl = msg
                try:
                    self.scan_elapsed = time.monotonic() - self.t0
                    self.n_excluded = n_excl
                    self.prog_bar.stop()
                    self.prog_bar.config(mode="determinate",
                                         value=self.prog_bar["value"] if canceled else 100)
                    self.prog_pct_var.set("canceled" if canceled else "100%")
                    last = (self.meter.last if self.meter else None) or {}
                    self.prog_var.set(
                        f"{'Canceled' if canceled else 'Finished'} in "
                        f"{fmt_duration(self.scan_elapsed)}  \u00b7  "
                        f"{last.get('folders', 0):,} folders  \u00b7  "
                        f"{last.get('files', 0):,} files  \u00b7  "
                        f"{fmt_size(last.get('bytes', 0))} read")
                    self._load_rows(rows)
                    if rows and not canceled:
                        remember_totals(self.settings, self._totals_key, len(rows),
                                        self.by_path[self.root_path]["info"].total_files)
                        self._save_settings()
                    self.cutoff = cutoff
                    self.scan_meta.update(elapsed=self.scan_elapsed, canceled=bool(canceled),
                                          excluded_count=n_excl)
                    self._refresh_tree()
                    el = time.monotonic() - self.t0
                    tag = "CANCELED (partial results). " if canceled else "Done. "
                    n_bad = sum(1 for r in rows if r["info"].unreadable)
                    bad = (f" | {n_bad:,} folder(s) could NOT be opened (see gray rows)"
                           if n_bad else "")
                    self.status_var.set(
                        f"{tag}{len(rows):,} folders in {el:.1f}s{bad} | "
                        f"{n_excl:,} folder(s) excluded | period: {cutoff}")
                except Exception as e:
                    traceback.print_exc()
                    messagebox.showerror("Scan finished with an error",
                                         f"The scan completed but showing the results failed: {e}")
                finally:             # whatever failed above, the user can scan again
                    self.scan_btn.config(state="normal")
                    self.cancel_btn.config(state="disabled")
                    self.export_btn.config(state="normal" if rows else "disabled")
                    self.report_btn.config(state="normal" if rows else "disabled")

            elif msg[0] == "files":
                self._files_loaded(*msg[1:])
            elif msg[0] == "note":
                self.awake_note = msg[1]
                self.status_var.set(msg[1])
            elif msg[0] == "report_canceled":
                self.cancel_btn.config(state="disabled")
                self.report_btn.config(state="normal" if self.rows else "disabled")
                self.status_var.set("The PDF was canceled.")
            elif msg[0] == "report_done":
                self._report_done(msg[1], msg[2])
            elif msg[0] == "bg_checked":
                self._bg_checked(*msg[1:])
            elif msg[0] == "background":
                self._bg_started(msg[1])
            elif msg[0] == "jobs_list":
                self._jobs_listed(*msg[1:])
            elif msg[0] == "job_row":
                self._job_row_done(*msg[1:])
            elif msg[0] == "job_done":
                self._job_done(*msg[1:])
            elif msg[0] == "error":
                self.prog_bar.stop()
                self.prog_var.set("Scan failed.")
                self.scan_btn.config(state="normal")
                self.cancel_btn.config(state="disabled")
                messagebox.showerror("Scan failed", msg[1])

        # ---- data helpers
        def _load_rows(self, rows):
            self.rows = rows
            self.by_path = {r["info"].path: r for r in rows}
            self.child_rows = {}
            self.root_path = None
            for r in rows:
                p = r["info"].parent
                if p is None:
                    self.root_path = r["info"].path
                else:
                    self.child_rows.setdefault(p, []).append(r)

        def _folder_basis(self):
            return self.basis_var.get().startswith("Folder")

        def _color(self, r):
            return color_of(r, self._folder_basis())

        def _compute_visibility(self):
            f = self.filter_var.get()
            if f == "All":
                self.visible = None
                self.matching = list(self.rows)
                return
            want = RED if f.startswith("Red") else GRAY if f.startswith("Gray") else GREEN
            self.matching = [r for r in self.rows if self._color(r) == want]
            vis = set()
            for r in self.matching:
                p = r["info"].path
                while p is not None and p not in vis:
                    vis.add(p)
                    p = self.by_path[p]["info"].parent
            self.visible = vis

        def _sorted_children(self, path):
            kids = [c for c in self.child_rows.get(path, [])
                    if self.visible is None or c["info"].path in self.visible]
            s = self.sort_var.get()
            if s.startswith("Size"):
                kids.sort(key=lambda r: -r["info"].total_size)
            elif s.startswith("Name"):
                kids.sort(key=lambda r: r["info"].path.lower())
            elif "oldest" in s:
                kids.sort(key=lambda r: r["info"].newest_file_mtime or 0)
            else:
                kids.sort(key=lambda r: -(r["info"].newest_file_mtime or 0))
            return kids

        # ---- tree building (children are created lazily on expand)
        def _insert(self, parent_iid, r):
            i = r["info"]
            if i.parent is None:
                name = i.path
                pct = "100%"
            else:
                name = os.path.basename(i.path.rstrip("/\\")) or i.path
                ps = self.by_path[i.parent]["info"].total_size
                frac = (i.total_size / ps) if ps else 0
                pct = f"{'█' * round(frac * 10):<10} {frac:.0%}"
            self.tree.insert(
                parent_iid, "end", iid=i.path, text=name, tags=(self._color(r),),
                values=(fmt_ts(i.newest_file_mtime), fmt_ts(i.own_mtime),
                        f"{i.total_files:,}", f"{i.range_files:,}", fmt_size(i.total_size), pct))
            if self._sorted_children(i.path) or i.direct_files:
                self.tree.insert(i.path, "end", iid=i.path + DUMMY, text="")

        def _populate(self, iid):
            kids = self.tree.get_children(iid)
            if len(kids) == 1 and kids[0].endswith(DUMMY):
                self.tree.delete(kids[0])
                for r in self._sorted_children(iid):
                    self._insert(iid, r)
                n = self.by_path[iid]["info"].direct_files
                if n:             # bulk expansion never reads files: the user clicks this row
                    self.tree.insert(iid, "end", iid=MORE_IID + iid, text=f"Show {n:,} files...")

        def _on_open(self, _e):
            self.levels_var.set("")          # a manual open no longer matches a chosen level
            iid = self.tree.focus()
            if iid in self.by_path:
                self._populate(iid)
                self._load_files(iid)

        def _load_files(self, folder):
            if (folder in self.file_cache or folder in self.file_loading
                    or not self.by_path[folder]["info"].direct_files or not self.scan_ctx):
                return
            self.file_loading.add(folder)
            old = FILEERR_IID + folder          # a retry replaces the earlier error row
            if self.tree.exists(old):
                self.tree.delete(old)
            self.file_rows.pop(old, None)
            if self.tree.exists(MORE_IID + folder):
                self.tree.item(MORE_IID + folder, text="Loading files...")
            self.file_queue.append(folder)
            self._pump_files()

        def _pump_files(self):
            while self.file_queue and self.file_active < FILE_THREADS:
                self._start_listing(self.file_queue.pop(0))

        def _start_listing(self, folder):
            gen, ctx, period = self.file_gen, self.scan_ctx, self.period_text
            if len(self.file_abandoned) >= MAX_ABANDONED:
                self._files_loaded(gen, folder, [], "Too many earlier listings are stuck "
                                   "waiting for a server, so this folder was not read.",
                                   final=False)
                return
            self.file_token += 1
            token = self.file_token
            count = [0]               # entries read so far; bumped by the worker, read here

            def progress():
                count[0] += 1
            self.file_live[token] = {"gen": gen, "folder": folder, "count": count, "seen": 0}
            self.file_active += 1

            def work():
                try:
                    rows, err = list_folder_files(folder, ctx["lo"], ctx["hi"], ctx["created"],
                                                  ctx["activity"], period, progress)
                except Exception as e:
                    rows, err = [], f"The files in this folder could not be listed. {e}"
                self.q.put(("files", gen, folder, rows, err, token))
            try:
                threading.Thread(target=work, daemon=True).start()
            except Exception as e:    # no thread could be started: undo, show why
                del self.file_live[token]
                self.file_active -= 1
                self._files_loaded(gen, folder, [], "The files in this folder could not be "
                                   f"listed: no worker could be started ({e}).", final=False)
                return
            self.after(int(LISTING_TIMEOUT * 1000), lambda: self._listing_timeout(token))

        def _listing_timeout(self, token):
            live = self.file_live.get(token)
            if live is None:
                return                                   # it answered in time
            if live["count"][0] != live["seen"]:         # still reading entries: not silent
                live["seen"] = live["count"][0]
                self.after(int(LISTING_TIMEOUT * 1000), lambda: self._listing_timeout(token))
                return
            del self.file_live[token]
            self.file_active -= 1
            self.file_abandoned.add(token)               # the thread may still be blocked
            self._files_loaded(live["gen"], live["folder"], [], "The server did not respond "
                               f"for {LISTING_TIMEOUT:g} seconds, so the files in this folder "
                               "could not be listed.", final=False)

        def _files_loaded(self, gen, folder, rows, err, token=None, final=True):
            if token is not None:
                if token in self.file_abandoned:         # a late answer after the timeout
                    self.file_abandoned.discard(token)
                    return
                if token not in self.file_live:
                    return
                del self.file_live[token]
                self.file_active -= 1                    # that thread has finished
            self._pump_files()
            if gen != self.file_gen:
                return
            self.file_loading.discard(folder)
            if not self.tree.exists(folder):
                return
            if err:
                rows = [{"path": folder, "name": "Files could not be listed", "size": None,
                         "mtime": None, "created": None, "color": GRAY, "reason": err,
                         "iid": FILEERR_IID + folder}]
            else:                 # the color filter applies to real listings only
                rows = sort_file_rows(filter_file_rows(rows, self.filter_var.get()),
                                      self.sort_var.get())
            self.file_cache[folder] = (rows, 0)
            self._show_file_page(folder)
            if not final:         # a timeout is not an answer: opening the folder again retries
                self.file_cache.pop(folder, None)

        def _show_file_page(self, folder):
            rows, shown = self.file_cache[folder]
            more = MORE_IID + folder
            had_focus = more in self.tree.selection() or self.tree.focus() == more
            if self.tree.exists(more):
                self.tree.delete(more)
            first_new, inserted, failure = None, 0, None
            try:
                for f in rows[shown:shown + FILE_PAGE]:
                    iid = f.get("iid") or FILE_IID + f["path"]
                    self.file_rows[iid] = f
                    self.tree.insert(folder, "end", iid=iid, text=f["name"], tags=(f["color"],),
                                     values=(fmt_ts(_file_activity(f) or None), "",
                                             "", "1" if f["color"] == GREEN else "",
                                             "" if f["size"] is None else fmt_size(f["size"]),
                                             ""))
                    first_new = first_new or iid
                    inserted += 1
            except Exception as e:      # leave rows the user can still work with
                traceback.print_exc()
                failure = e
            shown += inserted
            self.file_cache[folder] = (rows, shown)
            try:
                if failure is not None:
                    err = FILEERR_IID + folder
                    if not self.tree.exists(err):
                        self.file_rows[err] = {
                            "path": folder, "name": "Some files could not be shown", "size": None,
                            "mtime": None, "created": None, "color": GRAY,
                            "reason": f"The window could not show all the files: {failure}"}
                        self.tree.insert(folder, "end", iid=err, text="Some files could not be shown",
                                         tags=(GRAY,))
                    first_new = first_new or err
                if shown < len(rows):
                    self.tree.insert(folder, "end", iid=more,
                                     text=f"Show more ({len(rows) - shown:,} left)...")
                if had_focus:     # the row the user was on is gone: keep the keyboard usable
                    target = first_new or folder
                    self.tree.focus(target)
                    self.tree.selection_set(target)
                    self.tree.see(target)
            except Exception:
                traceback.print_exc()

        def _path_of(self, iid):
            if iid in self.file_rows:
                return self.file_rows[iid]["path"]
            return iid

        def _tip_text(self, iid, with_path):
            if iid in self.file_rows:
                f = self.file_rows[iid]
                label = COLOR_LABEL[f["color"]]
                return "\n".join(([f["path"]] if with_path else []) + [label, "- " + f["reason"]])
            return reason_text(self.by_path[iid], self._folder_basis(), with_path)

        def _on_close_node(self, _e):
            self.levels_var.set("")

        def _refresh_tree(self):
            self.levels_var.set("")
            self.file_gen += 1
            self.file_rows, self.file_cache, self.file_loading = {}, {}, set()
            self.file_queue = []
            self.tree.delete(*self.tree.get_children())
            if not self.rows:
                return
            self._compute_visibility()
            root = self.by_path[self.root_path]
            self._insert("", root)
            self._populate(self.root_path)
            self.tree.item(self.root_path, open=True)
            self._load_files(self.root_path)
            self._update_summary()

        def _clear_summary(self):
            for col, lbl in self.sum_boxes.items():
                lbl.config(text=f"{SUMMARY_NAMES[col]}\n-")
            self.summary_var.set("Storage per color appears here at the end of the scan.")

        def _update_summary(self):
            sm = summarize(self.rows, self.n_excluded, self._folder_basis(), self.scan_elapsed)
            if sm is None:
                self._clear_summary()
                return
            tot, c = sm["total"], sm["colors"]
            for col in (GREEN, RED, GRAY):
                b = c[col]
                if col == GRAY:
                    second = (f"{b['folders']:,} folders: {b['empty']:,} empty, "
                              f"{b['unreadable']:,} unreadable")
                else:
                    second = f"{b['files']:,} files  \u00b7  {b['folders']:,} folders"
                self.sum_boxes[col].config(
                    text=f"{SUMMARY_NAMES[col]}:  {fmt_size(b['bytes'])}  "
                         f"({pct_text(b['bytes'], tot)})\n{second}")
            pf, pb = sm["period_files"], sm["period_bytes"]
            t = (f"Total {fmt_size(tot)} in {sm['files']:,} files and {sm['folders']:,} folders"
                 f"  \u00b7  By file date: {fmt_size(pb)} ({pct_text(pb, tot)}) in {pf:,} files "
                 f"{sm['activity']} in the period ({sm['period']}), {fmt_size(tot - pb)} "
                 f"({pct_text(tot - pb, tot)}) not")
            if sm["excluded"]:
                t += f"  \u00b7  {sm['excluded']:,} folder(s) excluded"
            if sm["unreadable"]:
                t += (f"\nWARNING: {sm['unreadable']:,} folder(s) could not be opened - their "
                      "contents are not counted, so the real totals may be higher.")
            self.summary_var.set(t)

        # ---- expand / collapse
        def _expand_all(self, _keep=False):
            """Returns False when the user declined the large-tree prompt."""
            if not self.rows:
                return False
            total = len(self.visible) if self.visible is not None else len(self.rows)
            if total > 20000 and not messagebox.askyesno(
                    "Large tree", f"This opens all {total:,} folders, which can take a while. "
                    "Continue?"):
                return False
            if not _keep:
                self.levels_var.set("")
            self.config(cursor="watch")
            self.update_idletasks()
            stack = [self.root_path]
            while stack:
                iid = stack.pop()
                self._populate(iid)
                self.tree.item(iid, open=True)
                stack.extend(c for c in self.tree.get_children(iid)
                             if c in self.by_path)
            self.config(cursor="")
            return True

        def _collapse_all(self, _keep=False):
            if self.rows:
                if not _keep:
                    self.levels_var.set("")
                for iid in self.tree.get_children(""):
                    self._close_rec(iid)
                self.tree.item(self.root_path, open=True)

        def _count_to_level(self, limit):
            """How many folders the tree shows when opened to this level (root included)."""
            n, stack = 1, [(self.root_path, 0)]
            while stack:
                iid, depth = stack.pop()
                if depth >= limit:
                    continue
                kids = [r["info"].path for r in self._sorted_children(iid)]
                n += len(kids)
                stack.extend((k, depth + 1) for k in kids)
            return n

        def _show_levels(self, value):
            """Opens the tree to the chosen depth. Display only: the scan has read everything.
            The combobox is blanked when nothing was changed or the user declined."""
            if not self.rows:
                return
            if value == "Unlimited":
                if not self._expand_all(_keep=True):
                    self.levels_var.set("")
                return
            limit = int(value)
            total = self._count_to_level(limit)
            if total > 20000 and not messagebox.askyesno(
                    "Large tree", f"This opens {total:,} folders, which can take a while. "
                    "Continue?"):
                self.levels_var.set("")
                return
            self._collapse_all(_keep=True)
            self.config(cursor="watch")
            try:
                self.update_idletasks()
                stack = [(self.root_path, 0)]
                while stack:
                    iid, depth = stack.pop()
                    if depth >= limit:
                        continue
                    self._populate(iid)
                    self.tree.item(iid, open=True)
                    stack.extend((c, depth + 1) for c in self.tree.get_children(iid)
                                 if c in self.by_path)
            finally:
                self.config(cursor="")
            self.levels_var.set(value)

        def _close_rec(self, iid):
            for c in self.tree.get_children(iid):
                if c in self.by_path:
                    self._close_rec(c)
            self.tree.item(iid, open=False)

        def _expand_to_red(self):
            self.levels_var.set("")
            """Open every green/gray ancestor so each top-level red folder is visible."""
            if not self.rows:
                return
            need = set()
            for r in self.rows:
                if self._color(r) == RED:
                    p = r["info"].parent
                    if p is not None and self._color(self.by_path[p]) == RED:
                        continue  # not top-most red
                    while p is not None and p not in need:
                        need.add(p)
                        p = self.by_path[p]["info"].parent
            first_red = None
            stack = [self.root_path]
            while stack:
                iid = stack.pop()
                if iid in need:
                    self._populate(iid)
                    self.tree.item(iid, open=True)
                    stack.extend(c for c in self.tree.get_children(iid)
                                 if c in self.by_path)
            for r in self.rows:
                if self._color(r) == RED and self.tree.exists(r["info"].path):
                    first_red = r["info"].path
                    break
            if first_red:
                self.tree.see(first_red)
            elif not need:
                self.status_var.set("No red (unused) folders found.")

        # ---- selection / context menu
        def _on_select(self, _e):
            sel = self.tree.selection()
            if not sel:
                return
            iid = sel[0]       # a "Show more" row is only activated by click or Enter/space
            if iid in self.file_rows:
                self.status_var.set(self.file_rows[iid]["path"])
            elif iid in self.by_path:
                i = self.by_path[iid]["info"]
                self.status_var.set(
                    f"{i.path}  |  {i.total_files:,} files, {fmt_size(i.total_size)}"
                    + (f"  |  error: {i.error}" if i.error else ""))

        def _activate_more(self, iid):
            folder = iid[len(MORE_IID):]
            if folder in self.file_cache:
                self._show_file_page(folder)
            else:
                self._load_files(folder)

        def _on_press(self, e):
            self._press_row = self.tree.identify_row(e.y)

        def _on_click(self, e):
            iid = self.tree.identify_row(e.y)
            if iid.startswith(MORE_IID) and iid == self._press_row:
                self._activate_more(iid)

        def _on_activate_key(self, _e):
            iid = self.tree.focus()
            if iid.startswith(MORE_IID):
                self._activate_more(iid)
                return "break"

        def _context_menu(self, e):
            iid = self.tree.identify_row(e.y)
            if iid and (iid in self.by_path or iid in self.file_rows):
                self._tip_leave()
                self.tree.selection_set(iid)
                self.menu.entryconfig("Exclude this folder (applies on next scan)",
                                      state="normal" if iid in self.by_path else "disabled")
                self.menu.tk_popup(e.x_root, e.y_root)

        def _exclude_selected(self):
            sel = self.tree.selection()
            if sel and sel[0] in self.by_path:
                if sel[0] == self.root_path:
                    messagebox.showinfo("Exclude", "The scan root itself cannot be excluded.")
                    return
                self._ex_add(sel[0])
                self.status_var.set(f"Added to exclusions: {sel[0]}  -  click Scan to apply.")

        # ---- hover tooltip: why is this folder green / red / gray?
        def _tip_hide(self):
            if self._tip_job is not None:
                self.after_cancel(self._tip_job)
                self._tip_job = None
            if self._tip_win is not None:
                self._tip_win.destroy()
                self._tip_win = None

        def _tip_leave(self, _e=None):
            self._tip_hide()
            self._tip_iid = None

        def _tip_motion(self, e):
            iid = self.tree.identify_row(e.y)
            if iid == self._tip_iid:
                return
            self._tip_hide()
            self._tip_iid = iid
            if iid in self.by_path or iid in self.file_rows:
                self._tip_job = self.after(
                    400, lambda: self._tip_show(iid, e.x_root, e.y_root))

        def _tip_show(self, iid, x, y):
            self._tip_job = None
            if iid != self._tip_iid or not (iid in self.by_path or iid in self.file_rows):
                return
            text = self._tip_text(iid, True)
            tw = tk.Toplevel(self)
            tw.wm_overrideredirect(True)
            try:
                tw.attributes("-topmost", True)
            except tk.TclError:
                pass
            tk.Label(tw, text=text, justify="left", background="#ffffe0", foreground="black",
                     relief="solid", borderwidth=1, wraplength=560, padx=8, pady=5
                     ).pack()
            tw.update_idletasks()
            w, h = tw.winfo_reqwidth(), tw.winfo_reqheight()
            px = min(x + 16, max(0, self.winfo_screenwidth() - w - 4))
            py = y + 22
            if py + h > self.winfo_screenheight() - 4:
                py = max(0, y - h - 12)
            tw.geometry(f"+{px}+{py}")
            self._tip_win = tw

        def _copy_reason(self, with_path):
            sel = self.tree.selection()
            if sel and (sel[0] in self.by_path or sel[0] in self.file_rows):
                self.clipboard_clear()
                self.clipboard_append(self._tip_text(sel[0], with_path))
                self.status_var.set("Copied to clipboard.")

        def _copy_path(self):
            sel = self.tree.selection()
            if sel:
                self.clipboard_clear()
                self.clipboard_append(self._path_of(sel[0]))

        def _open_path(self):
            sel = self.tree.selection()
            if not sel:
                return
            path = self._path_of(sel[0])
            is_file = sel[0].startswith((FILE_IID, FILEERR_IID)) or os.path.isfile(path)
            argv = file_manager_command(path, is_file, sys.platform)
            try:
                if argv is None:
                    os.startfile(path)
                else:
                    subprocess.Popen(argv)
            except Exception as e:
                messagebox.showerror("Cannot open", str(e))

        # ---- export
        def _export_report(self):
            if not self.rows:
                return
            win = tk.Toplevel(self)
            win.title("Export report")
            win.transient(self)
            win.resizable(False, False)
            frm = ttk.Frame(win, padding=16)
            frm.pack(fill="both", expand=True)
            browser = find_browser()
            fmt = tk.StringVar(value=self.settings.get("report_format", "html"))
            if not browser:
                fmt.set("html")
            saved = str(self.settings.get("report_pdf_tree", "2"))
            if saved.startswith("Path"):                     # older settings format
                saved = "unused"
            elif saved.split() and saved.split()[0].isdigit():
                saved = saved.split()[0]
            try:
                saved = parse_pdf_tree(saved)
            except ValueError:
                saved = "2"
            deepest = max(1, max(r["info"].depth for r in self.rows))
            tree_mode = tk.StringVar(value="levels" if saved.isdigit() else saved)
            levels = tk.StringVar(value=saved if saved.isdigit() else str(min(2, deepest)))
            ttk.Label(frm, text="Save the report as:", font=("TkDefaultFont", 10, "bold")
                      ).grid(row=0, column=0, columnspan=2, sticky="w")
            ttk.Radiobutton(frm, variable=fmt, value="html",
                            text="HTML - open folders, search and filter in any browser"
                            ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))
            pdf_rb = ttk.Radiobutton(frm, variable=fmt, value="pdf",
                                     text="PDF - fixed pages for printing and sending")
            pdf_rb.grid(row=2, column=0, columnspan=2, sticky="w", pady=(4, 0))
            ttk.Label(frm, text="Folders in the PDF (the scan itself always covers every level):"
                      ).grid(row=3, column=0, columnspan=2, sticky="w", padx=(22, 0), pady=(10, 0))
            lv = ttk.Frame(frm)
            lv.grid(row=4, column=0, columnspan=2, sticky="w", padx=(40, 0), pady=(4, 0))
            rb_lv = ttk.Radiobutton(lv, variable=tree_mode, value="levels", text="Up to")
            rb_lv.pack(side="left")
            sp = ttk.Spinbox(lv, from_=1, to=deepest, width=5, textvariable=levels)
            sp.pack(side="left", padx=4)
            ttk.Label(lv, text=f"levels below the top folder (this scan goes {deepest} "
                               f"level{'s' if deepest != 1 else ''} deep)").pack(side="left")
            rb_all = ttk.Radiobutton(frm, variable=tree_mode, value="all",
                                     text="All levels - every folder (unlimited)")
            rb_all.grid(row=5, column=0, columnspan=2, sticky="w", padx=(40, 0), pady=(2, 0))
            rb_un = ttk.Radiobutton(frm, variable=tree_mode, value="unused",
                                    text="The path to every unused folder")
            rb_un.grid(row=6, column=0, columnspan=2, sticky="w", padx=(40, 0), pady=(2, 0))
            est_var = tk.StringVar(value="")
            ttk.Label(frm, textvariable=est_var, foreground="#666666", wraplength=460,
                      justify="left").grid(row=7, column=0, columnspan=2, sticky="w",
                                           padx=(40, 0), pady=(6, 0))
            if browser:
                hint = f"The PDF is printed with {os.path.basename(browser)}."
            else:
                pdf_rb.state(["disabled"])
                hint = ("PDF needs Microsoft Edge, Google Chrome or Chromium,\n"
                        "and none was found on this computer.")
            ttk.Label(frm, text=hint, foreground="#666666").grid(
                row=8, column=0, columnspan=2, sticky="w", padx=(22, 0), pady=(10, 0))

            def current_tree():
                if tree_mode.get() != "levels":
                    return tree_mode.get()
                try:
                    return parse_pdf_tree(levels.get())
                except ValueError:
                    return "2"

            def sync(*_):
                on = fmt.get() == "pdf"
                for w in (rb_lv, sp, rb_all, rb_un):
                    w.state(["!disabled"] if on else ["disabled"])
                if not on:
                    est_var.set("")
                    return
                n = pdf_tree_rows(self.rows, current_tree(), self._folder_basis())
                pages = estimate_pdf_pages(n)
                t = f"About {n:,} folders in the PDF tree, roughly {pages:,} pages."
                if pages > 300:
                    t += " That is a very large PDF; the HTML report is easier to use for this."
                est_var.set(t)
            for var in (fmt, tree_mode, levels):
                var.trace_add("write", sync)
            sync()
            btns = ttk.Frame(frm)
            btns.grid(row=9, column=0, columnspan=2, sticky="e", pady=(16, 0))

            def go():
                f, d = fmt.get(), current_tree()
                win.destroy()
                self._save_report(f, d, browser)
            ttk.Button(btns, text="Cancel", command=win.destroy).pack(side="right")
            ttk.Button(btns, text="Save...", command=go).pack(side="right", padx=(0, 6))
            win.bind("<Escape>", lambda e: win.destroy())
            win.update_idletasks()
            win.geometry(f"+{self.winfo_rootx() + 160}+{self.winfo_rooty() + 120}")
            win.grab_set()

        def _save_report(self, fmt, pdf_tree, browser):
            ext = ".pdf" if fmt == "pdf" else ".html"
            fn = filedialog.asksaveasfilename(
                defaultextension=ext,
                filetypes=[("PDF report", "*.pdf")] if fmt == "pdf" else [("HTML report", "*.html")],
                initialfile=f"treerot_report_{datetime.now():%Y%m%d_%H%M}{ext}")
            if not fn:
                return
            if not fn.lower().endswith(ext):
                fn += ext
            self.settings.update(report_format=fmt, report_pdf_tree=pdf_tree)
            self._save_settings()
            meta = dict(self.scan_meta)
            meta["basis_note"] = basis_note(self._folder_basis(), meta["activity"])
            rows, basis = self.rows, self._folder_basis()
            self.report_btn.config(state="disabled")
            self.report_cancel.clear()
            if fmt == "pdf":
                self.cancel_btn.config(state="normal")
            self.status_var.set("Creating the PDF report..." if fmt == "pdf" else "Saving the report...")
            cancel = self.report_cancel

            def work():
                try:
                    # None, not the dialog's browser: naming one browser would turn off the
                    # fallback. The dialog uses find_browser() only to decide if PDF is offered.
                    write_report(fn, rows, meta, basis, pdf_tree, None, cancel)
                    self.q.put(("report_done", fn, None))
                except ReportCanceled:
                    self.q.put(("report_canceled",))
                except (ReportError, OSError) as e:
                    self.q.put(("report_done", fn, str(e)))
            self._report_thread = threading.Thread(target=work, daemon=True)
            self._report_thread.start()

        def _report_done(self, fn, err):
            self.cancel_btn.config(state="disabled")
            self.report_btn.config(state="normal" if self.rows else "disabled")
            if err:
                self.status_var.set("The report was not saved.")
                messagebox.showerror("Report not saved", err)
                return
            self.status_var.set(f"Report saved: {fn}")
            if messagebox.askyesno("Report saved", f"Saved the report to:\n{fn}\n\nOpen it now?"):
                try:
                    open_with_default_app(fn)
                except Exception as e:
                    messagebox.showerror("Cannot open", str(e))

        # ---- background scans (Windows). Everything slow runs on a worker that reports through
        # self.q: a status file or report on a dead share must never stall this thread.
        def _clean_finished_jobs(self):
            def work():
                try:
                    clean_finished_jobs()
                except Exception:
                    traceback.print_exc()
            threading.Thread(target=work, daemon=True).start()

        def _run_background(self):
            if self._bg_starting:
                self.status_var.set("A background scan is still being set up. "
                                    "Look for the console window asking for your password.")
                return
            root = self.path_var.get().strip().strip(QUOTE)
            if not root:
                messagebox.showerror("Invalid path", "Enter the folder or share to scan.")
                return
            text_from, text_to = self.from_var.get().strip(), self.to_var.get().strip()
            try:
                d_from = parse_date(text_from)
                d_to = parse_date(text_to, end_of_day=True)
            except ValueError:
                messagebox.showerror("Invalid date", "Use the format YYYY-MM-DD, e.g. 2024-10-28.")
                return
            if d_from is None and d_to is None:
                messagebox.showerror("Missing period", "Enter at least a From date.")
                return
            if d_from and d_to and d_from > d_to:
                messagebox.showerror("Invalid period", "The From date is after the To date.")
                return
            args = background_args(text_from, text_to, list(self.ex_list.get(0, "end")),
                                   created=self.created_var.get(),
                                   follow_symlinks=self.symlink_var.get(),
                                   precount=self.precount_var.get())
            self._bg_token += 1      # a folder still being checked no longer counts
            token = self._bg_token
            self.status_var.set("Checking the folder...")
            q = self.q

            def work():
                try:
                    problem = check_background_folder(root)
                except Exception as e:
                    problem = str(e) or type(e).__name__
                q.put(("bg_checked", token, root, args, problem))
            threading.Thread(target=work, daemon=True).start()

        def _bg_checked(self, token, root, args, problem):
            if token != self._bg_token or self._bg_starting:
                return
            if problem:
                self.status_var.set("The background scan was not started.")
                messagebox.showerror("Background scan", problem)
                return
            fn = filedialog.asksaveasfilename(
                title="Where should the report be saved?", defaultextension=".html",
                filetypes=[("HTML report", "*.html"), ("PDF report", "*.pdf")],
                initialfile=f"treerot_report_{datetime.now():%Y%m%d_%H%M}.html")
            if not fn:
                self.status_var.set("The background scan was not started.")
                return
            self._bg_starting = True
            self.status_var.set("A console window will ask for your Windows password...")
            q = self.q

            def work():
                try:
                    start_background_scan(root, args, fn)
                    q.put(("background", None))
                except Exception as e:
                    q.put(("background", str(e) or type(e).__name__))
            threading.Thread(target=work, daemon=True).start()

        def _bg_started(self, problem):
            self._bg_starting = False
            if problem:
                self.status_var.set("The background scan was not started.")
                messagebox.showerror("Background scan", problem)
            else:
                self.status_var.set("The background scan is running. You can close this "
                                    "window and log off. See Background scans for progress.")

        def _jobs_panel(self):
            ui = self._jobs_ui
            if ui is not None:
                ui["win"].lift()
                return
            win = tk.Toplevel(self)
            win.title("Background scans")
            win.geometry("900x340")
            frame = ttk.Frame(win)
            frame.pack(fill="both", expand=True, padx=8, pady=8)
            tv = ttk.Treeview(frame, columns=("state", "detail"), selectmode="browse", height=8)
            tv.heading("#0", text="Folder")
            tv.heading("state", text="State")
            tv.heading("detail", text="Details")
            tv.column("state", width=90, stretch=False)
            bar = ttk.Scrollbar(frame, orient="vertical", command=tv.yview)
            tv.configure(yscrollcommand=bar.set)
            bar.pack(side="right", fill="y")
            tv.pack(side="left", fill="both", expand=True)
            detail = ttk.Label(win, wraplength=870, justify="left")
            detail.pack(fill="x", padx=8)
            btns = ttk.Frame(win)
            btns.pack(fill="x", padx=8, pady=8)
            open_btn = ttk.Button(btns, text="Open report", command=self._jobs_open, state="disabled")
            end_btn = ttk.Button(btns, text="End scan", command=self._jobs_end, state="disabled")
            remove_btn = ttk.Button(btns, text="Remove", command=self._jobs_remove, state="disabled")
            open_btn.pack(side="left")
            end_btn.pack(side="left", padx=6)
            remove_btn.pack(side="left")
            note = ttk.Label(btns, wraplength=600, justify="left")
            note.pack(side="left", padx=12)
            self._jobs_gen += 1
            self._jobs_ui = {
                "win": win, "tv": tv, "detail": detail, "note": note,
                "open": open_btn, "end": end_btn, "remove": remove_btn, "gen": self._jobs_gen,
                "jobs": {}, "states": {}, "reports": {},
                "reading": set(),      # jobs with a status read in progress (one each, at most)
                "changing": set(),     # jobs being removed: a late read must not bring them back
                "gone": set(), "listing": False, "after": None}
            tv.bind("<<TreeviewSelect>>", lambda _e: self._jobs_sync())

            def closed(e):
                if e.widget is win:
                    ui = self._jobs_ui
                    self._jobs_ui = None
                    if ui is not None and ui["after"] is not None:
                        try:
                            self.after_cancel(ui["after"])
                        except tk.TclError:
                            pass
            win.bind("<Destroy>", closed)
            self._jobs_refresh()

        def _jobs_refresh(self):
            ui = self._jobs_ui
            if ui is None:
                return
            self._jobs_fetch()
            ui["after"] = self.after(JOBS_REFRESH_MS, self._jobs_refresh)

        def _jobs_fetch(self):
            ui = self._jobs_ui
            if ui is None or ui["listing"]:
                return
            ui["listing"] = True
            gen, q = ui["gen"], self.q

            def work():
                try:
                    jobs = load_jobs()
                except Exception:
                    traceback.print_exc()
                    jobs = None
                q.put(("jobs_list", gen, jobs))
            threading.Thread(target=work, daemon=True).start()

        def _jobs_listed(self, gen, jobs):
            ui = self._jobs_ui
            if ui is None or ui["gen"] != gen:
                return
            ui["listing"] = False
            if jobs is None:
                return
            tv = ui["tv"]
            wanted = {j["id"]: j for j in jobs if j["id"] not in ui["gone"]}
            for iid in tv.get_children():
                if iid not in wanted:
                    tv.delete(iid)
            ui["jobs"] = wanted
            for iid, job in wanted.items():
                if not tv.exists(iid):
                    tv.insert("", "end", iid=iid, text=job["root"], values=("Checking", ""))
                if iid not in ui["reading"] and iid not in ui["changing"]:
                    ui["reading"].add(iid)
                    self._jobs_read(gen, job)
            self._jobs_sync()

        def _jobs_read(self, gen, job):
            q = self.q

            def work():
                try:
                    row = job_row(job)
                except Exception as e:
                    row = ("failed", f"Could not read this scan's status: {e}", None)
                q.put(("job_row", gen, job["id"], row))
            threading.Thread(target=work, daemon=True).start()

        def _job_row_done(self, gen, iid, row):
            ui = self._jobs_ui
            if ui is None or ui["gen"] != gen:
                return
            ui["reading"].discard(iid)
            tv = ui["tv"]
            if iid in ui["changing"] or iid in ui["gone"] or not tv.exists(iid):
                return
            state, detail, report = row
            ui["states"][iid], ui["reports"][iid] = state, report
            tv.item(iid, values=(JOB_LABELS.get(state, state), detail))
            self._jobs_sync()

        def _jobs_selected(self):
            ui = self._jobs_ui
            sel = ui["tv"].selection() if ui is not None else ()
            return ui["jobs"].get(sel[0]) if sel else None

        def _jobs_sync(self):
            """The buttons and the full text follow the selected row."""
            ui = self._jobs_ui
            if ui is None:
                return
            job = self._jobs_selected()
            iid = job["id"] if job else None
            idle = job is not None and iid not in ui["changing"]
            live = ui["states"].get(iid) in JOB_LIVE

            def enable(name, on):
                ui[name].config(state="normal" if on else "disabled")
            enable("open", idle and bool(ui["reports"].get(iid)))
            enable("end", idle and live)
            enable("remove", idle)
            ui["detail"].config(text=ui["tv"].set(iid, "detail") if job else "")

        def _jobs_work(self, ui, fn, after=None):
            """Runs fn on a worker. What it returns, or the error, goes in the panel's note."""
            gen, q = ui["gen"], self.q

            def work():
                try:
                    note, ok = fn() or "", True
                except Exception as e:
                    note, ok = str(e) or type(e).__name__, False
                q.put(("job_done", gen, note, after, ok))
            threading.Thread(target=work, daemon=True).start()

        def _job_done(self, gen, note, after, ok):
            ui = self._jobs_ui
            if ui is None or ui["gen"] != gen:
                return
            ui["note"].config(text=note)
            if after is not None:
                after(ok)
            self._jobs_sync()
            self._jobs_fetch()

        def _jobs_open(self):
            job = self._jobs_selected()
            if job is None:
                return

            def work():
                path = job_report(job)
                if path is None:
                    return "The report file was not found."
                open_with_default_app(path)
                return ""
            self._jobs_ui["note"].config(text="Opening the report...")
            self._jobs_work(self._jobs_ui, work)

        def _jobs_end(self):
            job = self._jobs_selected()
            if job is None:
                return
            if not messagebox.askyesno("End scan", "End this scan? It stops now and "
                                                   "writes no report.", parent=self._jobs_ui["win"]):
                return

            def work():
                end_job(job)
                return "The scan was ended."
            self._jobs_ui["note"].config(text="Ending the scan...")
            self._jobs_work(self._jobs_ui, work)

        def _jobs_remove(self):
            job = self._jobs_selected()
            if job is None:
                return
            ui, iid = self._jobs_ui, job["id"]
            # Not yet known to be over (its share may not be answering): treat it as running.
            running = ui["states"].get(iid) not in ("finished", "failed", "ended")
            if running and not messagebox.askyesno(
                    "Remove", "This scan may still be running. End it and remove it?",
                    parent=ui["win"]):
                return
            ui["changing"].add(iid)
            ui["tv"].item(iid, values=("Removing", ""))
            ui["note"].config(text="")
            self._jobs_sync()

            def work():
                if running:
                    try:
                        end_job(job)
                    except (BackgroundError, OSError):
                        pass               # it had already stopped, most likely
                remove_job(job)

            def after(ok):
                ui["changing"].discard(iid)
                if ok:
                    ui["gone"].add(iid)
                    ui["jobs"].pop(iid, None)
                    if ui["tv"].exists(iid):
                        ui["tv"].delete(iid)
            self._jobs_work(ui, work, after)

        def _about(self):
            if messagebox.askyesno(f"About {APP_NAME}",
                                   f"{APP_NAME} {__version__}\n{CREDIT}\n{CREDIT_URL}\n\n"
                                   "Open this link in your browser?"):
                import webbrowser
                webbrowser.open(CREDIT_URL)

        def _export(self):
            rows = self.matching
            if not rows:
                messagebox.showinfo("Nothing to export", "No rows match the current filter.")
                return
            fn = filedialog.asksaveasfilename(
                defaultextension=".csv", filetypes=[("CSV", "*.csv")],
                initialfile=f"treerot_{datetime.now():%Y%m%d_%H%M}.csv")
            if fn:
                try:
                    write_csv(fn, rows)
                    messagebox.showinfo("Exported", f"Saved {len(rows):,} rows to:\n{fn}")
                except OSError as e:
                    messagebox.showerror("Export failed", str(e))

    try:
        app = App()
    except tk.TclError as e:               # typically: no display on a server / SSH session
        gui_unavailable(f"the window could not be created ({e}).")
    if preload:                      # used for testing / screenshots
        app.path_var.set(preload)
        app.after(300, app._start)
    if on_ready:                     # test hook: on_ready(app) runs once the window is up
        app.after(300, lambda: on_ready(app))
    try:
        app.mainloop()
    except KeyboardInterrupt:
        app._on_close()


# --------------------------------------------------------------------------
# HTML report (one self-contained file: opens in any browser, prints to PDF)
# --------------------------------------------------------------------------


def _period_phrase(period):
    if " to " in period:
        a_, b_ = period.split(" to ", 1)
        return f"between {a_} and {b_}"
    return period


def report_data(rows, meta, folder_basis=False, cancel_event=None):
    """Compact, JSON-ready data for the report. Rows are ordered so a parent always comes first."""
    root = next(r for r in rows if r["info"].parent is None)
    kids = {}
    for r in rows:
        if r["info"].parent is not None:
            kids.setdefault(r["info"].parent, []).append(r)
    order, idx = [], {}
    stack = [root]
    while stack:
        r = stack.pop()
        idx[r["info"].path] = len(order)
        order.append(r)
        stack.extend(kids.get(r["info"].path, []))
    code = {GREEN: "g", RED: "r", GRAY: "x"}
    by_path = {r["info"].path: r for r in rows}
    out = []
    for n, r in enumerate(order):
        if n % 2000 == 0:
            _check_canceled(cancel_event)
        i = r["info"]
        c = color_of(r, folder_basis)
        special = c == GRAY or bool(i.error) or bool(i.unreadable_below and not folder_basis)
        name = i.path if i.parent is None else (os.path.basename(i.path.rstrip("/\\")) or i.path)
        out.append([idx[i.parent] if i.parent is not None else -1, name, code[c],
                    i.total_size, i.total_files, i.range_files,
                    fmt_ts(i.newest_file_mtime), fmt_ts(i.own_mtime),
                    reason_text(r, folder_basis) if special else ""])
    # bytes inside each folder that sit in unused (red) folders; rows are parent-first
    unused_in = [0] * len(order)
    for k in range(len(order) - 1, -1, -1):
        r = order[k]
        if color_of(r, folder_basis) == RED:
            unused_in[k] += r["info"].direct_size
        if out[k][0] >= 0:
            unused_in[out[k][0]] += unused_in[k]
    for k, row in enumerate(out):
        row.append(unused_in[k])
    red_top = [r for r in rows if color_of(r, folder_basis) == RED and (
        r["info"].parent is None or color_of(by_path[r["info"].parent], folder_basis) != RED)]
    red_top.sort(key=lambda r: -r["info"].total_size)
    sm = summarize(rows, meta.get("excluded_count", 0), folder_basis, meta.get("elapsed"))
    root_path = root["info"].path
    return {
        "rows": out,
        "top_red": [idx[r["info"].path] for r in red_top[:25]],
        "red_top_count": len(red_top),
        "sep": "\\" if ("\\" in root_path and "/" not in root_path) else "/",
        "summary": {
            "colors": sm["colors"], "total": sm["total"], "files": sm["files"],
            "folders": sm["folders"], "period_files": sm["period_files"],
            "period_bytes": sm["period_bytes"], "unreadable": sm["unreadable"],
        },
        "period": root["period"], "period_phrase": _period_phrase(root["period"]),
        "activity": root.get("activity", "modified"), "folder_basis": folder_basis,
        "meta": {k: v for k, v in meta.items()},
        "version": __version__,
        "icon": ICON_PNG_B64,
    }


def _check_canceled(cancel_event):
    if cancel_event is not None and cancel_event.is_set():
        raise ReportCanceled("The report was canceled.")


def write_html_report(path, rows, meta, folder_basis=False, pdf=None, cancel_event=None):
    """Writes the HTML report. Checks cancel_event as it works; a canceled or failed write leaves
    no partial file, and an existing report is only replaced once the new one is complete."""
    import html as html_mod
    _check_canceled(cancel_event)
    data = report_data(rows, meta, folder_basis, cancel_event)
    data["pdf"] = pdf                     # None for the interactive HTML report
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    payload = payload.replace("</", "<\\/").replace("<!--", "<\\!--")   # safe inside <script>
    title = f"Folder activity report - {meta.get('root', '')}"
    page = REPORT_TEMPLATE.replace("__TITLE__", html_mod.escape(title)).replace("__DATA__", payload)
    _check_canceled(cancel_event)
    part = path + ".part"
    try:
        with open(part, "w", encoding="utf-8") as f:
            for i in range(0, len(page), 1 << 20):     # a share can be slow: look up every MB
                f.write(page[i:i + (1 << 20)])
                _check_canceled(cancel_event)
        _check_canceled(cancel_event)
        os.replace(part, path)
    except BaseException:
        try:
            os.remove(part)
        except OSError:
            pass
        raise


class ReportError(Exception):
    pass


class ReportCanceled(ReportError):
    pass


NO_BROWSER_MSG = (
    "A PDF report is made by printing the report with Microsoft Edge, Google Chrome or "
    "Chromium, and none of them was found on this computer. Save the report as HTML "
    "instead (it prints to PDF from any browser), install one of those browsers, or point "
    "to one with --browser PATH.")


def _browser_rank(path):
    """Edge, then Chrome, then Chromium, then anything else such as Brave. On Windows Chromium's
    program is also called chrome.exe, so a folder named Chromium just above it decides."""
    parts = [p.lower() for p in path.replace("\\", "/").split("/") if p][-3:]
    name = parts[-1] if parts else ""
    if "edge" in name:
        return 0
    if "chromium" in name or "chromium" in parts[:-1]:
        return 2
    if "chrome" in name:
        return 1
    return 3


def find_browsers(explicit=None):
    """Chromium-family browsers that can print to PDF, best first. An explicit one is the only one."""
    if explicit:
        return [explicit] if os.path.isfile(explicit) else []
    cands = [os.environ.get("TREEROT_BROWSER"), os.environ.get("FAS_BROWSER")]
    override = [c for c in cands if c and os.path.isfile(c)]
    if override:
        return override[:1]
    cands = []
    if sys.platform == "win32":
        for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"),
                     os.environ.get("LOCALAPPDATA")):
            if base:
                cands += [os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe"),
                          os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"),
                          os.path.join(base, "Chromium", "Application", "chrome.exe"),
                          os.path.join(base, "BraveSoftware", "Brave-Browser", "Application",
                                       "brave.exe")]
    elif sys.platform == "darwin":
        cands += ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                  "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
                  "/Applications/Chromium.app/Contents/MacOS/Chromium",
                  "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"]
    for name in ("msedge", "microsoft-edge", "microsoft-edge-stable", "google-chrome",
                 "google-chrome-stable", "chromium", "chromium-browser", "chrome",
                 "brave-browser", "brave"):
        cands.append(shutil.which(name))
    found, seen = [], set()
    for c in cands:
        if c and os.path.isfile(c) and os.path.realpath(c) not in seen:
            seen.add(os.path.realpath(c))
            found.append(c)
    return sorted(found, key=_browser_rank)


def find_browser(explicit=None):
    found = find_browsers(explicit)
    return found[0] if found else None


def pdf_timeout(n_rows):
    return min(600, 60 + n_rows // 50)


def _pdf_ready(path):
    """True once path is a complete PDF: the header is there and the end marker was written."""
    try:
        with open(path, "rb") as f:
            if f.read(5) != b"%PDF-":
                return False
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - 1024))
            return b"%%EOF" in f.read()
    except OSError:
        return False


class _WinJob:
    """A Windows Job Object that ends every process in it when closed (ctypes, stdlib only).
    The browser and anything it starts are put in it, so no helper outlives the export.
    NOTE: written for Windows and not run on other systems."""

    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self._lock = threading.Lock()
        self._k = k = ctypes.WinDLL("kernel32", use_last_error=True)
        self._ct = ctypes
        ULONG_PTR = ctypes.c_size_t

        class Basic(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64),
                        ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", ctypes.c_uint32),
                        ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t),
                        ("ActiveProcessLimit", ctypes.c_uint32),
                        ("Affinity", ULONG_PTR),
                        ("PriorityClass", ctypes.c_uint32),
                        ("SchedulingClass", ctypes.c_uint32)]

        class IoCounters(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in
                        ("ReadOps", "WriteOps", "OtherOps", "ReadBytes", "WriteBytes",
                         "OtherBytes")]

        class Extended(ctypes.Structure):
            _fields_ = [("Basic", Basic), ("Io", IoCounters),
                        ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        class Accounting(ctypes.Structure):
            _fields_ = [("TotalUserTime", ctypes.c_int64), ("TotalKernelTime", ctypes.c_int64),
                        ("ThisPeriodTotalUserTime", ctypes.c_int64),
                        ("ThisPeriodTotalKernelTime", ctypes.c_int64),
                        ("TotalPageFaultCount", ctypes.c_uint32),
                        ("TotalProcesses", ctypes.c_uint32),
                        ("ActiveProcesses", ctypes.c_uint32),
                        ("TotalTerminatedProcesses", ctypes.c_uint32)]
        self._Accounting = Accounting
        k.CreateJobObjectW.restype = wintypes.HANDLE
        k.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        k.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                              wintypes.DWORD]
        k.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                                wintypes.DWORD, ctypes.c_void_p]
        k.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        k.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        self.handle = k.CreateJobObjectW(None, None)
        if not self.handle:
            raise OSError("CreateJobObject failed")
        info = Extended()
        info.Basic.LimitFlags = 0x2000          # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not k.SetInformationJobObject(self.handle, 9, ctypes.byref(info),
                                         ctypes.sizeof(info)):
            self.close()
            raise OSError("SetInformationJobObject failed")

    def assign(self, proc):
        if not self._k.AssignProcessToJobObject(self.handle, int(proc._handle)):
            raise OSError("AssignProcessToJobObject failed")

    def active(self):
        """Number of processes still in the job, or None if it cannot be asked."""
        info = self._Accounting()
        if not self._k.QueryInformationJobObject(self.handle, 1, self._ct.byref(info),
                                                 self._ct.sizeof(info), None):
            return None
        return info.ActiveProcesses

    def terminate(self):
        self._k.TerminateJobObject(self.handle, 1)

    def close(self):
        with self._lock:             # the window's thread and the worker may both get here
            h, self.handle = self.handle, None
        if h:
            self._k.CloseHandle(h)


def _new_job():
    """A Job Object on Windows, made BEFORE the browser starts (its first use also loads ctypes,
    which is slow enough for a child to be started meanwhile). None when that is not possible:
    never a reason to stop the export (taskkill /T is the fallback)."""
    if sys.platform != "win32":
        return None
    try:
        return _WinJob()
    except Exception:
        return None


def _attach_job(proc, job):
    """Puts the just-started browser in job. None (and the job closed) if that fails, so that
    ending the tree falls back to taskkill /T."""
    if job is None:
        return None
    try:
        job.assign(proc)
        return job
    except Exception:
        try:
            job.close()
        except Exception:
            pass
        return None


_LIVE_LOCK = threading.Lock()
_LIVE_PROCS = set()          # browsers started by a running export
_LIVE_DIRS = {}            # temporary report folder -> cancel flag of the export using it


def _end_live_exports():
    """Ends the browsers and removes the temp folders of every export still running. Used when
    the window closes (or the program exits) and a worker is slow to finish by itself. Safe to
    call from several threads: ending a tree and removing a folder both tolerate repeats. Only
    processes this program started are touched."""
    with _LIVE_LOCK:
        procs, dirs = list(_LIVE_PROCS), list(_LIVE_DIRS.items())
    for _, flag in dirs:            # first stop the workers, so none starts another browser
        flag.set()
    for proc in procs:
        _kill_tree(proc)
    for d, _ in dirs:
        shutil.rmtree(d, ignore_errors=True)


atexit.register(_end_live_exports)


def _tree_alive(proc):
    """True while the browser or anything it started is still running."""
    if proc.poll() is None:
        return True
    if sys.platform == "win32":
        job = getattr(proc, "job", None)
        try:
            return bool(job and job.active())
        except Exception:
            return False
    try:
        os.killpg(proc.pid, 0)       # signal 0 only asks whether the group has any member
        return True
    except OSError:
        return False


def _kill_tree(proc):
    """Ends proc and everything it started. Only our own process group / job, never by name."""
    job = getattr(proc, "job", None)
    try:
        if sys.platform == "win32":
            if job is not None:
                try:
                    job.terminate()
                except Exception:
                    job = None
            if job is None:          # no job: taskkill /T follows the tree while the parent lives
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=0x08000000, timeout=20)
        else:
            os.killpg(proc.pid, 9)       # the browser was started as its own group leader
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        proc.kill()
        proc.wait(timeout=5)
    except (OSError, subprocess.SubprocessError):
        pass
    if job is not None:
        try:
            job.close()
        except Exception:
            pass


def _run_browser(cmd, pdf_path, timeout, cancel_event):
    """Returns ("ok" | "exit" | "timeout", detail). Raises ReportCanceled. Never leaves it running."""
    if cancel_event is not None and cancel_event.is_set():
        raise ReportCanceled("The PDF was canceled.")
    flags = 0x08000000 if sys.platform == "win32" else 0     # CREATE_NO_WINDOW
    extra = {} if sys.platform == "win32" else {"start_new_session": True}
    with tempfile.TemporaryFile() as err:
        job = _new_job()
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=err,
                                    creationflags=flags, **extra)
        except BaseException:
            if job is not None:
                job.close()
            raise
        proc.job = _attach_job(proc, job)    # Windows only; None elsewhere or if it fails
        with _LIVE_LOCK:
            _LIVE_PROCS.add(proc)
        deadline = time.monotonic() + timeout
        try:
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    raise ReportCanceled("The PDF was canceled.")
                alive = _tree_alive(proc)      # a launcher may exit while its child prints
                if _pdf_ready(pdf_path):
                    return "ok", ""
                gone = proc.poll() is not None
                if not alive or (gone and time.monotonic() > deadline):
                    # The browser itself exited without a PDF. A helper still holding on does
                    # not make that a hang: report how it ended, and let the retry run.
                    err.seek(0)
                    text = err.read().decode("utf-8", "replace").strip()[-300:]
                    return "exit", f"the browser exited with status {proc.returncode}" + (
                        f": {text}" if text else "")
                if time.monotonic() > deadline:
                    return "timeout", f"did not finish within {timeout} seconds"
                time.sleep(0.25)
        finally:
            _kill_tree(proc)        # also helper processes left behind by an exited browser
            with _LIVE_LOCK:
                _LIVE_PROCS.discard(proc)


def html_to_pdf(html_path, pdf_path, browser, workdir, timeout, cancel_event=None):
    """Prints HTML to PDF with one browser. Raises ReportError with the reason on failure."""
    import pathlib
    profile = tempfile.mkdtemp(prefix="profile_", dir=workdir)   # never touch the user's profile
    try:
        args = ["--disable-gpu", "--no-first-run", "--no-default-browser-check",
                "--disable-extensions", f"--user-data-dir={profile}",
                "--no-pdf-header-footer", "--print-to-pdf-no-header",
                f"--print-to-pdf={pdf_path}", "--virtual-time-budget=20000"]
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            args.append("--no-sandbox")       # Chromium refuses to run as root otherwise
        url = pathlib.Path(html_path).resolve().as_uri()
        detail = ""
        for headless in ("--headless=new", "--headless"):        # newer and older browsers
            try:
                state, detail = _run_browser([browser, headless] + args + [url], pdf_path,
                                             timeout, cancel_event)
            except OSError as e:
                raise ReportError(f"could not start: {e}")
            if state == "ok":
                return
            if state == "timeout":            # a hang will not improve with the older flag
                break
        raise ReportError(detail or "finished without producing a PDF")
    finally:
        shutil.rmtree(profile, ignore_errors=True)


def parse_pdf_tree(value):
    """
    How much of the folder tree a PDF shows: a number of levels below the top folder
    ("1", "2", ...), "all" for every level (also "unlimited" or "0"), or "unused" for the
    path to every unused folder. Raises ValueError for anything else.
    """
    v = str(value).strip().lower()
    if v in ("all", "unlimited", "0"):
        return "all"
    if v in ("unused", "red"):
        return "unused"
    n = int(v)
    if n < 1:
        raise ValueError(value)
    return str(n)


PDF_TREE_ROWS_PER_PAGE = 26          # folder rows per A4 landscape page (measured: 1,692 rows
PDF_OVERVIEW_PAGES = 6               # = 73 pages, 2,601 = 110, 4,041 = 158)


def pdf_tree_rows(rows, pdf_tree, folder_basis=False):
    """How many folder rows the PDF's tree will contain, so a huge PDF can be flagged first."""
    if pdf_tree == "all":
        return len(rows)
    nkids = {}
    for r in rows:
        if r["info"].parent is not None:
            nkids[r["info"].parent] = nkids.get(r["info"].parent, 0) + 1
    if pdf_tree == "unused":
        by_path = {r["info"].path: r for r in rows}
        opened = set()
        for r in rows:
            par = r["info"].parent
            if color_of(r, folder_basis) == RED and (
                    par is None or color_of(by_path[par], folder_basis) != RED):
                while par is not None and par not in opened:
                    opened.add(par)
                    par = by_path[par]["info"].parent
        return 1 + sum(nkids.get(p_, 0) for p_ in opened)
    n = int(pdf_tree)
    return sum(1 for r in rows if r["info"].depth <= n)


def estimate_pdf_pages(n_rows):
    return PDF_OVERVIEW_PAGES + -(-n_rows // PDF_TREE_ROWS_PER_PAGE)


def write_report(path, rows, meta, folder_basis=False, pdf_tree="2", browser=None,
                 cancel_event=None):
    """
    Write the report as HTML or PDF, chosen by the file extension.
    pdf_tree: how much of the folder tree the PDF shows (see parse_pdf_tree). The scan itself
    always covers every level; this only limits what is printed.
    """
    if cancel_event is None:
        cancel_event = threading.Event()      # so shutting down can still stop this export
    _check_canceled(cancel_event)
    if not path.lower().endswith(".pdf"):
        write_html_report(path, rows, meta, folder_basis, cancel_event=cancel_event)
        return
    exes = find_browsers(browser)
    if not exes:
        raise ReportError(NO_BROWSER_MSG)
    pdf_tree = parse_pdf_tree(pdf_tree)
    if pdf_tree == "all":
        pdf_opt = {"all": True}
    elif pdf_tree == "unused":
        pdf_opt = {"unused": True}
    else:
        pdf_opt = {"depth": int(pdf_tree)}
    n_rows = pdf_tree_rows(rows, pdf_tree, folder_basis)
    # work next to the target: some browsers (e.g. Ubuntu's snap Chromium) cannot read /tmp
    workdir = tempfile.mkdtemp(prefix=".treerot_report_",
                               dir=os.path.dirname(os.path.abspath(path)))
    with _LIVE_LOCK:
        _LIVE_DIRS[workdir] = cancel_event
    try:
        _check_canceled(cancel_event)
        tmp_html = os.path.join(workdir, "report.html")
        tmp_pdf = os.path.join(workdir, "report.pdf")
        write_html_report(tmp_html, rows, meta, folder_basis, pdf=pdf_opt,
                          cancel_event=cancel_event)
        failures = []
        for exe in exes:
            try:
                html_to_pdf(tmp_html, tmp_pdf, exe, workdir, pdf_timeout(n_rows), cancel_event)
                break
            except ReportCanceled:
                raise
            except ReportError as e:
                failures.append(f"{os.path.basename(exe)}: {e}")
        else:
            text = "No browser could make the PDF.\n" + "\n".join(failures)
            if n_rows > 4000:
                text += (f"\n\nThis PDF would have about {estimate_pdf_pages(n_rows):,} pages "
                         f"({n_rows:,} folders), which may be more than a browser can print. "
                         "Choose fewer levels or 'the path to every unused folder'.")
            raise ReportError(text + "\n\nThe HTML report is still available and shows the "
                              "complete tree.")
        os.replace(tmp_pdf, path)         # only replaces an existing file once the PDF is good
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
        with _LIVE_LOCK:
            _LIVE_DIRS.pop(workdir, None)


def open_with_default_app(path):
    if sys.platform == "win32":
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def basis_note(folder_basis, activity):
    if folder_basis:
        return "Colored by each folder's own date only; the files inside are not considered."
    return (f"A folder counts as used when a file anywhere inside it was {activity} in the "
            "period, even if the folder's own date is older.")


REPORT_TEMPLATE = r'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root {
  color-scheme: light;
  --ink: #1d2730;
  --ink-soft: #56616b;
  --paper: #f5f6f4;
  --sheet: #ffffff;
  --rule: #d8dcd7;
  --used: #2f7d4f;   --used-tint: #dbeee1;
  --unused: #b8402f; --unused-tint: #f6dbd5;
  --empty: #8b939b;  --empty-tint: #e7e9eb;
  --other: #c9ced3;
  --focus: #2457a6;
  --head: "Bahnschrift", "DIN Alternate", "DIN Next", "Roboto Condensed", "Arial Narrow", system-ui, sans-serif;
  --body: system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
}
* { box-sizing: border-box; }
html { background: var(--paper); }
body { margin: 0; color: var(--ink); font: 15px/1.55 var(--body); font-variant-numeric: tabular-nums; }
.wrap { max-width: 1240px; margin: 0 auto; padding: 28px 24px 72px; }
button, input, select { font: inherit; color: inherit; }
:focus-visible { outline: 2px solid var(--focus); outline-offset: 2px; }

.top { display: flex; justify-content: space-between; gap: 12px; flex-wrap: wrap;
       color: var(--ink-soft); font-size: 13px; }
h1 { font-family: var(--head); font-weight: 600; font-size: clamp(26px, 4.2vw, 46px);
     line-height: 1.08; margin: 10px 0 6px; overflow-wrap: anywhere; }
.period { color: var(--ink-soft); margin: 0 0 30px; }
.finding { font-family: var(--head); font-weight: 400; font-size: clamp(19px, 2.3vw, 27px);
           line-height: 1.3; max-width: 44ch; margin: 0 0 18px; }

/* the storage strip: every top-level folder as a block, sized by storage */
.strip { display: flex; align-items: flex-start; width: 100%; }
.seg { flex: 0 0 auto; min-width: 2px; display: flex; flex-direction: column; }
.seg button { display: flex; width: 100%; height: 64px; border: 0; padding: 0; cursor: pointer;
              border-right: 2px solid var(--paper); background: var(--other); overflow: hidden; }
.seg:first-child button { border-radius: 3px 0 0 3px; }
.seg:last-child button { border-radius: 0 3px 3px 0; border-right: 0; }
.seg button i { display: block; height: 100%; flex: 0 0 auto; }
.seg i.g { background: var(--used); } .seg i.r { background: var(--unused); }
.seg i.x { background: var(--empty); } .seg i.o { background: var(--other); }
.seg button.static { cursor: default; }
.seg button:hover:not(.static) { filter: brightness(1.12); }
.seg span { font-size: 12px; color: var(--ink-soft); padding: 4px 6px 0 2px; white-space: nowrap;
            overflow: hidden; text-overflow: ellipsis; }
.strip-note { font-size: 13px; color: var(--ink-soft); margin: 8px 0 0; }

.figures { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 28px;
           margin: 30px 0 6px; }
.fig { border-top: 5px solid; padding-top: 10px; }
.fig.g { border-color: var(--used); } .fig.r { border-color: var(--unused); }
.fig.x { border-color: var(--empty); }
.fig h3 { font: 600 15px/1.3 var(--body); margin: 0; }
.fig .size { font-family: var(--head); font-size: 34px; font-weight: 600; line-height: 1.15;
             margin: 4px 0 2px; }
.fig p { margin: 0; color: var(--ink-soft); font-size: 14px; }
.byfile { max-width: 80ch; margin: 22px 0 0; }
.notice { border-left: 4px solid var(--unused); background: var(--sheet); padding: 10px 14px;
          margin: 18px 0 0; max-width: 90ch; }

section { margin-top: 56px; }
h2 { font-family: var(--head); font-weight: 600; font-size: 26px; margin: 0 0 4px; }
.lead { color: var(--ink-soft); margin: 0 0 14px; max-width: 80ch; }
.scroll { overflow-x: auto; background: var(--sheet); border: 1px solid var(--rule); border-radius: 4px; }
table { border-collapse: collapse; width: 100%; font-size: 14px; }
th { text-align: left; font-weight: 600; font-size: 13px; color: var(--ink-soft); padding: 9px 10px;
     border-bottom: 1px solid var(--rule); background: var(--sheet); white-space: nowrap; }
td { padding: 6px 10px; border-bottom: 1px solid #eceeeb; vertical-align: middle; }
.num { text-align: right; white-space: nowrap; }
.date { white-space: nowrap; }
.path { overflow-wrap: anywhere; min-width: 260px; }
.share { display: inline-block; width: 90px; height: 8px; background: #edf0ec; border-radius: 2px;
         vertical-align: middle; margin-right: 8px; overflow: hidden; }
.share i { display: block; height: 100%; background: var(--unused); }
.linkbtn { border: 1px solid var(--rule); background: var(--paper); border-radius: 3px;
           padding: 2px 10px; cursor: pointer; white-space: nowrap; }
.linkbtn:hover { border-color: var(--ink-soft); }

.controls { display: flex; flex-wrap: wrap; gap: 10px 18px; align-items: center; margin: 0 0 12px; }
.seg-ctl { display: inline-flex; border: 1px solid var(--rule); border-radius: 4px; overflow: hidden;
           background: var(--sheet); }
.seg-ctl label { padding: 5px 12px; cursor: pointer; border-right: 1px solid var(--rule); }
.seg-ctl label:last-child { border-right: 0; }
.seg-ctl input { position: absolute; opacity: 0; pointer-events: none; }
.seg-ctl input:checked + span { font-weight: 600; }
.seg-ctl label:has(input:checked) { background: var(--paper); box-shadow: inset 0 -3px 0 var(--ink); }
.seg-ctl label:has(input:focus-visible) { outline: 2px solid var(--focus); outline-offset: -2px; }
.controls select, .controls input[type=search] { border: 1px solid var(--rule); border-radius: 4px;
           background: var(--sheet); padding: 5px 8px; }
.controls input[type=search] { width: 220px; }
.btn { border: 1px solid var(--rule); background: var(--sheet); border-radius: 4px; padding: 5px 12px;
       cursor: pointer; }
.btn:hover { border-color: var(--ink-soft); }
.tree-note { color: var(--ink-soft); font-size: 13px; min-height: 1.4em; margin: 0 0 8px; }
.pdf-note { color: var(--ink-soft); margin: 0 0 10px; max-width: 90ch; }

table.tree th { position: sticky; top: 0; z-index: 1; }
table.tree td { padding-top: 4px; padding-bottom: 4px; }
table.tree tr.c-g td { background: var(--used-tint); }
table.tree tr.c-r td { background: var(--unused-tint); }
table.tree tr.c-x td { background: var(--empty-tint); }
table.tree tr td:first-child { box-shadow: inset 5px 0 0 var(--bar); }
table.tree tr.c-g { --bar: var(--used); } table.tree tr.c-r { --bar: var(--unused); }
table.tree tr.c-x { --bar: var(--empty); }
table.tree tr.hit td { font-weight: 600; }
table.tree tr.hit td:first-child { outline: 2px solid var(--focus); outline-offset: -2px; }
td.name { white-space: nowrap; }
.tg, .tg-space { display: inline-block; width: 22px; height: 22px; margin-right: 4px;
                 vertical-align: middle; }
.tg { border: 0; background: none; padding: 0; cursor: pointer; border-radius: 3px;
      color: var(--ink); font-size: 13px; line-height: 22px; text-align: center;
      transition: transform .12s; }
.tg:hover { background: rgba(0,0,0,.07); }
.tg[aria-expanded="true"] { transform: rotate(90deg); }
.bar { display: inline-block; width: 64px; height: 8px; background: rgba(255,255,255,.75);
       border-radius: 2px; vertical-align: middle; margin-right: 6px; overflow: hidden; }
.bar i { display: block; height: 100%; background: var(--bar); }
@keyframes flash { from { box-shadow: inset 0 0 0 3px var(--focus); } to { box-shadow: none; } }
tr.flash td { animation: flash 2.2s ease-out; }

dl.details { display: grid; grid-template-columns: max-content 1fr; gap: 6px 24px; margin: 0;
             max-width: 100ch; }
dl.details dt { color: var(--ink-soft); }
dl.details dd { margin: 0; overflow-wrap: anywhere; }

@media (max-width: 760px) {
  .figures { grid-template-columns: 1fr; gap: 18px; }
  .wrap { padding: 20px 14px 56px; }
}
@media (prefers-reduced-motion: reduce) {
  .tg { transition: none; } tr.flash td { animation: none; }
}
@media print {
  html { background: #fff; }
  .wrap { max-width: none; padding: 0; }
  .controls, .linkbtn, .tg, .tree-hint, .tree-note { display: none !important; }
  h2, .lead { break-after: avoid; page-break-after: avoid; }
  tr { break-inside: avoid; }
  .tg-space, .tg { width: 0; margin: 0; }
  section { margin-top: 28px; break-inside: auto; }
  .scroll { overflow: visible; border: 0; }
  table.tree th { position: static; }
  * { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
}
</style>
</head>
<body>
<div class="wrap">
  <div class="top"><span>Folder activity report</span><span id="generated"></span></div>
  <h1 id="root-path"></h1>
  <p class="period" id="period"></p>

  <p class="finding" id="finding"></p>
  <div class="strip" id="strip" role="list" aria-label="Storage by top-level folder"></div>
  <p class="strip-note" id="strip-note"></p>

  <div class="figures" id="figures"></div>
  <p class="byfile" id="byfile"></p>
  <div id="notices"></div>

  <section id="unused-section">
    <h2>Largest unused folders</h2>
    <p class="lead" id="unused-lead"></p>
    <div class="scroll"><table>
      <thead><tr><th>Folder</th><th class="num">Size</th><th>Share of total</th>
        <th class="num">Files</th><th>Last file activity</th><th><span class="tree-hint">In tree</span></th></tr></thead>
      <tbody id="unused-rows"></tbody>
    </table></div>
  </section>

  <section>
    <h2>All folders</h2>
    <p class="lead tree-hint">Open a folder with the arrow. Hover a row to see why it has its color.
      When printing, only the open folders are included.</p>
    <div class="controls">
      <div class="seg-ctl" role="radiogroup" aria-label="Show">
        <label><input type="radio" name="show" value="all" checked><span>All</span></label>
        <label><input type="radio" name="show" value="r"><span>Not used</span></label>
        <label><input type="radio" name="show" value="g"><span>Used</span></label>
        <label><input type="radio" name="show" value="x"><span>Empty or error</span></label>
      </div>
      <label>Sort by
        <select id="sort">
          <option value="size">Size, largest first</option>
          <option value="name">Name</option>
          <option value="oldest">Last file activity, oldest first</option>
          <option value="newest">Last file activity, newest first</option>
        </select>
      </label>
      <form id="find" role="search" onsubmit="return false">
        <input type="search" id="q" placeholder="Find a folder by name" aria-label="Find a folder by name">
        <button class="btn" type="submit">Find</button>
      </form>
      <label>Show levels <select id="levels"><option value="">Choose</option></select></label>
      <button class="btn" type="button" id="to-unused">Open to unused folders</button>
      <button class="btn" type="button" id="expand">Expand all</button>
      <button class="btn" type="button" id="collapse">Collapse all</button>
    </div>
    <p class="tree-note" id="tree-note" aria-live="polite"></p>
    <p class="pdf-note" id="pdf-note" hidden></p>
    <div class="scroll"><table class="tree">
      <thead><tr><th>Folder</th><th>Last file activity</th><th>Folder modified</th>
        <th class="num">Files</th><th class="num">In period</th><th class="num">Size</th>
        <th class="num">Not used inside</th><th>Share of parent</th></tr></thead>
      <tbody id="rows"></tbody>
    </table></div>
  </section>

  <section>
    <h2>Scan details</h2>
    <dl class="details" id="details"></dl>
  </section>
</div>
<script type="application/json" id="report-data">__DATA__</script>
<script>
(function () {
  "use strict";
  var D = JSON.parse(document.getElementById("report-data").textContent);
  var R = D.rows, N = R.length, S = D.summary, M = D.meta;
  var PARENT = 0, NAME = 1, COLOR = 2, SIZE = 3, FILES = 4, INP = 5, LAST = 6, OWN = 7, WHY = 8,
      UNUSED = 9;
  var NF = new Intl.NumberFormat("en-US");
  function nf(n) { return NF.format(n); }
  function fmtSize(n) {
    var u = ["B", "KB", "MB", "GB", "TB"], k = 0;
    while (n >= 1024 && k < 4) { n /= 1024; k++; }
    return k === 0 ? Math.round(n) + " B" : n.toFixed(1) + " " + u[k];
  }
  function pct(part, whole) {
    if (!whole) return "0%";
    var f = part / whole;
    if (f > 0 && f < 0.005) return "<1%";
    return Math.round(f * 100) + "%";
  }
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }

  var kids = [];
  for (var i = 0; i < N; i++) kids.push([]);
  for (i = 1; i < N; i++) kids[R[i][PARENT]].push(i);

  function path(i) {
    var parts = [];
    while (i > 0) { parts.push(R[i][NAME]); i = R[i][PARENT]; }
    var root = R[0][NAME];
    if (!parts.length) return root;
    parts.reverse();
    return (root.endsWith(D.sep) ? root : root + D.sep) + parts.join(D.sep);
  }
  function reason(i) {
    var r = R[i];
    if (r[WHY]) return r[WHY];
    if (D.folder_basis) {
      return r[COLOR] === "g"
        ? "USED in the period\n- The folder itself was modified " + r[OWN] + ", inside the period (" + D.period + ")."
        : "NOT used in the period\n- The folder itself was last modified " + r[OWN] + ", outside the period (" + D.period + ").";
    }
    return r[COLOR] === "g"
      ? "USED in the period\n- " + nf(r[INP]) + " of " + nf(r[FILES]) + " file(s) inside were " + D.activity +
        " within the period (" + D.period + "), even if the folder's own date is older. Last file activity: " + r[LAST] + "."
      : "NOT used in the period\n- None of the " + nf(r[FILES]) + " file(s) inside were " + D.activity +
        " within the period (" + D.period + "). Last file activity: " + r[LAST] + ".";
  }

  /* ---------- header + overview ---------- */
  var total = S.total, C = S.colors;
  document.getElementById("root-path").textContent = M.root;
  /* set after the h1 text above: assigning textContent would remove the logo */
  var logo = document.createElement("img");
  logo.src = "data:image/png;base64," + D.icon;
  logo.alt = "TreeRot logo";
  logo.width = 40; logo.height = 40;
  document.querySelector("h1").prepend(logo);
  document.getElementById("period").textContent = "Activity period: " + D.period;
  document.getElementById("generated").textContent = "Scanned " + M.scanned_at;
  document.getElementById("finding").textContent = total === 0
    ? "No files were found in this folder."
    : (C.red.bytes === 0
      ? "Every folder that holds files was used " + D.period_phrase + "."
      : pct(C.red.bytes, total) + " of the storage here (" + fmtSize(C.red.bytes) + " in " + nf(C.red.files) +
        " files) is in folders where no file was " + D.activity + " " + D.period_phrase + ".");

  var strip = document.getElementById("strip");
  var top = kids[0].slice().sort(function (a, b) { return R[b][SIZE] - R[a][SIZE]; });
  var shown = top.slice(0, 60), rest = top.slice(60);
  function segTitle(name, size, unused) {
    return name + ": " + fmtSize(size) + (unused ? ", of which " + fmtSize(unused) + " (" +
      pct(unused, size) + ") is not used" : ", all of it used");
  }
  var segs = shown.map(function (i) {
    return { i: i, size: R[i][SIZE], unused: R[i][UNUSED], label: R[i][NAME],
             title: segTitle(R[i][NAME], R[i][SIZE], R[i][UNUSED]) };
  });
  if (rest.length) {
    var rs = rest.reduce(function (s, i) { return s + R[i][SIZE]; }, 0);
    var ru = rest.reduce(function (s, i) { return s + R[i][UNUSED]; }, 0);
    if (rs > 0) segs.push({ i: null, size: rs, unused: ru, label: nf(rest.length) + " smaller folders",
                            title: segTitle(nf(rest.length) + " smaller folders", rs, ru) });
  }
  var inKids = top.reduce(function (s, i) { return s + R[i][SIZE]; }, 0);
  var direct = R[0][SIZE] - inKids;
  if (direct > 0) {
    var du = Math.max(0, R[0][UNUSED] - top.reduce(function (s, i) { return s + R[i][UNUSED]; }, 0));
    segs.push({ i: null, size: direct, unused: du, label: "files in the top folder",
                title: segTitle("Files directly in the top folder", direct, du) });
  }
  if (total > 0) {
    segs.forEach(function (s) {
      var w = 100 * s.size / total;
      if (w <= 0) return;
      var seg = el("div", "seg"); seg.setAttribute("role", "listitem");
      seg.style.width = w + "%";
      var b = el("button", s.i === null ? "static" : ""); b.type = "button";
      b.title = s.title; b.setAttribute("aria-label", s.title);
      var used = el("i", "g"); used.style.width = (100 * (s.size - s.unused) / s.size) + "%";
      var unused = el("i", "r"); unused.style.width = (100 * s.unused / s.size) + "%";
      b.appendChild(used); b.appendChild(unused);
      if (s.i !== null) b.addEventListener("click", function () { showInTree(s.i); });
      else b.tabIndex = -1;
      seg.appendChild(b);
      seg.appendChild(el("span", "", w >= 7 ? s.label : ""));
      strip.appendChild(seg);
    });
    document.getElementById("strip-note").textContent =
      "Each block is a folder directly under " + M.root + ", sized by storage. The red part is " +
      "storage inside it that was not used. Select a block to find the folder in the tree.";
  }

  var figs = document.getElementById("figures");
  [["g", "Used in the period", C.green], ["r", "Not used in the period", C.red], ["x", "Empty or unreadable", C.gray]]
    .forEach(function (f) {
      var d = el("div", "fig " + f[0]);
      d.appendChild(el("h3", "", f[1]));
      d.appendChild(el("div", "size", fmtSize(f[2].bytes)));
      d.appendChild(el("p", "", f[0] === "x"
        ? nf(f[2].folders) + " folders: " + nf(f[2].empty) + " empty, " + nf(f[2].unreadable) + " could not be opened"
        : pct(f[2].bytes, total) + " of storage, " + nf(f[2].files) + " files in " + nf(f[2].folders) + " folders"));
      figs.appendChild(d);
    });
  document.getElementById("byfile").textContent = total === 0 ? "" :
    "Counting individual files instead of folders: " + fmtSize(S.period_bytes) + " (" + pct(S.period_bytes, total) +
    ") in " + nf(S.period_files) + " files was " + D.activity + " in the period, and " +
    fmtSize(total - S.period_bytes) + " (" + pct(total - S.period_bytes, total) + ") in " +
    nf(S.files - S.period_files) + " files was not. A used folder can still hold many old files.";
  var notices = document.getElementById("notices");
  function notice(t) { notices.appendChild(el("p", "notice", t)); }
  if (M.canceled) notice("This scan was canceled before it finished, so the figures cover only the part that was scanned.");
  if (S.unreadable) notice(nf(S.unreadable) + " folder(s) could not be opened, usually because of missing permissions. " +
    "Their contents are not counted, so the real totals may be higher. Show \u201cEmpty or error\u201d in the tree to find them.");

  /* ---------- largest unused ---------- */
  var ub = document.getElementById("unused-rows");
  document.getElementById("unused-lead").textContent = D.top_red.length
    ? (D.red_top_count > D.top_red.length
        ? "The " + D.top_red.length + " largest of " + nf(D.red_top_count) + " unused folders. "
        : "") + "Each one is unused as a whole: nothing inside it was " + D.activity + " " + D.period_phrase + "."
    : "There are no unused folders in this scan.";
  if (!D.top_red.length) document.querySelector("#unused-section .scroll").hidden = true;
  D.top_red.forEach(function (i) {
    var tr = el("tr");
    tr.appendChild(el("td", "path", path(i)));
    tr.appendChild(el("td", "num", fmtSize(R[i][SIZE])));
    var td = el("td", "num"); td.style.textAlign = "left";
    var bar = el("span", "share"); var fill = el("i");
    fill.style.width = Math.max(1, 100 * R[i][SIZE] / (C.red.bytes || 1)) + "%";
    bar.appendChild(fill); td.appendChild(bar); td.appendChild(document.createTextNode(pct(R[i][SIZE], total)));
    tr.appendChild(td);
    tr.appendChild(el("td", "num", nf(R[i][FILES])));
    tr.appendChild(el("td", "date", R[i][LAST] || "\u2013"));
    var b = el("button", "linkbtn", "Show in tree"); b.type = "button";
    b.addEventListener("click", function () { showInTree(i); });
    var bt = el("td"); bt.appendChild(b); tr.appendChild(bt);
    ub.appendChild(tr);
  });

  /* ---------- tree ---------- */
  var open = new Set([0]), visible = null, hits = new Set(), filter = "all";
  var tbody = document.getElementById("rows"), note = document.getElementById("tree-note");

  function sortKids(mode) {
    var key;
    if (mode === "name") key = function (a, b) { return R[a][NAME].localeCompare(R[b][NAME]); };
    else if (mode === "oldest") key = function (a, b) { return (R[a][LAST] || "").localeCompare(R[b][LAST] || ""); };
    else if (mode === "newest") key = function (a, b) { return (R[b][LAST] || "").localeCompare(R[a][LAST] || ""); };
    else key = function (a, b) { return R[b][SIZE] - R[a][SIZE]; };
    kids.forEach(function (k) { k.sort(key); });
  }
  function visKids(i) {
    return visible ? kids[i].filter(function (c) { return visible.has(c); }) : kids[i];
  }
  function setFilter(f) {
    filter = f; levelsStale();
    document.querySelector('input[name=show][value="' + f + '"]').checked = true;
    if (f === "all") { visible = null; return; }
    visible = new Set();
    for (var i = 0; i < N; i++) {
      if (R[i][COLOR] !== f) continue;
      var j = i;
      while (j >= 0 && !visible.has(j)) { visible.add(j); j = j === 0 ? -1 : R[j][PARENT]; }
    }
  }
  function openAncestors(i) {
    var j = i === 0 ? -1 : R[i][PARENT];
    while (j >= 0) { open.add(j); j = j === 0 ? -1 : R[j][PARENT]; }
  }
  function makeRow(i, lvl) {
    var r = R[i], tr = el("tr", "c-" + r[COLOR] + (hits.has(i) ? " hit" : ""));
    tr.dataset.i = i;
    tr.title = path(i) + "\n" + reason(i);
    var td = el("td", "name"); td.style.paddingLeft = (10 + lvl * 20) + "px";
    if (visKids(i).length) {
      var b = el("button", "tg", "\u25B8"); b.type = "button"; b.dataset.i = i;
      b.setAttribute("aria-expanded", open.has(i) ? "true" : "false");
      b.setAttribute("aria-label", (open.has(i) ? "Collapse " : "Expand ") + r[NAME]);
      td.appendChild(b);
    } else td.appendChild(el("span", "tg-space"));
    td.appendChild(el("span", "", r[NAME]));
    tr.appendChild(td);
    tr.appendChild(el("td", "date", r[LAST] || "\u2013"));
    tr.appendChild(el("td", "date", r[OWN] || "\u2013"));
    tr.appendChild(el("td", "num", nf(r[FILES])));
    tr.appendChild(el("td", "num", nf(r[INP])));
    tr.appendChild(el("td", "num", fmtSize(r[SIZE])));
    tr.appendChild(el("td", "num", r[UNUSED] ? fmtSize(r[UNUSED]) + (r[COLOR] === "r" ? "" :
      " (" + pct(r[UNUSED], r[SIZE]) + ")") : "\u2013"));
    var ps = i === 0 ? r[SIZE] : R[r[PARENT]][SIZE];
    var share = ps ? r[SIZE] / ps : 0;
    var pc = el("td", "date"), bar = el("span", "bar"), fill = el("i");
    fill.style.width = (share * 100) + "%"; bar.appendChild(fill); pc.appendChild(bar);
    pc.appendChild(document.createTextNode(i === 0 ? "100%" : pct(r[SIZE], ps)));
    tr.appendChild(pc);
    return tr;
  }
  function render() {
    var frag = document.createDocumentFragment(), stack = [[0, 0]], count = 0;
    while (stack.length) {
      var it = stack.pop(), i = it[0], lvl = it[1];
      if (visible && !visible.has(i)) continue;
      frag.appendChild(makeRow(i, lvl)); count++;
      if (open.has(i)) {
        var ks = visKids(i);
        for (var k = ks.length - 1; k >= 0; k--) stack.push([ks[k], lvl + 1]);
      }
    }
    tbody.replaceChildren(frag);
    return count;
  }
  function rowEl(i) { return tbody.querySelector('tr[data-i="' + i + '"]'); }
  function showInTree(i) {
    if (visible && !visible.has(i)) setFilter("all");
    levelsStale(); openAncestors(i); render();
    var tr = rowEl(i);
    if (tr) {
      tr.scrollIntoView({ block: "center", behavior: "smooth" });
      tr.classList.remove("flash"); void tr.offsetWidth; tr.classList.add("flash");
      var b = tr.querySelector(".tg");
      if (b) b.focus({ preventScroll: true });
    }
  }

  tbody.addEventListener("click", function (e) {
    var b = e.target.closest(".tg");
    if (!b) return;
    var i = +b.dataset.i;
    levelsStale();
    if (open.has(i)) open.delete(i); else open.add(i);
    render();
    var nb = rowEl(i) && rowEl(i).querySelector(".tg");
    if (nb) nb.focus({ preventScroll: true });
  });
  document.querySelectorAll("input[name=show]").forEach(function (r) {
    r.addEventListener("change", function () {
      setFilter(r.value); render();
      note.textContent = r.value === "all" ? "" : "Showing matching folders and the folders that contain them.";
    });
  });
  document.getElementById("sort").addEventListener("change", function (e) { sortKids(e.target.value); render(); });
  document.getElementById("collapse").addEventListener("click", function () {
    levelsStale(); open = new Set([0]); render(); note.textContent = "";
  });
  document.getElementById("expand").addEventListener("click", function () {
    var total = visible ? visible.size : N;
    if (total > 20000 && !window.confirm("This opens all " + nf(total) +
        " folders, which can make the page slow for a while. Continue?")) return;
    var q = [0], head = 0;
    levelsStale(); open = new Set();
    while (head < q.length) {
      var i = q[head++], ks = visKids(i);
      if (!ks.length) continue;
      open.add(i);
      for (var k = 0; k < ks.length; k++) q.push(ks[k]);
    }
    render();
    note.textContent = "All " + nf(total) + " folders are open.";
  });
  var levelSel = document.getElementById("levels");
  function levelsStale() { if (levelSel) levelSel.value = ""; }
  (function () {
    var sel = levelSel, deepest = 0, q = [[0, 0]], head = 0;
    while (head < q.length) {
      var it = q[head++], ks = visKids(it[0]);
      if (it[1] > deepest) deepest = it[1];
      for (var k = 0; k < ks.length; k++) q.push([ks[k], it[1] + 1]);
    }
    for (var n = 1; n <= Math.min(deepest, 20); n++) {
      var o = document.createElement("option");
      o.value = o.textContent = String(n);
      sel.appendChild(o);
    }
    var u = document.createElement("option");
    u.value = "all"; u.textContent = "Unlimited";
    sel.appendChild(u);
    sel.addEventListener("change", function () {
      if (sel.value === "all") {
        var chosen = open;
        document.getElementById("expand").click();
        if (open === chosen) sel.value = "";      // the prompt was cancelled
        else sel.value = "all";
        return;
      }
      if (!sel.value) return;
      var limit = +sel.value, st = [[0, 0]], h = 0, next = new Set();
      while (h < st.length) {
        var x = st[h++], kids = visKids(x[0]);
        if (x[1] >= limit || !kids.length) continue;
        next.add(x[0]);
        for (var j = 0; j < kids.length; j++) st.push([kids[j], x[1] + 1]);
      }
      var shown = st.length;
      if (shown > 20000 && !window.confirm("This opens about " + nf(shown) +
          " folders, which can make the page slow for a while. Continue?")) {
        sel.value = ""; return;
      }
      open = next;
      render();
      note.textContent = "Showing " + limit + " level" + (limit === 1 ? "" : "s") + ".";
    });
  })();
  document.getElementById("to-unused").addEventListener("click", function () {
    levelsStale();
    if (filter === "g" || filter === "x") setFilter("all");
    var first = null, n = 0;
    for (var i = 0; i < N; i++) {
      if (R[i][COLOR] === "r" && (i === 0 || R[R[i][PARENT]][COLOR] !== "r")) {
        openAncestors(i); n++; if (first === null) first = i;
      }
    }
    render();
    note.textContent = n ? "Opened the path to " + nf(n) + " unused folder(s)." : "There are no unused folders.";
    if (D.top_red.length) { var tr = rowEl(D.top_red[0]); if (tr) tr.scrollIntoView({ block: "center" }); }
  });
  document.getElementById("find").addEventListener("submit", function () {
    var q = document.getElementById("q").value.trim().toLowerCase();
    levelsStale();
    hits = new Set();
    if (!q) { render(); note.textContent = ""; return; }
    var byPath = q.indexOf("/") >= 0 || q.indexOf("\\") >= 0, found = [];
    for (var i = 0; i < N; i++) {
      var s = (byPath ? path(i) : R[i][NAME]).toLowerCase();
      if (s.indexOf(q) >= 0) found.push(i);
    }
    if (!found.length) { render(); note.textContent = "No folder name contains \u201c" + q + "\u201d."; return; }
    if (visible && found.some(function (i) { return !visible.has(i); })) setFilter("all");
    found.forEach(function (i) { hits.add(i); });
    found.slice(0, 300).forEach(openAncestors);
    render();
    note.textContent = nf(found.length) + " folder(s) match" + (found.length > 300 ? "; the first 300 are opened." : ".");
    var tr = rowEl(found[0]); if (tr) tr.scrollIntoView({ block: "center" });
  });
  sortKids("size");
  if (D.pdf) {
    var pg = document.createElement("style");
    pg.textContent = "@page { size: A4 landscape; margin: 11mm; }";
    document.head.appendChild(pg);
    var pn = document.getElementById("pdf-note");
    if (D.pdf.unused) {
      document.getElementById("to-unused").click();
      pn.textContent = "The tree shows the path to every unused folder.";
    } else {
      open = new Set();
      var lim = D.pdf.all ? Infinity : D.pdf.depth, lvl = [[0, 0]];
      for (var h = 0; h < lvl.length; h++) {
        if (lvl[h][1] < lim && kids[lvl[h][0]].length) {
          open.add(lvl[h][0]);
          kids[lvl[h][0]].forEach(function (c) { lvl.push([c, lvl[h][1] + 1]); });
        }
      }
      render();
      pn.textContent = D.pdf.all ? "The tree shows every folder, on all levels."
        : "The tree shows folders up to " + D.pdf.depth + " level" +
          (D.pdf.depth > 1 ? "s" : "") + " below the top folder.";
    }
    if (!D.pdf.all) pn.textContent += " The scan covered every level; the HTML version of this report has the complete tree, which you can expand and search.";
    pn.hidden = false;
  } else {
    render();
  }

  /* ---------- details ---------- */
  var dl = document.getElementById("details");
  function detail(k, v) { dl.appendChild(el("dt", "", k)); dl.appendChild(el("dd", "", v)); }
  detail("Scanned folder", M.root);
  detail("Activity period", D.period);
  detail("Counted as used", M.basis_note);
  detail("Excluded", M.excludes && M.excludes.length ? M.excludes.join(", ") + " (" + nf(M.excluded_count || 0) + " folders skipped)" : "Nothing");
  detail("Scanned at", M.scanned_at);
  if (M.elapsed !== null && M.elapsed !== undefined) {
    var s = Math.round(M.elapsed), h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60);
    detail("Scan time", (h ? h + " h " : "") + (h || m ? m + " min " : "") + (s % 60) + " s");
  }
  detail("Totals", nf(S.folders) + " folders, " + nf(S.files) + " files, " + fmtSize(total));
  if (M.computer) detail("Computer", M.computer);
  detail("Tool", "TreeRot " + D.version);
  detail("Credit", "Created by Arik Pinhasov, github.com/arikpinhasov1998");
})();
</script>
<footer style="margin:2rem 0 1rem;font-size:13px">TreeRot. Created by <a href="https://github.com/arikpinhasov1998">Arik Pinhasov</a>.</footer>
</body>
</html>
'''


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


ANSI = {GREEN: "\033[32m", RED: "\033[31m", GRAY: "\033[90m"}
ANSI_RESET = "\033[0m"
TAGS = {GREEN: "USED", RED: "UNUSED"}


def filter_rows(rows, show):
    """Return (matching rows, set of paths to display incl. ancestors or None for all)."""
    if show == "all":
        return list(rows), None
    want = {"red": RED, "green": GREEN, "gray": GRAY}[show]
    by_path = {r["info"].path: r for r in rows}
    matching = [r for r in rows if color_of(r) == want]
    visible = set()
    for r in matching:
        path = r["info"].path
        while path is not None and path not in visible:
            visible.add(path)
            path = by_path[path]["info"].parent
    return matching, visible


def summarize(rows, excluded=0, folder_basis=False, elapsed=None):
    by_path = {r["info"].path: r for r in rows}
    root = next((r for r in rows if r["info"].parent is None), None)
    if root is None:
        return None
    ri = root["info"]
    red_top = [r for r in rows if color_of(r, folder_basis) == RED and (
        r["info"].parent is None or color_of(by_path[r["info"].parent], folder_basis) != RED)]
    return {
        "root": ri.path, "folders": len(rows), "files": ri.total_files, "total": ri.total_size,
        "colors": storage_breakdown(rows, folder_basis),
        "period_files": ri.range_files, "period_bytes": ri.range_size,
        "red_top": len(red_top), "unreadable": sum(1 for r in rows if r["info"].unreadable),
        "excluded": excluded, "period": root["period"], "elapsed": elapsed,
        "activity": root.get("activity", "modified"),
        "folder_basis": folder_basis,
    }


def summary_text(sm, use_color=False):
    """Multi-line end-of-scan report: storage per color, plus the same split by file date."""
    def paint(color, text):
        return ANSI[color] + text + ANSI_RESET if use_color else text

    tot, c = sm["total"], sm["colors"]
    basis = ", colored by each folder's own date" if sm["folder_basis"] else ""
    lines = [f"Storage by folder color - {sm['root']}  (period: {sm['period']}{basis})"]
    for color in (GREEN, RED, GRAY):
        b = c[color]
        line = (f"  {SUMMARY_NAMES[color]:<22}{fmt_size(b['bytes']):>11}  "
                f"{pct_text(b['bytes'], tot):>5}  {b['files']:>13,} files  "
                f"{b['folders']:>11,} folders")
        if color == GRAY:
            line += f"  ({b['empty']:,} empty, {b['unreadable']:,} unreadable)"
        lines.append(paint(color, line))
    lines.append(f"  {'TOTAL':<22}{fmt_size(tot):>11}  {'100%' if tot else '0%':>5}  "
                 f"{sm['files']:>13,} files  {sm['folders']:>11,} folders")
    pf, pb = sm["period_files"], sm["period_bytes"]
    lines.append(f"By file date: {fmt_size(pb)} ({pct_text(pb, tot)}) in {pf:,} files was "
                 f"{sm['activity']} in the period; {fmt_size(tot - pb)} "
                 f"({pct_text(tot - pb, tot)}) in {sm['files'] - pf:,} files was not.")
    notes = []
    if sm["red_top"]:
        notes.append(f"unused data sits in {sm['red_top']:,} top-level red folder(s)")
    if sm["excluded"]:
        notes.append(f"{sm['excluded']:,} folder(s) excluded")
    if sm["elapsed"] is not None:
        notes.append(f"scan time {fmt_duration(sm['elapsed'])}")
    if notes:
        lines.append(notes[0][0].upper() + "; ".join(notes)[1:] + ".")
    if sm["unreadable"]:
        lines.append(f"WARNING: {sm['unreadable']:,} folder(s) could not be opened - their "
                     "contents are NOT counted above, so the real totals may be higher.")
    return "\n".join(lines)


class CliProgress:
    """Progress on stderr: a live bar for terminals, or a timestamped line every 30 s for logs."""

    def __init__(self, mode, stream):
        self.mode, self.stream = mode, stream
        self.meter = ProgressMeter()
        self.last_line = 0.0
        enc = getattr(stream, "encoding", None) or "ascii"
        try:
            "\u2588\u2591".encode(enc)
            self.full, self.empty = "\u2588", "\u2591"
        except (UnicodeEncodeError, LookupError):
            self.full, self.empty = "#", "-"

    def _width(self):
        try:
            return max(40, os.get_terminal_size(self.stream.fileno()).columns - 1)
        except (OSError, ValueError, AttributeError):
            return 100

    def __call__(self, p):
        v = self.meter.update(p)
        pct, counts, times = progress_parts(p, v, " | ")
        if self.mode == "lines":
            now = time.monotonic()
            final = p["phase"] == "scan" and v["fraction"] >= 1.0
            if now - self.last_line < 30 and not final and self.last_line:
                return
            self.last_line = now
            self.stream.write(f"[{datetime.now():%H:%M:%S}] {pct} | {times} | {counts}\n")
        else:
            cols = self._width()
            if p["phase"] == "count":
                spin = "|/-\\"[int(v["elapsed"] * 4) % 4]
                line = f"{spin} {counts} | {times}"
            else:
                bar_w = max(10, min(30, cols // 5))
                filled = int(round(v["fraction"] * bar_w))
                # time first: if the terminal is narrow, the counts get cut, not the time left
                line = (f"[{self.full * filled}{self.empty * (bar_w - filled)}] {pct:>6} | "
                        f"{times} | {counts}")
            if len(line) > cols:
                line = line[:cols - 3] + "..."
            self.stream.write("\r" + line.ljust(cols))
        self.stream.flush()

    def finish(self):
        if self.mode == "bar":
            self.stream.write("\n")
            self.stream.flush()


def print_tree(rows, out, depth, show, sort, use_color):
    """Text version of the GUI tree: one line per folder, tagged USED / UNUSED / EMPTY / ERROR."""
    _, visible = filter_rows(rows, show)
    by_path = {r["info"].path: r for r in rows}
    kids = {}
    for r in rows:
        parent = r["info"].parent
        if parent is not None and (visible is None or r["info"].path in visible):
            kids.setdefault(parent, []).append(r)
    if sort == "name":
        key = lambda r: r["info"].path.lower()
    elif sort == "oldest":
        key = lambda r: r["info"].newest_file_mtime or 0
    elif sort == "newest":
        key = lambda r: -(r["info"].newest_file_mtime or 0)
    else:
        key = lambda r: -r["info"].total_size
    for lst in kids.values():
        lst.sort(key=key)

    root = next(r for r in rows if r["info"].parent is None)
    stack = [(root, 0)]
    while stack:
        r, level = stack.pop()
        i = r["info"]
        color = color_of(r)
        tag = TAGS.get(color) or ("ERROR" if r["status"] == "Error" else "EMPTY")
        name = i.path if i.parent is None else (os.path.basename(i.path.rstrip("/\\")) or i.path)
        children = kids.get(i.path, [])
        parent_size = by_path[i.parent]["info"].total_size if i.parent is not None else 0
        share = f"{i.total_size / parent_size:4.0%}" if parent_size else "    "
        line = (f"{'  ' * level}{name}  [{tag}]  {fmt_size(i.total_size)}  {share}  "
                f"files {i.total_files:,} ({i.range_files:,} in period)  "
                f"newest {fmt_ts(i.newest_file_mtime) or '-'}")
        if i.unreadable:
            line += f"  !! {i.error_msg}"
        elif i.unreadable_below and color != GRAY:
            line += f"  ! {i.unreadable_below:,} unreadable sub-folder(s) below"
        go_deeper = depth == 0 or level < depth
        if children and not go_deeper:
            line += f"  (+{len(children):,} sub-folder(s) not shown)"
        out.write((ANSI[color] + line + ANSI_RESET if use_color else line) + "\n")
        if go_deeper:
            stack.extend((c, level + 1) for c in reversed(children))


def read_exclude_file(path):
    with open(path, encoding="utf-8-sig") as f:
        return [ln.strip() for ln in f if ln.strip() and not ln.lstrip().startswith("#")]


STATUS_STALE_SECONDS = 120      # a "running" status not refreshed for this long is dead or stuck


class StatusWriter:
    """Keeps a small JSON file up to date, so a window can follow a scan running elsewhere.

    Each write goes to a temporary file that then replaces the real one, so a reader never
    sees a half-written file. A failed write is ignored: it must never stop a scan.
    A heartbeat thread rewrites the latest data every HEARTBEAT seconds, so "updated" stays
    fresh while the report is made or the share is slow; a reader treats an old "updated"
    on a "running" file as a dead scan (see status_is_stale). Writes are serialized by a
    lock. The scan never waits for it: update() skips a write if another is in progress."""

    INTERVAL = 5
    HEARTBEAT = 30
    FINISH_TIMEOUT = 15            # finish() never waits longer than this in all
    LOCK_WAIT = 10                 # longest finish() waits for a write that is stuck
    FINISH_TRIES = 8
    RETRY_DELAY = 0.25

    def __init__(self, path, report=None):
        self.path, self.report = path, report
        self.meter = ProgressMeter()
        self.last = None
        self.error_text = ""
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._latest = ("running", "", "", "", "")
        self._finished = False
        self._finish_lock = threading.Lock()
        self._final_thread = None
        self._write("running")
        self._thread = threading.Thread(target=self._heartbeat, name="status-heartbeat",
                                        daemon=True)
        try:
            self._thread.start()
        except RuntimeError:
            pass                   # no heartbeat is better than no scan

    def _data(self, state, percent, counts, times, error):
        return {"state": state, "percent": percent, "counts": counts, "times": times,
                "updated": time.time(), "report": self.report, "error": error}

    def _write(self, state, percent="", counts="", times="", error="", wait=-1):
        """Write now. wait = seconds to wait for another write to end (-1 forever, 0 not at
        all). True if the file was written."""
        self._latest = (state, percent, counts, times, error)
        return self._locked_write(self._data(*self._latest), wait)

    def _locked_write(self, data, wait):
        if not self._lock.acquire(timeout=wait):
            return False
        try:
            if self._stop.is_set() and data["state"] == "running":
                return False           # finish() has run: never turn its state back
            return self._write_file(data)
        finally:
            self._lock.release()

    def _write_file(self, data):
        """One attempt to replace the status file. True if it worked."""
        tmp = f"{self.path}.{os.getpid()}.tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f)
            os.replace(tmp, self.path)
            return True
        except (OSError, ValueError, TypeError):
            try:
                os.remove(tmp)
            except OSError:
                pass                   # a status problem must never stop the scan
            return False

    def _heartbeat(self):
        while not self._stop.wait(self.HEARTBEAT):
            self._beat()

    def _beat(self):
        with self._lock:               # this thread may block; the scan never does
            if self._stop.is_set():    # finish() has begun: never overwrite its state
                return
            self._write_file(self._data(*self._latest))

    def update(self, p):
        try:
            v = self.meter.update(p)
            now = time.monotonic()
            if self.last is None or now - self.last >= self.INTERVAL:
                pct, counts, times = progress_parts(p, v, "  \u00b7  ")
                if self._write("running", pct, counts, times, wait=0):
                    self.last = now    # if skipped, try again on the next report
        except Exception:
            pass                       # progress text is never worth stopping a scan for

    def finish(self, state, error=""):
        """Write the final state, retrying: on Windows a reader holding the file open makes
        the replace fail, and nothing would ever correct a stale "running". True if written.
        The writes run on a daemon thread and finish() waits at most FINISH_TIMEOUT for it, so
        a stalled share can never hang the program or keep it from exiting."""
        with self._finish_lock:            # never held during file I/O
            if self._stop.is_set():
                return self._finished      # already finished: the first result stands
            self._stop.set()
            if state != "finished":
                self.report = None         # only a finished scan has a report to point at
            self._final_thread = threading.Thread(
                target=self._final_writes, args=(state, error), name="status-final",
                daemon=True)
        try:
            self._final_thread.start()
        except RuntimeError:
            return False
        self._final_thread.join(self.FINISH_TIMEOUT)
        self._thread.join(0.1)
        return self._finished

    def _final_writes(self, state, error):
        try:
            for i in range(self.FINISH_TRIES):
                if i:
                    time.sleep(self.RETRY_DELAY)
                if not self._lock.acquire(timeout=self.LOCK_WAIT):
                    return                 # a write is stuck (stalled share): give up
                try:
                    ok = self._write_file(self._data(
                        state, "100%" if state == "finished" else "", "", "", error))
                finally:
                    self._lock.release()
                if ok:
                    self._finished = True
                    return
        except Exception:
            pass                           # a status problem must never stop the scan


def status_is_stale(data, now=None):
    """True if a status dict says "running" but has not been refreshed for
    STATUS_STALE_SECONDS: the scan is dead or its share is stuck."""
    if not data or data.get("state") != "running":
        return False
    try:
        age = (time.time() if now is None else now) - float(data["updated"])
    except (KeyError, TypeError, ValueError):
        return True
    return age > STATUS_STALE_SECONDS


def read_status(path):
    """The status file as a dict, or None if it is missing, unreadable or not a status file
    (no known state), so a reader can index data["state"] safely."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    ok = isinstance(data, dict) and data.get("state") in ("running", "finished", "failed")
    return data if ok else None


def run_cli(a, root):
    """Headless scan. Returns a process exit code."""
    if not a.status_file:
        return _run_cli(a, root)
    status = StatusWriter(a.status_file, os.path.abspath(a.report) if a.report else None)
    try:
        rc = _run_cli(a, root, status)
    except BaseException as e:
        status.finish("failed", str(e) or type(e).__name__)
        raise
    if rc == 0:
        status.finish("finished")
    else:
        status.finish("failed", status.error_text or f"The scan failed (exit code {rc}).")
    return rc


def _run_cli(a, root, status=None):
    """Headless scan. Returns a process exit code."""
    if not os.path.isdir(root):
        text = f"Error: '{root}' is not a folder, or it is not reachable from here."
        sys.stderr.write(text + "\n")
        if status:
            status.error_text = text
        return 2
    if a.date_from or a.date_to:
        d_from, d_to = a.date_from, a.date_to
        if d_from and d_to and d_from > d_to:
            sys.stderr.write("Error: --from is later than --to.\n")
            if status:
                status.error_text = "Error: --from is later than --to."
            return 2
    else:
        d_from, d_to = datetime.now() - timedelta(days=365.25 * (a.years or 2.0)), None

    excludes = list(a.exclude or [])
    if a.exclude_common:
        excludes += COMMON_EXCLUDES
    if a.exclude_file:
        try:
            excludes += read_exclude_file(a.exclude_file)
        except OSError as e:
            sys.stderr.write(f"Error: cannot read --exclude-file: {e}\n")
            if status:
                status.error_text = f"Cannot read the exclude file: {e}"
            return 2

    show = "red" if a.stale_only else a.show
    fmt = a.format
    if fmt == "auto":
        fmt = "tree" if (sys.stdout.isatty() and not a.output) else "csv"

    # Console / pipe encoding: never crash on non-ASCII (e.g. Hebrew) folder names.
    try:
        sys.stdout.reconfigure(encoding=None if sys.stdout.isatty() else "utf-8",
                               errors="replace")
    except (AttributeError, ValueError, OSError):
        pass
    use_color = (a.color == "always" or (
        a.color == "auto" and sys.stdout.isatty() and not a.output
        and "NO_COLOR" not in os.environ and os.environ.get("TERM") != "dumb"))
    if use_color and sys.platform == "win32":
        os.system("")                       # switches on ANSI colors in the Windows console

    err_color = (a.color == "always" or (
        a.color == "auto" and sys.stderr.isatty()
        and "NO_COLOR" not in os.environ and os.environ.get("TERM") != "dumb"))
    if err_color and not use_color and sys.platform == "win32":
        os.system("")                       # switches on ANSI colors in the Windows console

    pmode = "none" if a.quiet else a.progress
    if pmode == "auto":
        pmode = "bar" if sys.stderr.isatty() else "none"
    printer = CliProgress(pmode, sys.stderr) if pmode != "none" else None
    if status:
        def reporter(p):
            status.update(p)
            if printer:
                printer(p)
    else:
        reporter = printer

    t0 = time.monotonic()
    scan_started = datetime.now()
    settings = load_settings()
    tkey = totals_key(root, excludes, a.follow_symlinks)
    with keep_awake() as awake_note:
        if awake_note and not a.quiet:
            sys.stderr.write(awake_note + "\n")
        totals, exact = None, True
        if a.precount:
            totals = count_tree(root, progress_cb=reporter, follow_symlinks=a.follow_symlinks,
                                excludes=excludes)
        else:
            totals, exact = last_totals(settings, tkey), False
        stats = {}
        folders, _ = scan_tree(
            root, progress_cb=reporter, excludes=excludes, stats=stats,
            follow_symlinks=a.follow_symlinks,
            date_from_ts=d_from.timestamp() if d_from else None,
            date_to_ts=d_to.timestamp() if d_to else None, totals=totals, totals_exact=exact,
            created=a.created)
    if printer:
        printer.finish()
    uses_created = a.created == "ctime" or (a.created == "auto" and CREATED_NATIVE)
    rows = build_rows(folders, d_from, d_to,
                      "modified or created" if uses_created else "modified")
    if rows:                                # finished: remember totals for the next progress bar
        root_info = next(r["info"] for r in rows if r["info"].parent is None)
        remember_totals(settings, tkey, len(rows), root_info.total_files)
        save_settings(settings)
    if status and not rows:
        status.report = None                # no report is written without rows: claim none
    sm = summarize(rows, stats.get("excluded", 0), elapsed=time.monotonic() - t0)
    if a.report and rows:
        activity = "modified or created" if uses_created else "modified"
        meta = {
            "root": next(r["info"].path for r in rows if r["info"].parent is None),
            "excludes": excludes, "excluded_count": stats.get("excluded", 0),
            "scanned_at": scan_started.strftime("%Y-%m-%d %H:%M"),
            "elapsed": time.monotonic() - t0, "canceled": False, "activity": activity,
            "computer": socket.gethostname(), "basis_note": basis_note(False, activity),
        }
        if not a.quiet and a.report.lower().endswith(".pdf"):
            n_pdf = pdf_tree_rows(rows, a.report_tree)
            sys.stderr.write(f"Creating the PDF report ({n_pdf:,} folders in the tree, roughly "
                             f"{estimate_pdf_pages(n_pdf):,} pages)...\n")
        try:
            write_report(a.report, rows, meta, pdf_tree=a.report_tree, browser=a.browser)
        except ReportError as e:
            sys.stderr.write(f"Error: {e}\n")
            if status:
                status.error_text = str(e)
            return 2
        except OSError as e:
            sys.stderr.write(f"Error: cannot write the report to {a.report}: {e}\n")
            if status:
                status.error_text = f"Cannot write the report to {a.report}: {e}"
            return 2
        if not a.quiet:
            sys.stderr.write(f"Wrote report {a.report}\n")

    to_file = None
    try:
        if fmt == "csv":
            matching, _ = filter_rows(rows, show)
            if a.output:
                write_csv(a.output, matching)
            else:
                w = csv.writer(sys.stdout, lineterminator="\n")
                w.writerow(CSV_HEADERS)
                for r in matching:
                    w.writerow(row_to_csv(r))
            if sm and not a.quiet:
                sys.stderr.write(summary_text(sm, err_color) + "\n")
        else:
            out = sys.stdout
            if a.output:
                to_file = out = open(a.output, "w", encoding="utf-8")
            if fmt == "tree" and rows:
                print_tree(rows, out, a.depth, show, a.sort, use_color and not a.output)
                out.write("\n")
            if sm:                          # storage summary comes last, at the end of the scan
                out.write(summary_text(sm, use_color and not a.output) + "\n")
    except BrokenPipeError:                 # e.g. "... | head"
        try:
            sys.stdout = open(os.devnull, "w")
        except OSError:
            pass
        return 0
    finally:
        if to_file:
            to_file.close()
    if a.output and not a.quiet:
        sys.stderr.write(f"Wrote {a.output}\n")
    return 0


def ensure_std_streams():
    """
    A windowed (no-console) .exe starts with sys.stdout / sys.stderr set to None, which would
    crash --cli and --help. On Windows we re-attach to the console that launched us (if any);
    otherwise output is discarded instead of raising errors.
    """
    if sys.stdout is not None and sys.stderr is not None:
        return
    if sys.platform == "win32":
        try:
            import ctypes
            if ctypes.windll.kernel32.AttachConsole(-1):     # -1 = the parent's console
                if sys.stdout is None:
                    sys.stdout = open("CONOUT$", "w", encoding="utf-8")
                if sys.stderr is None:
                    sys.stderr = open("CONOUT$", "w", encoding="utf-8")
        except Exception:
            pass
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")


def _pdf_tree_arg(text):
    try:
        return parse_pdf_tree(text)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"'{text}' is not a number of levels (1 or more), 'all' or 'unused'")


def _depth_arg(text):
    if str(text).strip().lower() in ("all", "unlimited"):
        return 0
    try:
        n = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"'{text}' is not a number of levels or 'all'")
    if n < 0:
        raise argparse.ArgumentTypeError("the number of levels cannot be negative")
    return n


def build_parser():
    ap = argparse.ArgumentParser(
        prog="treerot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=("Find which folders are (and are not) in use. With no PATH the graphical "
                     "interface opens. With a PATH it runs headless: no display and no tkinter "
                     "needed, so it works over SSH, in cron and in Task Scheduler."),
        epilog=("examples:\n"
                "  treerot.py /srv/share --format tree --depth 3\n"
                "  treerot.py /srv/share --from 2024-10-28 --show red -o unused.csv\n"
                "  treerot.py \\\\server\\share --exclude-common --format summary\n"
                "\n"
                "colors / tags: USED = a file inside changed in the period, UNUSED = none did,\n"
                "EMPTY / ERROR = no files, or the folder could not be opened.\n"
                "exit codes: 0 ok, 2 bad arguments or path, 3 GUI unavailable, 130 interrupted.\n"
                "tip: on Windows do not end a quoted path with a backslash (use \"C:\\Data\", "
                "not \"C:\\Data\\\")."))
    ap.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}\n{CREDIT}\n{CREDIT_URL}")
    ap.add_argument("path", nargs="?", metavar="PATH",
                    help="folder or share to scan (runs headless); omit to open the GUI")
    ap.add_argument("--cli", nargs="?", const="", metavar="PATH",
                    help="same as giving PATH (kept for compatibility)")
    g = ap.add_argument_group("period")
    g.add_argument("--from", dest="date_from", metavar="YYYY-MM-DD",
                   type=lambda t: parse_date(t), help="period start date")
    g.add_argument("--to", dest="date_to", metavar="YYYY-MM-DD",
                   type=lambda t: parse_date(t, end_of_day=True),
                   help="period end date, inclusive (default: no end)")
    g.add_argument("--years", type=float, default=None,
                   help="shortcut for --from (today minus N years); default 2 if no dates given")
    g.add_argument("--created", choices=["auto", "ctime", "off"], default="auto",
                   help="also count files CREATED in the period as used (a copied file keeps its "
                        "old modified date). auto = real creation date on Windows/macOS, not "
                        "available on Linux; ctime = on Linux use the change time instead (also "
                        "updated by renames and permission changes); off = modified date only "
                        "(default: auto)")
    g = ap.add_argument_group("what to skip")
    g.add_argument("--exclude", action="append", metavar="NAME_OR_PATH",
                   help="folder name, wildcard or path to skip (repeatable)")
    g.add_argument("--exclude-common", action="store_true",
                   help="also skip common system / snapshot / recycle-bin folders")
    g.add_argument("--exclude-file", metavar="FILE",
                   help="text file with one exclusion per line (# starts a comment)")
    g.add_argument("--follow-symlinks", action="store_true",
                   help="follow symbolic links (risk of loops)")
    g = ap.add_argument_group("output")
    g.add_argument("--format", choices=["auto", "csv", "tree", "summary"], default="auto",
                   help="auto = tree when printing to a terminal, otherwise csv (default)")
    g.add_argument("-o", "--output", metavar="FILE", help="write the result to FILE")
    g.add_argument("--report", metavar="FILE",
                   help="also write a report: storage summary, largest unused folders and the "
                        "color-coded folder tree. FILE.html = interactive (expand folders, search) "
                        "in any browser; FILE.pdf = fixed pages, printed with Edge/Chrome/Chromium")
    g.add_argument("--report-tree", type=_pdf_tree_arg, default="2", metavar="N|all|unused",
                   help="PDF only: how much of the tree to print - N levels below the top folder, "
                        "'all' for every level (unlimited), or 'unused' for the path to every "
                        "unused folder (default 2). The scan itself always covers every level.")
    g.add_argument("--browser", metavar="PATH",
                   help="PDF only: browser to print with, if it is not found automatically")
    g.add_argument("--status-file", metavar="FILE",
                   help="keep FILE up to date with the scan's progress and result, as JSON "
                        "(used by background scans)")
    g.add_argument("--show", choices=["all", "red", "green", "gray"], default="all",
                   help="only folders that are unused (red), used (green) or empty/error (gray)")
    g.add_argument("--stale-only", action="store_true", help="same as --show red")
    g.add_argument("--depth", type=_depth_arg, default=3, metavar="N|all",
                   help="tree format: levels to show below the start folder, 'all' (or 0) for "
                        "every level (default 3). The scan itself always covers every level.")
    g.add_argument("--sort", choices=["size", "name", "oldest", "newest"], default="size",
                   help="tree format: order of sibling folders (default: largest first)")
    g.add_argument("--color", choices=["auto", "always", "never"], default="auto",
                   help="tree format: ANSI colors (default: only on a terminal)")
    g.add_argument("--progress", choices=["auto", "bar", "lines", "none"], default="auto",
                   help="progress on stderr: bar = live bar for terminals, lines = one status "
                        "line every 30 s for log files, none; auto = bar on a terminal, "
                        "otherwise none (default)")
    g.add_argument("--precount", action="store_true",
                   help="count folders and files first, so the percentage, totals and time left "
                        "are exact instead of estimated (slower: the tree is listed twice)")
    g.add_argument("-q", "--quiet", action="store_true", help="no progress or summary on stderr")
    ap.add_argument("--preload", metavar="PATH", help=argparse.SUPPRESS)
    return ap


def main(argv=None):
    ensure_std_streams()
    ap = build_parser()
    a = ap.parse_args(argv)
    if a.cli is not None and not (a.cli or a.path):
        ap.error("--cli needs a PATH")
    target = a.cli or a.path
    try:
        if target:
            return run_cli(a, target)
        run_gui(a.preload)
        return 0
    except KeyboardInterrupt:
        sys.stderr.write("\nInterrupted.\n")
        return 130


if __name__ == "__main__":
    sys.exit(main())
