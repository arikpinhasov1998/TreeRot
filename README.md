# TreeRot

<img src="assets/treerot-256.png" width="96" alt="TreeRot logo">

**Find the rot in your folder tree.** TreeRot scans a folder or network share and shows every
folder as **green** (used in the dates you choose), **red** (not used) or **gray** (empty or
unreadable).

Created by [Arik Pinhasov](https://github.com/arikpinhasov1998). All rights reserved; see
[LICENSE](LICENSE). GitHub's terms let others view and fork this public repository, but no other
rights are granted.

A folder counts as used when a file anywhere inside it was **modified or created** in the period,
even if the folder's own date is older. Hover over a folder to see *why* it has its color;
right-click to copy the reason or path.

At the end of a scan you see how much storage is used, unused and empty. Export a CSV, or a
**report** as HTML (interactive: open folders, search, filter) or PDF (fixed pages to print or send).
It runs on Windows, Linux and macOS, with a window or from the command line (for servers).

**What has and has not been tested.** The automatic tests have so far been run only on the
developer's Mac. GitHub's build is set up to run the same tests on Windows, Linux and macOS
before it builds anything, but that workflow has not run yet, so nothing is proven on those
systems. The Windows features listed under
[Check on a real Windows server](#check-on-a-real-windows-server) have not been tried on a real
Windows server. Please run that checklist before you rely on them.

## Download

Go to the [**Releases**](../../releases/latest) page and download the file for your system:

| System | Download | What you get |
|---|---|---|
| Windows 10 / 11 | `TreeRot.exe` | The window. Double-click to start. |
| | `TreeRot-cli.exe` | The command line, for scripts and Task Scheduler. |
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

### What survives what (Windows)

| What happens | Scan in the window | Run in background |
|---|---|---|
| Closing the RDP window (disconnect) | Should keep running, unless a server policy ends disconnected sessions | Should keep running |
| Logging off | Stops | Should keep running |
| The computer restarts | Stops | Stops; start it again |

"Should" is deliberate: this has not been tried on a real server yet. See the checklist below.

### Run in background (Windows window)

**What it does.** In the window, **Run in background...** creates a Windows scheduled task that
runs `TreeRot-cli.exe` for you, under your own account, and starts it at once. The scan then
carries on without the window and without you being logged on. **Background scans** lists these
scans, shows their progress, and opens the finished report. It follows them even after you
close and reopen TreeRot.

**How to use it.**

1. Enter the folder and set the dates and exclusions as for a normal scan.
2. Click **Run in background...** and choose where to save the report (HTML or PDF).
3. A black Windows console window opens and asks for **your Windows password**. Type it there.
4. Open **Background scans** to follow the scan. When it says finished, click **Open report**.

**Your password.** Windows' own console prompt collects it. TreeRot never sees it, never stores
it and never writes it to a file. Windows keeps the password with the task, because the task needs
it to run when you are logged off. That has a consequence you should know about: **the password
stays stored with the task until the task is removed.** TreeRot removes the finished task for you
when you open **Background scans** or the next time it starts, or when you press **Remove**. If
TreeRot is never opened again, the task, and the password stored with it, stay in Windows. To delete
one by hand, see [Delete a background task by hand](#delete-a-background-task-by-hand).

**If the task cannot be created.** Windows' own error appears in the console window and stays
there until you press a key. Read it before you close the window: closing it counts as a failure.
Common reasons are a wrong password or an account that is not allowed to run a task without being
logged on (the Windows policy "Log on as a batch job"). TreeRot's window then points you at
[Set up a background scan by hand](#set-up-a-background-scan-by-hand).

**Rules.**

* **Use a network path** (`\\server\share`), not a mapped drive such as `Z:`. A background task
  has no mapped drives, so TreeRot refuses them for the folder to scan and for the report.
  The report may go to a local drive such as `C:\reports`, or to a UNC path.
* **The folder or report must not contain `%NAME%` or `$(Arg0)`** (a percent sign pair around
  text, or a dollar sign followed by text in parentheses). Task Scheduler may expand these in a
  command line and silently change the path, so TreeRot refuses them. A lone `100%` or `$5` is
  fine. Use the manual route for these names.
* **Your Windows user name cannot contain `&`, `%`, `^`, `|`, `<`, `>` or `"`.** The button
  refuses it, because the user name has to pass through `cmd.exe` to Windows' password prompt.
  Use the manual route.
* You need permission to create scheduled tasks. A standard account normally has it for its
  own tasks, but see the checklist.

### Set up a background scan by hand

Use this when the button refuses your user name or path, when the task cannot be created, or when
you prefer to see every setting. It does not need the TreeRot window. A task made this way does
**not** appear in **Background scans**; you follow it by its report and its log.

1. Open **Task Scheduler** (Start menu, type "Task Scheduler").
2. Choose **Action > Create Task...** (not "Create Basic Task").
3. **General:** give it a name such as `Share scan`. Choose **Run whether user is logged on or
   not**. Tick **Do not store password** only if the scan does not need network access (leave it
   unticked for a `\\server\share`). The account must be allowed to read the share and write the
   report.
4. **Actions > New...:** *Start a program*.
   * Program/script: the full path of `TreeRot-cli.exe`, for example `C:\Tools\TreeRot-cli.exe`
   * Add arguments: `"\\server\share" --from 2024-11-04 --format summary --report "C:\reports\share.html"`
   * Leave *Start in* empty, or use a folder the account can write to.
5. **Settings:** untick **Stop the task if it runs longer than**. The default of 3 days ends long
   scans. Leave **Allow task to be run on demand** ticked.
6. Click **OK**. Windows asks for your password; this is Windows' own dialog.
7. Right-click the new task in the list and choose **Run**. The **Last Run Result** column shows
   `0x0` when it succeeded.

**Avoid `%NAME%` and `$(...)` in paths here as well.** Task Scheduler may expand them in the
arguments and change the path, and this has not been tested. If your folder name has them, scan
its parent folder instead, or rename the folder.

A task does not keep the program's text output. The report is the result; add `--status-file
C:\reports\share.status.json` if you also want a small file that shows progress while it runs.

### Delete a background task by hand

TreeRot's tasks are named `TreeRot-` followed by the date and a short code, in the top level of
**Task Scheduler Library**. To remove one: open Task Scheduler, find it, right-click and choose
**Delete**. Or, in a Command Prompt run as the same user:

```
schtasks /Query /FO CSV /NH
schtasks /Delete /TN TreeRot-20261104-120000-ab12 /F
```

The first line lists your tasks; use the name from the list in the second. Deleting the task also
deletes the password Windows stored with it. TreeRot keeps a small record of each background scan
in `.treerot\jobs` in your home folder; it is safe to delete those files too.

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

### Check on a real Windows server

TreeRot's tests cannot create real scheduled tasks, log off, or reach a real server, so these
checks need a person. Please run them once on the Windows Server you care about and tell the
developer what differed. Each step says what should happen. Use a test folder first.

**A. The window and RDP**

1. Start a scan of a large `\\server\share` in the window. Close the RDP window without logging
   off, wait a minute, reconnect. *The scan should still be running, unless a server policy ends
   disconnected sessions.*
2. Start another scan, then log off, log back on, and open TreeRot. *The scan has stopped; that
   is expected for a scan in the window.*
3. Start a scan and leave the computer alone for longer than its sleep time. *The scan should
   keep going and the computer should not sleep.* Also try choosing Sleep yourself: *the scan
   pauses, and carries on after waking.*
4. Scan a UNC path (`\\server\share`). *It works and files can be listed.* Try a mapped drive
   letter in **Run in background...** *It is refused with a clear message.*
5. Open a folder with spaces in its path, right-click a file in it and choose **Open in file
   manager**. *Explorer opens with that file selected.* Try a folder name with Hebrew letters
   and one with `&`.

**B. Run in background**

6. Sign in as a **standard (non-admin) user**. Click **Run in background...** with a `\\server\share`
   path. *The password console appears and the task is created.* If it fails with "access is
   denied", note the exact words.
7. Type your password in the black console window. *Windows accepts it, and **Background scans**
   shows the scan running within a minute.* Do this once with a folder and report path that
   contain spaces and Hebrew letters.
8. Run it again and type a **wrong password**. *The console shows Windows' error and waits for a
   key; the TreeRot window then says the task could not be created and points at the README.*
   Try closing the console without pressing a key: *this counts as a failure.*
9. Ask your Windows administrator for an account that is **not allowed to run tasks while logged
   off** (in Windows this permission is called "Log on as a batch job"; a locked-down account often
   lacks it). Try **Run in background...** with it. *You should see a reason you can understand,
   in the console window or in **Background scans**. Write down the exact words if it is unclear.*
10. With a scan running in the background, close the RDP window. *The scan keeps running.* Then log
    off and log back on and open TreeRot: *Background scans still lists it, with progress, and
    **Open report** works when it has finished.*
11. Press **End scan** on a running background scan. *It stops.* Press **Remove**. *The row goes,
    and the task is gone from Task Scheduler.*
12. Finish a scan, then close TreeRot without pressing Remove and open it again. *The finished
    task is gone from Task Scheduler (check the Task Scheduler Library) and the entry stays in the
    list with **Open report**.*
13. Try to use a path containing `%NAME%` and one containing `$(Arg0)`. *Both are refused.*
    Try a user name with `&` if you have one. *Refused, with a pointer to the manual route.*
14. Follow [Set up a background scan by hand](#set-up-a-background-scan-by-hand) once. *It runs
    and writes the report.*
15. Run a background scan with a **PDF** report. *The PDF is made even though no one is logged
    on.* If not, note the message: it names each browser that failed.
16. *Only if your company signs in with Microsoft work accounts (Azure AD, now called Entra ID;
    the user name looks like `AzureAD\name`):* try **Run in background...** with such an account.
    *It works, or it shows a clear reason why not.*

**C. Smaller things not yet seen on Windows**

17. Run a background scan with a long list of exclusions (dozens). *It starts normally.*
18. After a wrong-password failure, the **Background scans** panel should say the task never
    started and let you **Remove** it.
19. In the panel, a task Windows could not start should show a reason in plain words
    (for example "the password has expired").
20. *Optional, for developers:* if Python is installed on the server, open a Command Prompt in the
    TreeRot folder and run `python -m unittest discover -s tests -v`. *Every test passes.*

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
