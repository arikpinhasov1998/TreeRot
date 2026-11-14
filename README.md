# TreeRot

<img src="assets/treerot-256.png" width="96" alt="TreeRot logo">

**Find the rot in your folder tree.** TreeRot scans a folder or network share and shows every
folder as **green** (used in the dates you choose), **red** (not used) or **gray** (empty or
unreadable).

Created by [Arik Pinhasov](https://github.com/arikpinhasov1998). TreeRot is open source under the
[MIT License](LICENSE): you may use, change and share it, as long as the copyright notice stays.

A folder counts as used when a file anywhere inside it was **modified or created** in the period,
even if the folder's own date is older. Hover over a folder to see *why* it has its color;
right-click to copy the reason or path.

At the end of a scan you see how much storage is used, unused and empty. Export a CSV, or a
**report** as HTML (interactive: open folders, search, filter) or PDF (fixed pages to print or send).
It runs on Windows, Linux and macOS, with a window or from the command line (for servers).

**What has and has not been tested.** The automatic tests have so far been run only on the
developer's Mac. GitHub's build is set up to run the same tests on Windows, Linux and macOS
before it builds anything, but that workflow has not run yet, so nothing is proven on those
systems. Background scans have been run for real on Linux (Ubuntu, systemd) only; the steps
under [Check on real computers](#check-on-real-computers) have not been tried on Windows or
macOS yet. Please run that checklist before you rely on them.

## Download

Go to the [**Releases**](../../releases/latest) page and download the file for your system:

| System | Download | What you get |
|---|---|---|
| Windows 10 / 11 | `TreeRot.exe` | The window. Double-click to start. |
| | `TreeRot-cli.exe` | The command line, for scripts and terminals. Not needed for background scans. |
| Linux (x86-64) | `treerot-linux-x86_64.tar.gz` | One program for both the window and the command line. |
| macOS, Apple Silicon (M1 and later) | `TreeRot-macos-arm64.zip` | `TreeRot.app` and the command-line program `treerot`. |
| macOS, Intel | `TreeRot-macos-x86_64.zip` | The same, for Intel Macs. |

Nothing is installed. To check that a download is genuine, compare its SHA-256 hash with
`SHA256SUMS.txt` from the same release (`certutil -hashfile FILE SHA256` on Windows,
`shasum -a 256 FILE` on macOS, `sha256sum FILE` on Linux).

### First start

The programs are not code-signed, so each system warns the first time:

* **Windows:** "Windows protected your PC" - click **More info**, then **Run anyway**.
* **macOS:** "cannot be opened because Apple cannot check it" - open **System Settings >
  Privacy & Security**, scroll down and click **Open Anyway** next to the app's name. Or, in
  Terminal: `xattr -dr com.apple.quarantine TreeRot.app`.
  To scan a network share, also allow the app under **Privacy & Security > Files and Folders >
  Network Volumes**; without it every folder on the share shows as unreadable (gray).
* **Linux:** unpack and run:
  ```
  tar -xzf treerot-linux-x86_64.tar.gz
  ./treerot              # window (needs a desktop)
  ./treerot /srv/share   # command line
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
* Open a folder to see its files, each with its own color, hover reason and right-click copy.
  Files are read live from the share. Large folders show 1,000 at a time with **Show more**.
  Right-click a file and choose **Open in file manager** to see it in Explorer, Finder or your
  Linux file manager. The file is shown there, never opened.
* **Show levels** opens the tree to a chosen depth or **Unlimited**. The scan always reads every
  level, so colors and sizes stay correct.
* **Export report...** lets you choose **HTML** or **PDF**. See [PDF reports](#pdf-reports).
* The PDF has to choose how much of the tree to print, because paper cannot expand folders:
  **up to N levels**, **all levels (unlimited)**, or **the path to every unused folder**. The
  dialog shows how many folders and roughly how many pages that gives before you save.
* Settings (last path, exclusions, last scan totals) are saved in `.treerot.json`
  in your home folder.

## Command line

Give a path and the window does not open, so it works over SSH, in cron and in Task Scheduler:

```
TreeRot-cli.exe "\\server\share" --from 2024-10-28 --format summary --report share.html
./treerot /srv/share --from 2024-10-28 --format summary --report share.pdf
./treerot /srv/share --format csv -o share.csv --progress lines 2>> scan.log
```

Useful options: `--to DATE`, `--exclude NAME_OR_PATH` (repeatable), `--exclude-common`,
`--format summary|tree|csv` (with `--depth N|all` for the tree), `--report FILE.html|FILE.pdf`
(with `--report-tree N|all|unused` and `--browser PATH` for PDF), `--progress bar|lines|none`
(`lines` writes a status line every 30 s, for logs), `--precount`, `--created auto|ctime|off`.
Run with `--help` for everything.

For Task Scheduler, use the **UNC path** (`\\server\share`), not a mapped drive letter: mapped
drives do not exist when a task runs on its own.

## PDF reports

TreeRot makes a PDF by printing the HTML report with a Chromium-family browser that is already
on the computer. It tries them in this order: **Microsoft Edge, Google Chrome, Chromium, then
Brave**. If one fails, it moves on to the next and, if none works, lists why each one failed.

* **Time limit.** Each browser gets 60 seconds plus about one second for every 50 rows printed,
  and never more than 10 minutes. A browser that is still working after that is ended, together
  with anything it started.
* **No browser, or none works.** Servers often have none. The PDF fails with a message, and the
  HTML report is still available. It needs no browser, shows the complete tree, and prints to PDF
  from any browser.
* **Choose a browser yourself** with `--browser PATH` on the command line, or set the
  environment variable `TREEROT_BROWSER` to the browser's full path. Either one means only that
  browser is tried.

## Long scans, RDP and servers

### Keeping the computer awake

While a scan runs, TreeRot asks the computer not to go to sleep. The screen may still turn off.

| System | What TreeRot does | If it cannot |
|---|---|---|
| Windows | Tells Windows the computer is busy. The computer will not go to sleep by itself during the scan. | - |
| macOS | Runs the built-in `caffeinate` for as long as the scan runs. | Shows a note. |
| Linux | Runs `systemd-inhibit` while the scan runs. It needs systemd and a session bus. | Shows a note. |

This stops *automatic* sleep. It does not stop a person closing a laptop lid or choosing Sleep,
and the computer can still be shut down. If TreeRot cannot keep the computer awake, it says so;
a sleeping computer pauses the scan.

### Run in background

**What it does.** In the window, **Run in background...** starts the scan as a separate copy of
TreeRot that keeps going after you close the window. **Background scans** lists these scans,
shows their progress, ends them, and opens the finished report, also after you close and reopen
TreeRot. When a scan finishes, fails or is stopped, a **desktop notification** says so.

It works on Windows, Linux and macOS, from the one program you downloaded. **No administrator
rights, no password and no installation** are needed: the scan runs as your own process.

**How to use it.**

1. Enter the folder and set the dates and exclusions as for a normal scan.
2. Click **Run in background...** and choose where to save the report (HTML or PDF).
3. Close the window if you like. Open **Background scans** to follow the scan; when it says
   finished, click **Open report**.

**What survives what.**

| What happens | Scan in the window | Run in background |
|---|---|---|
| Closing the TreeRot window | Stops | Keeps running |
| Locking the screen, closing the RDP window (disconnect) | Keeps running | Keeps running |
| Logging off, **Windows** | Stops | Stops |
| Logging out, **macOS** | Stops | Stops |
| Logging out, **Linux** | Stops | Keeps running (see below) |
| The computer restarts | Stops | Stops; start it again |

* **Windows and macOS** do not let a normal user keep a program running after logging off;
  only an administrator-installed service could. TreeRot does not store your password to get
  around this, so a background scan there runs until you log off.
* **Linux** runs the scan as a systemd *user service* and turns on "linger" for your account
  (`loginctl enable-linger`), which keeps your services running after you log out. Most
  distributions let you do that for yourself without an administrator. If it is refused, or the
  system has no systemd, TreeRot says the scan may stop when you log out.
* **Linux shares opened in the file manager** (they appear under `/run/user/<id>/gvfs/`) belong
  to your desktop session and disappear when you log out. TreeRot warns you and still lets you
  scan them. To scan a share while logged out, have it mounted by the system (`/etc/fstab` or
  autofs, usually set up by an administrator) and scan that path instead. Local disks and
  system-mounted shares (SMB or NFS) keep working after logout.
* A scan stopped by logging off or a restart shows as **Stopped** in **Background scans**.

**Notifications.** When a background scan ends you get a notification from your desktop
(Windows notification center, `notify-send` on Linux, Notification Center on macOS). If nobody
is logged in at that moment, or logging off stopped the scan, the notification appears **at
your next login**. For that, TreeRot adds a small login item while a scan is unreported and
removes it afterwards:

| System | Login item (your own account only) |
|---|---|
| Windows | A value named `TreeRot login check` under `HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run` |
| Linux | `~/.config/autostart/treerot-login-check.desktop` |
| macOS | `~/Library/LaunchAgents/io.github.arikpinhasov1998.treerot.login-check.plist` |

It runs `TreeRot --login-check` from where the program was when the scan started, so if you
move or delete the program in the meantime, the login item does nothing; it is safe to delete.

**Where TreeRot keeps its records.** A small record of each background scan sits in
`.treerot/jobs` in your home folder, and each scan writes its progress next to the report
(`<report>.status.json`). Removing a scan in **Background scans** deletes its record but keeps
the report and its status file.

**Scans started by older versions (Windows).** Versions before this one created a Windows
scheduled task that stored your password. Such scans still appear in **Background scans** and
**Remove** still deletes their task, and with it the stored password. New scans never create one.

### Linux and macOS: scans that outlive your terminal

The command-line program has no window, so run it in whatever keeps processes alive:

```
# nohup: keeps running after you log out (output goes to scan.log)
nohup ./treerot /srv/share --from 2024-11-04 --format summary --report share.html > scan.log 2>&1 &

# tmux: start a session, run the scan, press Ctrl-b then d to leave; "tmux attach" to come back
tmux new -s scan './treerot /srv/share --from 2024-11-04 --format summary --report share.html'

# systemd (Linux): runs as its own unit; follow it with journalctl
systemd-run --user --unit=treerot-scan /opt/treerot/treerot /srv/share --from 2024-11-04 --format summary --report /srv/reports/share.html
journalctl --user -u treerot-scan -f

# launchd (macOS): a one-off job; remove it when it is done
launchctl submit -l treerot-scan -o scan.log -e scan.log -- /path/to/treerot /srv/share --from 2024-11-04 --format summary --report /path/to/share.html
launchctl remove treerot-scan
```

Use full paths with `systemd-run` and `launchd` (change `/opt/treerot/treerot` to where you
unpacked the program), because they do not start in your current
folder. To keep a `--user` systemd unit running after you log out, run `loginctl enable-linger`
once. These commands were written for this README and have not all been run on every system.

### Check on real computers

TreeRot's tests cannot log off, restart, or reach a real server, so these checks need a person.
Please run them once on each system you care about and tell the developer what differed. Each
step says what should happen. Use a test folder first, and a **standard (non-admin) account**.

**A. The window and RDP (Windows)**

1. Start a scan of a large `\\server\share` in the window. Close the RDP window without logging
   off, wait a minute, reconnect. *The scan should still be running, unless a server policy ends
   disconnected sessions.*
2. Start a scan and leave the computer alone for longer than its sleep time. *The scan should
   keep going and the computer should not sleep.*
3. Open a folder with spaces in its path, right-click a file in it and choose **Open in file
   manager**. *Explorer opens with that file selected.* Try a folder name with Hebrew letters
   and one with `&`.

**B. Run in background (every system)**

4. Click **Run in background...** on a large folder and save the report. *No password is asked
   for, no console window appears, and **Background scans** shows the scan running within a
   minute.* Do this once with a folder and report path that contain spaces and Hebrew letters.
5. Close the TreeRot window. *The scan keeps running.* Open TreeRot again: *Background scans
   still lists it with progress.*
6. Wait for it to finish. *A notification says it finished; **Open report** opens the report.*
7. Press **End scan** on a running background scan. *It stops and shows Ended; no notification.*
   Press **Remove**. *The row goes; the report and its status file stay.*
8. Run a background scan with a **PDF** report, and one with the report on a network path.
   *Both reports are made and **Open report** opens them.*
9. *Windows:* use a **mapped drive letter** (such as `Z:`) for the folder. *It works, because
   the scan runs in your own session.*

**C. Logging off**

10. *Windows and macOS:* start a long background scan, then log off and log back on. *A
    notification soon after login says the scan was stopped; **Background scans** shows it as
    Stopped.*
11. *Linux:* start a long background scan of a local folder, then log out. Log back in after it
    should have finished. *A notification after login says it finished, and the report is there.*
    Run `loginctl show-user $USER --property=Linger`: *it says `Linger=yes`.*
12. *Linux:* open a share in the file manager and try **Run in background...** on its
    `/run/user/.../gvfs/...` path. *TreeRot warns that it stops at logout and lets you choose.*
13. After every scan has been reported, check the login item from the table above. *It is gone.*

**D. Optional, for developers**

14. If Python is installed, open a terminal in the TreeRot folder and run
    `python -m unittest discover -s tests -v`. *Every test passes.*

## Run from source

Requires Python 3.8 or newer and nothing else (standard library only):

```
python treerot.py                 # window
python treerot.py /srv/share      # command line
```

The window needs Python's tkinter: on Linux `sudo apt install python3-tk`; on macOS use Python
from python.org (Apple's built-in Python has an old, buggy Tk).

## Development

Run the tests from the project folder:

```
python3 -m unittest discover -s tests -v
```

The window tests skip themselves when there is no display. On a Linux server without a desktop
use `xvfb-run -a python3 -m unittest discover -s tests -v`. The suite takes several minutes.
The GitHub workflow is set up to run it on Windows, Linux and macOS, on Python 3.13 and
3.8 where GitHub offers 3.8, before it builds anything, so that a failure stops the build. It has
not run yet.

## Build the programs yourself

Each system can only build its own programs, so build on the system you want to run on:

| System | Command | Result in `dist/release/` |
|---|---|---|
| Windows | `build_exe.bat` | `TreeRot.exe`, `TreeRot-cli.exe` |
| Linux | `bash build.sh` | `treerot-linux-<arch>.tar.gz` |
| macOS | `bash build.sh` | `TreeRot-macos-<arch>.zip` |

The scripts create a private build environment in `.venv-build` and install the pinned build tool
(PyInstaller) there. The icons `app.ico` (Windows) and `app.icns` (macOS) are already in the
project; the scripts use them when they exist, and build without an icon if you delete them.
`tools/make_icons.py` draws them again from the logo.

## Publishing a release

GitHub builds every version for you (see `.github/workflows/release.yml`):

1. Change `__version__` in `treerot.py`, commit and push.
2. Tag the same version and push the tag:
   ```
   git tag v1.2.0
   git push origin v1.2.0
   ```
3. GitHub Actions is set up to run the tests on Windows, Linux and macOS, then to build the
   Windows, Linux and macOS (Apple Silicon and Intel) versions on their own systems, check that each one starts and
   can scan a folder, and publish them with `SHA256SUMS.txt` as a new release. The build stops if
   a test fails or if the tag does not match `__version__`.

To test the builds without publishing, open the **Actions** tab, choose **Build and release** and
click **Run workflow**; the programs appear under *Artifacts* on the run's page.

Dependabot proposes updates for the build tools once a month (`.github/dependabot.yml`).
