# TreeRot

<img src="assets/treerot-256.png" width="96" alt="TreeRot logo">

**Find the rot in your folder tree.**

Created by [Arik Pinhasov](https://github.com/arikpinhasov1998). TreeRot is open source under the
[MIT License](LICENSE): you may use, change and share it, as long as the copyright notice stays.

---

## What is TreeRot? (the short story)

Imagine a big toy box with lots of smaller boxes inside it, and boxes inside those boxes.
Some boxes have toys you played with this year. Some boxes have toys nobody has touched for a
very long time. They just sit there and take up space.

Your computer's folders are like those boxes. **TreeRot opens every box and paints it a color:**

| Color | What it means | In plain words |
|---|---|---|
| 🟩 **Green** | **Used** | Somebody changed or added a file in here during the dates you chose. Keep it. |
| 🟥 **Red** | **Not used** | Nothing in here was changed or added during the dates you chose. It might be "rot": old stuff you can archive or delete. |
| ⬜ **Gray** | **Empty or unreadable** | There are no files inside, or TreeRot was not allowed to open it. |

When it is done, TreeRot tells you **how much space is used, how much is not used, and how much is
empty**, and you can save a nice **report** to keep or send to someone.

> **TreeRot never deletes, moves or changes anything.** It only looks. You decide what to do.

### One rule to remember

A folder is **green** if **any file anywhere inside it** (even deep down, in a folder inside a
folder inside a folder) was **changed or created** during your dates. So a big folder turns green
even if only one small file deep inside it was used. That is on purpose: you should not throw
away a box that still has a toy someone is playing with.

---

## Contents

* [Get TreeRot](#get-treerot)
* [Your first scan, step by step](#your-first-scan-step-by-step)
* [Understand what you see](#understand-what-you-see)
* [Every button in the window](#every-button-in-the-window)
* [Save a report](#save-a-report)
* [Background scans](#run-in-background)
* [TreeRot stays open in the tray](#treerot-stays-open-in-the-tray)
* [Recipes: common jobs](#recipes-common-jobs)
* [Command line (for servers and scripts)](#command-line-for-servers-and-scripts)
* [When something goes wrong](#when-something-goes-wrong)
* [Words you might not know](#words-you-might-not-know)
* [Check on real computers](#check-on-real-computers)
* [For developers](#for-developers)

---

## Get TreeRot

### 1. Download

Go to the [**Releases**](../../releases/latest) page and download the one file for your computer:

| Your computer | Download this | What you get |
|---|---|---|
| Windows 10 / 11 | `TreeRot.exe` | The program with a window. Double-click to start. This is the one you want. |
| | `TreeRot-cli.exe` | Only for typing commands in a terminal or scripts. Most people do not need it. |
| Linux (x86-64) | `treerot-linux-x86_64.tar.gz` | One program that does both the window and the commands. |
| Mac with Apple chip (M1, M2, M3, M4 and later) | `TreeRot-macos-arm64.zip` | `TreeRot.app` (the window) and `treerot` (the commands). |
| Mac with Intel chip | `TreeRot-macos-x86_64.zip` | The same, for older Intel Macs. |

**Not sure which Mac you have?** Click the Apple menu  > **About This Mac**. If it says "Chip
Apple M…", take `arm64`. If it says "Processor Intel…", take `x86_64`.

**Nothing gets installed.** TreeRot is just one program file. You can keep it on your desktop, in
your Downloads folder, or on a USB stick. To get rid of it, delete the file.

### 2. Start it the first time

TreeRot is free and not "signed" (signing costs money every year), so your computer will be
careful the first time. That is normal. Here is how to say "yes, I trust it":

* **Windows:** a blue box says "Windows protected your PC". Click **More info**, then
  **Run anyway**. You only do this once.
* **Mac:** double-click `TreeRot.app`. If it says it "cannot be opened because Apple cannot check
  it", click **Done**, then open **System Settings > Privacy & Security**, scroll down, and click
  **Open Anyway** next to TreeRot. (Or, in Terminal: `xattr -dr com.apple.quarantine TreeRot.app`.)
  To scan a **network share** on a Mac, also turn TreeRot on under **Privacy & Security > Files
  and Folders > Network Volumes**. Without that, every folder on the share shows gray.
* **Linux:** unpack it and start it:
  ```
  tar -xzf treerot-linux-x86_64.tar.gz
  ./treerot              # opens the window (needs a desktop)
  ./treerot /srv/share   # scans without a window
  ```
  It needs a fairly new Linux (Ubuntu 22.04+, Debian 12+, RHEL/Rocky 9+). On older systems use
  the Python file instead (see [Run from source](#run-from-source)).

### 3. Is my download real? (optional)

Every release has a file called `SHA256SUMS.txt`. It holds a "fingerprint" for each download.
Make the fingerprint of your file and check it is the same:

* Windows: `certutil -hashfile TreeRot.exe SHA256`
* Mac: `shasum -a 256 TreeRot-macos-arm64.zip`
* Linux: `sha256sum treerot-linux-x86_64.tar.gz`

If the long string of letters and numbers matches the one in `SHA256SUMS.txt`, the file is genuine.

---

## Your first scan, step by step

Let's find the old, unused stuff in one folder. It takes five steps.

**Step 1. Choose the folder.**
At the top, next to **Folder / share**, click **Browse...** and pick a folder. Or type its path:

* A folder on your computer: `C:\Data` (Windows), or a folder like `/srv/share` (Mac, Linux)
* A shared folder on another computer (Windows network share): `\\server\share`

**Step 2. Choose the dates.**
Next to **Period**, there is **From** and **To (optional)**. TreeRot asks: *"Was anything used
between these dates?"*

* The easiest way: open **Quick set** and pick **Last 2 years** (it is already picked when TreeRot
  starts). This means "was anything used in the last 2 years?"
* Or click **Pick** next to **From** to choose a date on a little calendar.
* Leave **To** empty to mean "until today".
* Dates are written year-month-day, like `2024-11-04`.

**Step 3. (Optional) Skip some folders.**
Some folders are just computer clutter, like the recycle bin or backup snapshots. Click **Add
common system folders** to skip them all at once. More on this in
[Exclude folders](#exclude-folders).

**Step 4. Click Scan.**
First the bar slides back and forth: TreeRot is checking the folder (and counting, if **Count
first** is ticked), so it cannot tell yet how long it will take. Then the bar starts filling up.
Under it you can see how many folders and files TreeRot has looked at, how long it has been
running and about how much time is left. Big network shares can take a long time (minutes or
even hours). You can click **Cancel** at any time.

**Step 5. Look at the colors.**
When the scan is done, you see your folder as a tree, each folder in green, red or gray, with
three boxes on top that add up the space. The next section explains everything you see.

🎉 That's it. You did your first scan.

---

## Understand what you see

### The three summary boxes

After a scan, three colored boxes show the totals:

* **Green box:** how much space is in folders that were **used** in your dates.
* **Red box:** how much space is in folders that were **not used**. This is the space you could
  probably free up.
* **Gray box:** how much is **empty** or could not be read.

### The tree

The big list in the middle is your folder, with the folders inside it shown one level deeper.
Click the little arrow (▸) next to a folder to open it and see what's inside. The columns are:

| Column | What it tells you |
|---|---|
| **Folder / file** | The name, painted green, red or gray. |
| **Last file activity** | When the newest file anywhere inside was last changed or created. |
| **Folder modified** | The folder's own date (changes only when something is added, removed or renamed directly in it). |
| **Files** | How many files are inside, all the way down. |
| **In period** | How many of those files were used in your dates. |
| **Size** | How much space it takes. |
| **% of parent** | How big it is compared to the folder it sits in. |

* **Biggest first.** Folders are sorted largest first, so the biggest problems are at the top.
* **Hover** your mouse over any folder for a moment: a small note says **why** it got its color,
  for example which file was changed last and when.
* **Right-click** a folder to **Copy path**, **Copy reason**, or **Copy path + reason**. Paste it
  into an email or a ticket.

### Files inside a folder

When you open a folder, you also see its **files**, each with its own color and hover note.
Files are read fresh from the disk or share when you open the folder.

* A very big folder shows 1,000 files at a time. Click **Show more** for the next ones.
* Right-click a file and choose **Open in file manager** to see it in Explorer (Windows), Finder
  (Mac) or your Linux file manager. The file is only **shown** there, never opened or changed.

### What "used" really means

A file counts as **used** when it was **modified** (changed and saved) during your dates.

There is a catch: when you **copy** an old file to a new place, the copy often keeps its old
"modified" date. So TreeRot also counts files that were **created** in your dates. That is the box
**Files CREATED in the period count too**, which is on by default.

* On **Windows and Mac**, the computer remembers the real "created" date, so this works well.
* On **Linux**, there is no real "created" date. TreeRot uses the "change time" instead, which also
  changes when someone renames a file or changes who may open it. So on Linux a few folders may
  turn green that nobody really used. Untick the box if you only care about real edits.

### Opening a file does not count

Just **opening** or **reading** a file does not make it green. Most computers and file servers
don't keep track of that reliably. TreeRot only counts files that were changed or created.

---

## Every button in the window

### Top: what to scan

| Button or box | What it does |
|---|---|
| **Folder / share** + **Browse...** | The folder to scan. Type a path or click Browse. |
| **From** / **To (optional)** + **Pick** | The dates to check. Pick opens a small calendar. Empty To = until today. |
| **Quick set** | One click for Last 1, 2, 3, 5 or 10 years. |
| **Follow symlinks (risk of loops)** | Leave this **off**. A symlink is a shortcut to another folder; following them can make TreeRot go around in circles or count things twice. |
| **Files CREATED in the period count too** | Also counts copied-in files as used. See [What "used" really means](#what-used-really-means). |

### Exclude folders

Folders on this list are **skipped completely**: not read, not counted, not shown.

| Button | What it does |
|---|---|
| **Add folder...** | Skip one exact folder you choose. |
| **Add name / pattern...** | Skip every folder with this name, anywhere. You can use `*` as "anything", for example `*.tmp` or `backup*`. |
| **Add common system folders** | Skips the usual clutter: `$RECYCLE.BIN`, `System Volume Information`, `.snapshot`, `~snapshot`, `#snapshot`, `#recycle`, `@Recycle`, `@eaDir`, `.Trash-*`, `lost+found`. |
| **Remove selected** | Takes the selected item off the list. |

TreeRot remembers your list for next time.

### The scan buttons

| Button | What it does |
|---|---|
| **Scan** | Starts the scan in this window. |
| **Cancel** | Stops the scan. |
| **Count first (exact progress, slower)** | Before scanning, TreeRot counts everything first, so the percentage and "time left" are exact. It takes longer because it reads the whole tree twice. Without it, the first scan of a path shows a guess (marked `~`); the next scans of the same path remember the last totals and are close to exact. |
| **Export CSV...** | Saves the results as a spreadsheet file you can open in Excel, LibreOffice or Google Sheets. |
| **Export report...** | Saves a good-looking report (HTML or PDF). See [Save a report](#save-a-report). |
| **Run in background...** | Runs the scan by itself, so you can close the window. See [Run in background](#run-in-background). |
| **Background scans** | Shows the scans running in the background, and the finished ones. |
| **About** | Version and who made TreeRot. |

### Looking at the results

| Button or box | What it does |
|---|---|
| **Color by** | **Files inside (recursive)** is the normal way (see [One rule to remember](#one-rule-to-remember)). **Folder's own date only (ignores files)** uses just the folder's own date, which is usually less useful. |
| **Show** | **All**, or only **Red** (not used), only **Green** (used), or only **Gray** (empty / error). |
| **Sort siblings by** | Order folders by **Size**, **Name**, or **Last file activity** (oldest or newest first). |
| **Expand to unused (red)** | Opens the tree just enough to show you every red folder. Great for finding the rot fast. |
| **Expand all** / **Collapse all** | Opens or closes every folder in the list. |
| **Show levels** | Opens the tree down to 1, 2, 3… levels, or **Unlimited**. This only changes what you **see**; the scan always reads every level, so colors and sizes are always right. |
| **Appearance** | **System** (the starting choice) follows your computer: when the computer switches between light and dark, TreeRot switches too, within a few seconds. **Light** and **Dark** stay the same whatever the computer does. TreeRot remembers your choice. |

### Light and dark appearance

Pick **Appearance** at the right of the window: **System**, **Light** or **Dark**. The change
happens at once, in the main window and in every dialog. Green, red and gray stay easy to tell
apart in both: in dark mode they become deep green, deep red and dark gray with light text.

How TreeRot knows what your computer uses, when you choose **System**:

| System | Where the setting comes from |
|---|---|
| Windows 10 / 11 | **Settings > Personalization > Colors > Choose your app mode**. In dark mode the window's title bar turns dark too. |
| macOS | **System Settings > Appearance**. The Mac draws TreeRot's buttons and lists in its own light or dark style. |
| Linux | The desktop's own dark style setting (asked through the standard desktop settings service, which GNOME, KDE and most others answer), then the name of the GTK theme (for example `Yaru-dark`), then KDE's color scheme. If none of these says dark, TreeRot uses light. This works also when TreeRot is started from another program, such as PyCharm. |

Some parts are drawn by the computer itself and follow the computer, not TreeRot: the
**Browse** and **Save** windows and message boxes on Windows and macOS.

### Keeping the computer awake

While a scan runs, TreeRot asks the computer **not to go to sleep by itself**. The screen may
still turn off; that's fine.

| System | What TreeRot does | If it cannot |
|---|---|---|
| Windows | Tells Windows the computer is busy. The computer will not go to sleep by itself during the scan. | - |
| macOS | Runs the built-in `caffeinate` for as long as the scan runs. | Shows a note. |
| Linux | Runs `systemd-inhibit` while the scan runs. It needs systemd and a session bus. | Shows a note. |

It cannot stop a person closing a laptop lid, choosing Sleep, or shutting down. If the computer
sleeps anyway, the scan pauses until it wakes up.

### TreeRot stays open in the tray

When you close the TreeRot window, TreeRot **keeps running**, like a small helper that is always
there. Its icon stays in the **tray**:

| System | Where the icon is |
|---|---|
| Windows | The notification area, at the right end of the taskbar (it may be behind the **^** arrow). |
| macOS | The menu bar, at the top right of the screen. |
| Linux | The tray or top bar. On Ubuntu it is at the top right. Other GNOME systems need the "AppIndicator and KStatusNotifierItem Support" extension; KDE, Xfce, Cinnamon and MATE have a tray already. |

It works the same everywhere:

* **Click the icon** to open the window again.
* **Right-click the icon** (on a Mac: right-click or Control-click) for its menu:
  * **Open TreeRot**
  * **Background scans**: opens the list of background scans.
  * **Start with my computer**: when ticked, TreeRot starts by itself when you log in, with
    only its icon showing. Untick it to stop that. It uses your own account only (no
    administrator): a `TreeRot` value under
    `HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run` on Windows,
    `~/.config/autostart/treerot-startup.desktop` on Linux, or
    `~/Library/LaunchAgents/io.github.arikpinhasov1998.treerot.plist` on macOS.
  * **Quit TreeRot**: really closes TreeRot. A scan running in the window stops;
    background scans keep going.
* A scan running in the window **keeps going** while the window is hidden.
* The first time you close the window, a notification reminds you where the icon is.
* **Starting TreeRot again** while it is running opens the window that is already there,
  instead of a second TreeRot. (The running TreeRot listens for this on your own computer
  only, and the file `.treerot/instance.json` in your home folder tells the second start
  where to find it.)
* If your desktop has no tray at all, closing the window quits TreeRot, as before.

### Where TreeRot keeps your settings

Your last folder, your exclude list, your appearance choice and the totals from your last scans are saved in a small file
called `.treerot.json` in your home folder. Delete it to start fresh.

---

## Save a report

After a scan, click **Export report...**. You can choose:

* **HTML: open folders, search and filter in any browser.** Best for looking around. Open it in
  Chrome, Edge, Firefox or Safari. You can open and close folders, search for a name, and show
  only red, green or gray. It contains the **whole** tree. It needs no internet.
* **PDF: fixed pages for printing and sending.** Best for printing or sending to a boss.

Both reports start with the totals and a list of the **largest unused folders**, then the colored
folder tree.

### How much of the tree goes into the PDF?

Paper cannot open and close folders, so a PDF of a huge share could be thousands of pages. You
choose how much to print:

* **Up to N levels:** for example, 2 means the top folder, the folders in it, and the folders in
  those.
* **All levels (unlimited):** every single folder. Can be very long.
* **The path to every unused folder:** only the red folders, plus the folders you need to get to
  them. Usually the most useful choice.

The dialog tells you **how many folders and about how many pages** you will get, before you save.

### How the PDF is made

TreeRot doesn't draw the PDF itself. It asks a web browser that is already on your computer to
"print to PDF". It tries **Microsoft Edge, Google Chrome, Chromium, then Brave**, in that order.
If one doesn't work, it tries the next. If none works, it tells you why.

* **No browser?** (Common on servers.) The PDF fails with a message. Save the **HTML** report
  instead: it needs no browser to make, and you can print it to PDF later from any computer.
* **Want a specific browser?** On the command line use `--browser PATH`, or set the setting
  (environment variable) `TREEROT_BROWSER` to the browser's full path. Then only that one is used.
* **Time limit:** each browser gets 60 seconds, plus about one second for every 50 rows, but never
  more than 10 minutes. If it takes longer, TreeRot stops it and everything it started.

---

## Background scans

### Run in background

**What it does.** A big network share can take hours to scan. You don't want to sit and wait.
**Run in background...** starts the scan as a separate helper that keeps going **even after you
close the TreeRot window**. When it finishes, a **desktop notification** pops up to tell you.

It works on Windows, Linux and macOS, from the one program you downloaded. **No administrator
rights, no password and no installation** are needed: the scan runs as you, under your own account.

**How to use it.**

1. Choose the folder, the dates and the exclusions, the same as for a normal scan.
2. Click **Run in background...** and choose where to save the report (HTML or PDF).
3. That's it. You can close TreeRot now if you want.
4. To check on it, open TreeRot and click **Background scans**. You see each scan with its
   progress. When it says finished, click **Open report**.

**The Background scans list** has three buttons:

* **Open report:** opens the finished report.
* **End scan:** stops a scan that is still running. It shows as **Ended**.
* **Remove:** takes the scan off the list. The report file is **kept**.

**What survives what.**

| What happens | Scan in the window | Run in background |
|---|---|---|
| Closing the TreeRot window | Keeps running: TreeRot stays in the tray (stops if your desktop has no tray) | Keeps running |
| **Quit TreeRot** in the tray menu | Stops | Keeps running |
| Locking the screen, closing the RDP window (disconnect) | Keeps running | Keeps running |
| Logging off, **Windows** | Stops | Stops |
| Logging out, **macOS** | Stops | Stops |
| Logging out, **Linux** | Stops | Keeps running (see below) |
| The computer restarts | Stops | Stops; start it again |

In plain words: **close the window, lock the screen, walk away. Just don't log off (on Windows or
Mac) and don't restart the computer.**

* **Windows and macOS** do not let a normal user keep a program running after logging off; only
  a service installed by an administrator could. TreeRot does not store your password to get
  around this, so a background scan there runs until you log off.
* **Linux** runs the scan as a systemd *user service* and turns on "linger" for your account
  (`loginctl enable-linger`), which keeps your services running after you log out. Most
  distributions let you do that for yourself without an administrator. If it is refused, or the
  system has no systemd, TreeRot says the scan may stop when you log out. To turn linger off
  again later: `loginctl disable-linger`.
* **Linux shares opened in the file manager** (they appear under `/run/user/<id>/gvfs/`) belong
  to your desktop session and disappear when you log out. TreeRot warns you and still lets you
  scan them. To scan a share while logged out, have it mounted by the system (`/etc/fstab` or
  autofs, usually set up by an administrator) and scan that path instead. Local disks and
  system-mounted shares (SMB or NFS) keep working after logout.
* A scan stopped by logging off or a restart shows as **Stopped** in **Background scans**.

**Notifications.** When a background scan ends, your computer shows a notification (the Windows
notification center, Notification Center on a Mac, or `notify-send` on Linux). If nobody is logged
in at that moment, or logging off stopped the scan, the notification appears **at your next
login**. For that, TreeRot adds a small login item while a scan is unreported and removes it
afterwards:

| System | Login item (your own account only) |
|---|---|
| Windows | A value named `TreeRot login check` under `HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run` |
| Linux | `~/.config/autostart/treerot-login-check.desktop` |
| macOS | `~/Library/LaunchAgents/io.github.arikpinhasov1998.treerot.login-check.plist` |

It runs `TreeRot --login-check` from where the program was when the scan started. If you move or
delete the program in the meantime, the login item simply does nothing, and it is safe to delete.

**The TreeRot logo on notifications.** Notifications show the TreeRot logo:

* **Windows:** the notification says **TreeRot** with its logo. For that, TreeRot writes its name
  and logo once under `HKEY_CURRENT_USER\Software\Classes\AppUserModelId\io.github.arikpinhasov1998.TreeRot`
  (your own account, no administrator). If that cannot be written, the notification still comes,
  labeled "Windows PowerShell".
* **Linux:** the logo appears next to the text.
* **macOS:** the Mac shows the icon of the program that sends the notification, which is the
  built-in Script Editor. The text says TreeRot.

The logo file they use is `.treerot/treerot.png` in your home folder. TreeRot writes it again
whenever it is missing.

**The TreeRot logo in the taskbar or dock.**

* **Windows:** the taskbar shows the logo, also when you run `treerot.py` with Python.
* **macOS:** the Dock shows the logo.
* **Linux:** desktops such as GNOME and KDE show a window's logo in the dock or taskbar only
  when a launcher entry matches the window. Otherwise they show a plain gear. So each time
  TreeRot opens, it makes sure a **hidden** entry exists at
  `~/.local/share/applications/treerot.desktop` (your own account,
  no administrator). It does not add TreeRot to your app menu. The first time, and after you
  move the program, the window disappears and comes back once, a second after it opens, so the
  dock picks up the logo. It is safe to delete.

**Where TreeRot keeps its records.** A small record of each background scan sits in
`.treerot/jobs` in your home folder (next to the logo file `.treerot/treerot.png`), and each scan writes its progress next to the report
(`<report>.status.json`). Removing a scan in **Background scans** deletes its record but keeps
the report and its status file.

**Scans started by older versions (Windows).** Versions before this one created a Windows
scheduled task that stored your password. Such scans still appear in **Background scans** and
**Remove** still deletes their task, and with it the stored password. New scans never create one.

### Long scans over RDP (remote desktop)

If you use Remote Desktop to a server: **close the RDP window** (disconnect) instead of **signing
out**. Disconnecting keeps your session, and your scan, alive. Signing out ends it. (Some servers
are set up to end disconnected sessions after a while; ask your administrator.)

---

## Recipes: common jobs

**"Which folders on our file server has nobody touched in 3 years?"**
1. Folder: `\\server\share`. Quick set: **Last 3 years**. Click **Add common system folders**.
2. Click **Run in background...**, save the report as HTML, and close TreeRot.
3. When the notification comes, open the report and look at **Largest unused folders**.

**"I need a printout for my manager."**
Scan, then **Export report...** > **PDF** > **The path to every unused folder**.

**"I want the list in Excel."**
Scan, then **Export CSV...**, and open the file in Excel.

**"Only show me the old stuff."**
After a scan, set **Show** to **Red only (not used)** and click **Expand to unused (red)**.

**"Why is this folder green? It looks old!"**
Hover over it. The note shows the newest file inside. Open the folder and sort by **Last file
activity (newest first)** to find it.

**"Was anything used during last year only?"**
From: `2025-01-01`, To: `2025-12-31`.

**"Scan a Linux server every month, automatically."**
Use the command line with cron. See the next section.

---

## Command line (for servers and scripts)

If you give TreeRot a folder path when you start it, **no window opens**. It just scans and
prints the result. That works over SSH, on servers without a screen, in cron and in Windows
Task Scheduler.

Examples:

```
TreeRot-cli.exe "\\server\share" --from 2024-10-28 --format summary --report share.html
./treerot /srv/share --from 2024-10-28 --format summary --report share.pdf
./treerot /srv/share --format csv -o share.csv --progress lines 2>> scan.log
./treerot /srv/share --years 3 --show red -o unused.csv
```

The options you will use most:

| Option | What it does |
|---|---|
| `--from DATE`, `--to DATE` | The dates, like `2024-10-28`. |
| `--years N` | Shortcut: "the last N years". With no dates at all, TreeRot uses the last 2 years. |
| `--exclude NAME_OR_PATH` | Skip a folder (use it as many times as you like). |
| `--exclude-common` | Skip the usual system clutter (same as the button). |
| `--exclude-file FILE` | Read skips from a text file, one per line (`#` starts a comment). |
| `--format summary` / `tree` / `csv` | Just the totals, a colored tree, or a spreadsheet. |
| `--depth N` or `all` | How many levels the tree shows (default 3). |
| `--show red` / `green` / `gray` | Only one color. `--stale-only` = `--show red`. |
| `--sort size` / `name` / `oldest` / `newest` | Order of the tree. |
| `-o FILE` | Write the result to a file instead of the screen. |
| `--report FILE.html` or `FILE.pdf` | Also save a report. |
| `--report-tree N` / `all` / `unused` | For PDF: how much of the tree to print (default 2). |
| `--browser PATH` | For PDF: which browser to use. |
| `--progress bar` / `lines` / `none` | `lines` writes one status line every 30 seconds, nice for log files. |
| `--precount` | Count first, for exact progress (slower). |
| `--created auto` / `ctime` / `off` | Whether created files count too (see [What "used" really means](#what-used-really-means)). |
| `-q` | Quiet: no progress. |

Run `treerot --help` for the full list.

**Exit codes** (useful in scripts): `0` OK, `2` bad option or path, `3` window not available,
`130` stopped with Ctrl+C.

**Windows tips:**
* Use the **UNC path** (`\\server\share`) in Task Scheduler, not a drive letter like `Z:`.
  Drive letters often don't exist when a task runs on its own.
* Don't end a quoted path with a backslash: write `"C:\Data"`, not `"C:\Data\"`.

### Linux and macOS: scans that outlive your terminal

If you close an SSH window, the programs you started in it usually stop. These tools keep a
command-line scan running:

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
unpacked the program), because they do not start in your current folder. To keep a `--user`
systemd unit running after you log out, run `loginctl enable-linger` once. These commands were
written for this README and have not all been run on every system.

### A monthly scan with cron (Linux)

Type `crontab -e` and add this line. It scans on the 1st of every month at 2 in the morning:

```
0 2 1 * * /opt/treerot/treerot /srv/share --years 2 --format summary --report /srv/reports/share.html -q
```

---

## When something goes wrong

| Problem | What to do |
|---|---|
| Windows says "Windows protected your PC". | Click **More info** > **Run anyway**. See [Start it the first time](#2-start-it-the-first-time). |
| Mac says the app "cannot be opened". | **System Settings > Privacy & Security > Open Anyway**. |
| On a Mac, every folder on a network share is gray. | Allow TreeRot under **Privacy & Security > Files and Folders > Network Volumes**. |
| Some folders are gray. | Gray means empty, or TreeRot was not allowed in. Hover to see which. Ask for read access to that folder, or ignore it. |
| A folder I know is old shows green. | Hover over it to see which file made it green. On Linux, renaming files or changing permissions can do it (see [What "used" really means](#what-used-really-means)). |
| The scan is very slow. | Network shares are slower than local disks. Add exclusions for big folders you don't care about, or use **Run in background...** and do something else. |
| The time left jumps around. | The first scan of a path is a guess. Tick **Count first** for exact numbers, or just scan again: the second time is close to exact. |
| PDF says no browser was found. | Install Edge or Chrome, or save the **HTML** report instead. See [How the PDF is made](#how-the-pdf-is-made). |
| The background scan says **Stopped**. | Someone logged off or the computer restarted. Start it again. |
| The window is dark but I want it light (or the other way round). | Set **Appearance** to **Light** or **Dark**. **System** copies your computer's setting. |
| I got no notification. | Check the computer's "Do Not Disturb" or focus mode. Open **Background scans** to see the result anyway. |
| Linux: "tkinter is not installed" when running the Python file. | Run `sudo apt install python3-tk`, or use the downloaded program, which already includes it. |
| Linux: "GLIBC not found". | Your Linux is too old for the download; use [Run from source](#run-from-source). |

---

## Words you might not know

* **Folder / directory:** a box that holds files and other folders.
* **Path:** the address of a folder, like `C:\Data\Projects` or `/srv/share/projects`.
* **Network share:** a folder that lives on another computer (a server) and that you open over
  the network.
* **UNC path:** the Windows address of a network share: `\\server\share`.
* **Mapped drive:** a network share that Windows shows as a drive letter, like `Z:`.
* **Exclude:** tell TreeRot to skip a folder.
* **Recursive:** "all the way down": inside, and inside of inside, and so on.
* **HTML report:** a web page saved as a file. Double-click to open it in your browser.
* **CSV:** a simple spreadsheet file.
* **Command line / terminal:** a window where you type commands instead of clicking.
* **RDP / Remote Desktop:** using another computer's screen from yours, over the network.
* **Log off / log out / sign out:** fully leave your account, which closes all your programs.
  Locking the screen is **not** logging off.
* **Symlink:** a shortcut that points to another folder.

---

## What has and has not been tested

The automatic tests have so far been run only on the developer's computers. GitHub's build is set
up to run the same tests on Windows, Linux and macOS before it builds anything, but that workflow
has not run yet, so nothing is proven on those systems. Background scans have been run for real
on Linux (Ubuntu, systemd) only; the steps under [Check on real computers](#check-on-real-computers)
have not been tried on Windows or macOS yet. Please run that checklist before you rely on them.

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
13. After every scan has been reported, check the login item from the table in
    [Run in background](#run-in-background). *It is gone.*

**D. Optional, for developers**

14. If Python is installed, open a terminal in the TreeRot folder and run
    `python -m unittest discover -s tests -v`. *Every test passes.*

**E. Appearance (Windows and macOS)**

15. Set **Appearance** to **Dark**, then **Light**. *The whole window, the title bar on Windows,
    and dialogs such as **Export report...** and **About** change with it; all text stays
    readable.*
16. Set it to **System**, then switch the computer between light and dark mode. *TreeRot
    follows within a few seconds.*

**F. The logo**

17. *Windows:* start `TreeRot.exe`. *The taskbar button, the window's corner and every dialog
    show the TreeRot logo.* Finish a background scan: *the notification says **TreeRot** and
    shows the logo.*
18. *Every system:* open an HTML report in a browser. *The browser tab shows the logo.*

**G. The tray (every system)**

19. Close the TreeRot window. *The window goes away, the TreeRot icon stays in the tray (menu
    bar on a Mac), and a notification says so the first time.* Click the icon: *the window
    comes back.*
20. Right-click the icon. *A menu with Open TreeRot, Background scans, Start with my computer
    and Quit TreeRot appears and closes again when you click elsewhere.* Choose **Quit
    TreeRot**: *the icon goes away.*
21. Tick **Start with my computer**, log off and on. *TreeRot starts with only its icon
    showing.* Untick it, log off and on: *it does not start.*
22. With TreeRot open, start it again. *The open window comes to the front; no second icon
    appears.*

---

## For developers

### Run from source

Requires Python 3.8 or newer and nothing else (standard library only):

```
python treerot.py                 # window
python treerot.py /srv/share      # command line
```

The window needs Python's tkinter: on Linux `sudo apt install python3-tk`; on macOS use Python
from python.org (Apple's built-in Python has an old, buggy Tk).

### Tests

Run the tests from the project folder:

```
python3 -m unittest discover -s tests -v
```

The window tests skip themselves when there is no display. On a Linux server without a desktop
use `xvfb-run -a python3 -m unittest discover -s tests -v`. The suite takes several minutes.
The GitHub workflow is set up to run it on Windows, Linux and macOS, on Python 3.13 and
3.8 where GitHub offers 3.8, before it builds anything, so that a failure stops the build.

### Build the programs yourself

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

### Publishing a release

GitHub builds every version for you (see `.github/workflows/release.yml`):

1. Change `__version__` in `treerot.py`, commit and push.
2. Tag the same version and push the tag:
   ```
   git tag v1.3.0
   git push origin v1.3.0
   ```
3. GitHub Actions is set up to run the tests on Windows, Linux and macOS, then to build the
   Windows, Linux and macOS (Apple Silicon and Intel) versions on their own systems, check that
   each one starts and can scan a folder, and publish them with `SHA256SUMS.txt` as a new
   release. The build stops if a test fails or if the tag does not match `__version__`.

To test the builds without publishing, open the **Actions** tab, choose **Build and release** and
click **Run workflow**; the programs appear under *Artifacts* on the run's page.

Dependabot proposes updates for the build tools once a month (`.github/dependabot.yml`).
