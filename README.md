# Folder Activity Scanner

Scans a folder or network share and shows a TreeSize-style tree where every folder is
**green** (used in the period you choose), **red** (not used) or **gray** (empty or unreadable).
A folder counts as used when a file anywhere inside it was **modified or created** in the period,
even if the folder's own date is older. Hover over a folder to see *why* it has its color;
right-click to copy the reason or path.

At the end of a scan you see how much storage is used, unused and empty. Export a CSV, or a
**report** as HTML (interactive: open folders, search, filter) or PDF (fixed pages to print or send).
It runs on Windows, Linux and macOS, with a window or from the command line (for servers).

## Download

Go to the [**Releases**](../../releases/latest) page and download the file for your system:

| System | Download | What you get |
|---|---|---|
| Windows 10 / 11 | `FolderActivityScanner.exe` | The window. Double-click to start. |
| | `FolderActivityScanner-cli.exe` | The command line, for scripts and Task Scheduler. |
| Linux (x86-64) | `folder-activity-scanner-linux-x86_64.tar.gz` | One program for both the window and the command line. |
| macOS, Apple Silicon (M1 and later) | `FolderActivityScanner-macos-arm64.zip` | `FolderActivityScanner.app` and the command-line program `folder-activity-scanner`. |
| macOS, Intel | `FolderActivityScanner-macos-x86_64.zip` | The same, for Intel Macs. |

Nothing is installed. To check that a download is genuine, compare its SHA-256 hash with
`SHA256SUMS.txt` from the same release (`certutil -hashfile FILE SHA256` on Windows,
`shasum -a 256 FILE` on macOS, `sha256sum FILE` on Linux).

### First start

The programs are not code-signed, so each system warns the first time:

* **Windows:** "Windows protected your PC" - click **More info**, then **Run anyway**.
* **macOS:** "cannot be opened because Apple cannot check it" - open **System Settings >
  Privacy & Security**, scroll down and click **Open Anyway** next to the app's name. Or, in
  Terminal: `xattr -dr com.apple.quarantine FolderActivityScanner.app`.
  To scan a network share, also allow the app under **Privacy & Security > Files and Folders >
  Network Volumes**; without it every folder on the share shows as unreadable (gray).
* **Linux:** unpack and run:
  ```
  tar -xzf folder-activity-scanner-linux-x86_64.tar.gz
  ./folder-activity-scanner              # window (needs a desktop)
  ./folder-activity-scanner /srv/share   # command line
  ```
  The program needs glibc 2.35 or newer (Ubuntu 22.04+, Debian 12+, RHEL/Rocky 9+). On older
  systems run the Python file instead (see *Run from source*).

## Using the window

* Enter a folder or UNC path (`\\server\share`), set the **From** (and optional **To**) date, click **Scan**.
* Add **exclusions** (names, wildcards or paths) to skip things like `.snapshot` or `$RECYCLE.BIN`.
* A progress bar shows the percentage, folders and files done, elapsed time and time left.
  The first scan of a path is estimated (marked `~`); later scans of the same path use the last
  scan's totals and are close to exact. Tick **Count first** for exact numbers on a first scan
  (slower: the tree is read twice).
* **Export report...** lets you choose **HTML** or **PDF**. The PDF is printed with Microsoft
  Edge (built into Windows 10/11), Google Chrome or Chromium, so it shows Hebrew and other
  scripts correctly. Without one of those browsers (common on servers) PDF is unavailable and
  HTML still works.
* The scan always covers **every level** of the tree. Only the PDF has to choose how much of
  the tree to print, because it cannot expand folders: **up to N levels**, **all levels
  (unlimited)**, or **the path to every unused folder**. The dialog shows how many folders and
  roughly how many pages that gives before you save.
* Settings (last path, exclusions, last scan totals) are saved in `.folder_activity_scanner.json`
  in your home folder.

## Command line

Give a path and the window does not open, so it works over SSH, in cron and in Task Scheduler:

```
FolderActivityScanner-cli.exe "\\server\share" --from 2024-10-28 --format summary --report share.html
./folder-activity-scanner /srv/share --from 2024-10-28 --format summary --report share.pdf
./folder-activity-scanner /srv/share --format csv -o share.csv --progress lines 2>> scan.log
```

Useful options: `--to DATE`, `--exclude NAME_OR_PATH` (repeatable), `--exclude-common`,
`--format summary|tree|csv` (with `--depth N|all` for the tree), `--report FILE.html|FILE.pdf`
(with `--report-tree N|all|unused` and `--browser PATH` for PDF), `--progress bar|lines|none` (`lines` writes a status line every
30 s, for logs), `--precount`, `--created auto|ctime|off`. Run with `--help` for everything.

For Task Scheduler, use the **UNC path** (`\\server\share`), not a mapped drive letter: mapped
drives do not exist when a task runs on its own.

## Run from source

Requires Python 3.8 or newer and nothing else (standard library only):

```
python folder_activity_scanner.py                 # window
python folder_activity_scanner.py /srv/share      # command line
```

The window needs Python's tkinter: on Linux `sudo apt install python3-tk`; on macOS use Python
from python.org (Apple's built-in Python has an old, buggy Tk).

## Build the programs yourself

Each system can only build its own programs, so build on the system you want to run on:

| System | Command | Result in `dist/release/` |
|---|---|---|
| Windows | `build_exe.bat` | `FolderActivityScanner.exe`, `FolderActivityScanner-cli.exe` |
| Linux | `bash build.sh` | `folder-activity-scanner-linux-<arch>.tar.gz` |
| macOS | `bash build.sh` | `FolderActivityScanner-macos-<arch>.zip` |

The scripts create a private build environment in `.venv-build` and install the pinned build tool
(PyInstaller) there. Put an `app.ico` (Windows) or `app.icns` (macOS) next to the scripts to give the
programs an icon.

## Publishing a release

GitHub builds every version for you (see `.github/workflows/release.yml`):

1. Change `__version__` in `folder_activity_scanner.py`, commit and push.
2. Tag the same version and push the tag:
   ```
   git tag v1.1.1
   git push origin v1.1.1
   ```
3. GitHub Actions builds the Windows, Linux and macOS (Apple Silicon and Intel) versions on their own
   systems, tests that each one starts and can scan a folder, and publishes them with
   `SHA256SUMS.txt` as a new release. The build stops if the tag does not match `__version__`.

To test the builds without publishing, open the **Actions** tab, choose **Build and release** and
click **Run workflow**; the programs appear under *Artifacts* on the run's page.

Dependabot proposes updates for the build tools once a month (`.github/dependabot.yml`).
