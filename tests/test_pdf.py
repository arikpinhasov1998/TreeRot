import os
import stat
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime
from unittest import mock

from tests.helpers import OLD, app, make_tree, scan_rows
from tests.test_gui import GuiCase

GOOD = b"%PDF-1.4\nfake\n%%EOF\n"
OUT = ("import sys\n"
       "out = [a.split('=', 1)[1] for a in sys.argv if a.startswith('--print-to-pdf=')][0]\n")
# A helper process that outlives the browser's main process unless the whole tree is ended.
CHILD = ("import os, subprocess\n"
         "c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(300)'])\n"
         "open(os.environ['FAKE_PIDFILE'], 'w').write(str(c.pid))\n")
SCRIPTS = {
    "good": OUT + f"open(out, 'wb').write({GOOD!r})\n",
    "hang": "import time\ntime.sleep(300)\n",
    "fail": "import sys\nsys.stderr.write('boom')\nsys.exit(1)\n",
    "good_then_hang": OUT + f"open(out, 'wb').write({GOOD!r})\nimport time\ntime.sleep(300)\n",
    "hang_child": OUT + CHILD + "import time\ntime.sleep(300)\n",
    "good_child_hang": OUT + CHILD + f"open(out, 'wb').write({GOOD!r})\nimport time\ntime.sleep(300)\n",
    # a launcher that hands the work to a child and exits at once; the child writes the PDF later
    "fork_launcher": OUT + ("import subprocess\ncode = " + repr(
        f"import time,sys; time.sleep(1.5); open(sys.argv[1], 'wb').write({GOOD!r})") +
        "\nsubprocess.Popen([sys.executable, '-c', code, out])\n"),
    # fails with a message and exits, but leaves a helper running; logs each launch's headless flag
    "fail_with_helper": OUT + CHILD + (
        "open(os.environ['FAKE_LOG'], 'a').write([a for a in sys.argv if a.startswith('--headless')][0] + '\\n')\n"
        "sys.stderr.write('boom from the browser')\nsys.exit(3)\n"),
    "child_then_exit": OUT + CHILD + "sys.exit(1)\n",
}
META = {"root": "x", "excludes": [], "excluded_count": 0, "scanned_at": "now", "elapsed": 1,
        "canceled": False, "activity": "modified", "computer": "c", "basis_note": ""}


def make_browser(folder, kind):
    py = os.path.join(folder, kind + ".py")
    with open(py, "w") as f:
        f.write(SCRIPTS[kind])
    if os.name == "nt":
        path = os.path.join(folder, kind + ".cmd")
        with open(path, "w") as f:
            f.write(f'@"{sys.executable}" "{py}" %*\n')
    else:
        path = os.path.join(folder, kind)
        with open(path, "w") as f:
            f.write(f'#!/bin/sh\nexec "{sys.executable}" "{py}" "$@"\n')
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
    return path


def read_pid(path, seconds=15):
    """The helper's pid, waiting (bounded) for a slow start; fails clearly if it never appears."""
    end = time.monotonic() + seconds
    while True:
        try:
            with open(path) as f:
                return int(f.read())
        except (OSError, ValueError):       # not there yet, or half written
            if time.monotonic() > end:
                raise AssertionError(f"the fake browser never wrote its helper's pid to {path}")
            time.sleep(0.05)


def alive(pid):
    if os.name == "nt":     # os.kill(pid, 0) would END the process on Windows
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = wintypes.HANDLE
        h = k32.OpenProcess(0x1000, False, pid)        # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = wintypes.DWORD()
        ok = k32.GetExitCodeProcess(h, ctypes.byref(code))
        k32.CloseHandle(h)
        return bool(ok) and code.value == 259          # STILL_ACTIVE
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def wait_dead(pid, seconds=5):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if not alive(pid):
            return True
        time.sleep(0.1)
    return not alive(pid)


def leftovers(folder):
    return [n for n in os.listdir(folder) if n.startswith(".treerot_report_")]


class Pdf(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.d = d.name
        make_tree(os.path.join(self.d, "share"), {"a/f.txt": OLD})
        self.rows = list(scan_rows(os.path.join(self.d, "share"), datetime(2024, 1, 1)).values())
        self.out = os.path.join(self.d, "r.pdf")
        self.pidfile = os.path.join(self.d, "child.pid")
        env = mock.patch.dict(os.environ, {"FAKE_PIDFILE": self.pidfile})
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(self._reap_child)

    def _reap_child(self):          # a failing test must not leave a sleeper behind
        try:
            os.kill(read_pid(self.pidfile, 0), 9)
        except (OSError, ValueError, AssertionError):
            pass

    def browser(self, kind):
        return make_browser(self.d, kind)

    def child_pid(self):
        return read_pid(self.pidfile)

    def write(self, browsers, **kw):
        with mock.patch.object(app, "find_browsers", return_value=browsers), \
                mock.patch.object(app, "pdf_timeout", return_value=kw.pop("timeout", 3)):
            app.write_report(self.out, self.rows, META, **kw)

    def test_good_browser(self):
        self.write([self.browser("good")])
        self.assertEqual(open(self.out, "rb").read(5), b"%PDF-")
        self.assertEqual(leftovers(self.d), [])

    def test_hung_browser_moves_to_next(self):
        t = time.monotonic()
        self.write([self.browser("hang"), self.browser("good")])
        self.assertTrue(os.path.exists(self.out))
        self.assertLess(time.monotonic() - t, 30)

    def test_finished_pdf_kept_when_browser_never_exits(self):
        self.write([self.browser("good_then_hang")])
        self.assertTrue(os.path.exists(self.out))

    def test_launcher_that_exits_while_its_child_prints_is_waited_for(self):
        t = time.monotonic()
        self.write([self.browser("fork_launcher")], timeout=20)
        self.assertEqual(open(self.out, "rb").read(5), b"%PDF-")
        self.assertGreater(time.monotonic() - t, 1.4)
        self.assertEqual(leftovers(self.d), [])

    def test_browser_that_exits_with_an_error_but_leaves_a_helper_is_a_failure_not_a_hang(self):
        log = os.path.join(self.d, "launches.log")
        with mock.patch.dict(os.environ, {"FAKE_LOG": log}):
            with self.assertRaises(app.ReportError) as c:
                self.write([self.browser("fail_with_helper")], timeout=2)
        msg = str(c.exception)
        self.assertIn("boom from the browser", msg)
        self.assertIn("3", msg)
        self.assertNotIn("did not finish", msg)
        with open(log) as f:
            self.assertEqual(f.read().split(), ["--headless=new", "--headless"])   # retry ran
        self.assertTrue(wait_dead(self.child_pid()))

    def test_a_true_hang_keeps_the_did_not_finish_message(self):
        with self.assertRaises(app.ReportError) as c:
            self.write([self.browser("hang_child")], timeout=2)
        self.assertIn("did not finish within 2 seconds", str(c.exception))

    def test_a_browser_that_fails_with_nothing_left_fails_fast(self):
        t = time.monotonic()
        with self.assertRaises(app.ReportError):
            self.write([self.browser("fail")], timeout=30)
        self.assertLess(time.monotonic() - t, 5)

    def test_failure_names_each_browser_and_html(self):
        hang, fail = self.browser("hang"), self.browser("fail")
        with self.assertRaises(app.ReportError) as c:
            self.write([hang, fail])
        msg = str(c.exception)
        self.assertIn(os.path.basename(hang), msg)
        self.assertIn(os.path.basename(fail), msg)
        self.assertIn("HTML", msg)
        self.assertEqual(leftovers(self.d), [])
        self.assertFalse(os.path.exists(self.out))

    def test_cancel_stops_quickly(self):
        ev = threading.Event()
        threading.Timer(0.5, ev.set).start()
        t = time.monotonic()
        with self.assertRaises(app.ReportCanceled):
            self.write([self.browser("hang")], timeout=60, cancel_event=ev)
        self.assertLess(time.monotonic() - t, 15)
        self.assertEqual(leftovers(self.d), [])

    def test_already_canceled_never_starts_a_browser(self):
        ev = threading.Event()
        ev.set()
        with self.assertRaises(app.ReportCanceled):
            self.write([self.browser("hang_child")], cancel_event=ev)
        self.assertFalse(os.path.exists(self.pidfile))
        self.assertEqual(leftovers(self.d), [])

    def test_timeout_scale(self):
        self.assertEqual(app.pdf_timeout(0), 60)
        self.assertEqual(app.pdf_timeout(500), 70)
        self.assertEqual(app.pdf_timeout(10 ** 7), 600)

    def test_browser_order(self):
        names = ["Brave", "chromium", "chrome", "edge"]
        ranked = sorted(names, key=app._browser_rank)
        self.assertEqual(ranked, ["edge", "chrome", "chromium", "Brave"])

    def test_chrome_ranks_ahead_of_chromium_wherever_each_is_installed(self):
        pf, la = "C:\\PF", "C:\\LA"
        chromium = os.path.join(pf, "Chromium", "Application", "chrome.exe")
        chrome = os.path.join(la, "Google", "Chrome", "Application", "chrome.exe")
        brave = os.path.join(la, "BraveSoftware", "Brave-Browser", "Application", "brave.exe")
        present = {chromium, chrome, brave}
        env = {"ProgramFiles": pf, "ProgramFiles(x86)": "", "LOCALAPPDATA": la}
        with mock.patch.object(app.sys, "platform", "win32"), \
                mock.patch.dict(os.environ, env), \
                mock.patch.object(app.os.path, "isfile", side_effect=lambda p: p in present), \
                mock.patch.object(app.shutil, "which", return_value=None):
            self.assertEqual(app.find_browsers(), [chrome, chromium, brave])
        self.assertLess(app._browser_rank("/home/edgar/x/Chrome/Application/chrome.exe"),
                        app._browser_rank("/opt/Chromium/Application/chrome.exe"))
        # a user folder with a browser's name in it must not decide the rank
        self.assertEqual(app._browser_rank("/home/edge/apps/brave"), 3)

    def test_brave_is_found_last_on_every_system(self):
        env = {"ProgramFiles": "C:\\PF", "ProgramFiles(x86)": "C:\\PF86", "LOCALAPPDATA": "C:\\LA"}
        for plat in ("win32", "linux", "darwin"):
            with mock.patch.object(app.sys, "platform", plat), \
                    mock.patch.dict(os.environ, env), \
                    mock.patch.object(app.os.path, "isfile", return_value=True), \
                    mock.patch.object(app.shutil, "which", side_effect=lambda n: "/usr/bin/" + n):
                names = [os.path.basename(p).lower().replace("\\", "/").split("/")[-1]
                         for p in app.find_browsers()]
            self.assertTrue(any("brave" in n for n in names), plat)
            self.assertIn("brave", names[-1], plat)
            self.assertTrue(any("edge" in n for n in names[:1]), plat)

    # ---- Windows job objects, exercised here with fakes (the real calls only run on Windows)
    def test_without_a_job_object_the_export_still_works(self):
        class Boom:
            def __init__(self):
                raise OSError("no job")
        with mock.patch.object(app.sys, "platform", "win32"), \
                mock.patch.object(app, "_WinJob", Boom, create=True):
            self.assertIsNone(app._new_job())

    def test_no_job_on_other_systems(self):
        with mock.patch.object(app.sys, "platform", "linux"):
            self.assertIsNone(app._new_job())

    def test_failed_assignment_closes_the_job_and_falls_back(self):
        job = mock.Mock()
        job.assign.side_effect = OSError("denied")
        self.assertIsNone(app._attach_job(mock.Mock(pid=1), job))
        job.close.assert_called_once()
        good = mock.Mock()
        self.assertIs(app._attach_job(mock.Mock(pid=1), good), good)

    def test_the_job_is_made_before_the_browser_starts(self):
        order = []
        real_popen = app.subprocess.Popen

        def popen(*a, **k):
            order.append("popen")
            return real_popen(*a, **k)
        job = mock.Mock()
        with mock.patch.object(app, "_new_job", side_effect=lambda: order.append("job") or job), \
                mock.patch.object(app, "_attach_job",
                                  side_effect=lambda p, j: order.append("attach") or None), \
                mock.patch.object(app.subprocess, "Popen", popen):
            self.write([self.browser("good")])
        self.assertEqual(order, ["job", "popen", "attach"])

    def test_job_structures_have_the_windows_sizes(self):
        import ctypes
        k = mock.MagicMock()
        k.SetInformationJobObject.return_value = 1
        with mock.patch.object(ctypes, "WinDLL", create=True, return_value=k):
            job = app._WinJob()
        self.assertEqual(k.SetInformationJobObject.call_args[0][3], 144)
        self.assertEqual(ctypes.sizeof(job._Accounting), 48)

    def test_job_counts_as_alive_after_the_launcher_exits(self):
        job = mock.Mock()
        job.active.return_value = 2
        proc = mock.Mock(pid=1, job=job)
        proc.poll.return_value = 0
        with mock.patch.object(app.sys, "platform", "win32"):
            self.assertTrue(app._tree_alive(proc))
            job.active.return_value = 0
            self.assertFalse(app._tree_alive(proc))

    def test_kill_uses_the_job_and_closes_it(self):
        job = mock.Mock()
        proc = mock.Mock(pid=1, job=job)
        proc.poll.return_value = 0
        with mock.patch.object(app.sys, "platform", "win32"), \
                mock.patch.object(app.subprocess, "run") as run:
            app._kill_tree(proc)
        job.terminate.assert_called_once()
        job.close.assert_called_once()
        run.assert_not_called()

    def test_kill_falls_back_to_taskkill_without_a_job(self):
        proc = mock.Mock(pid=77, job=None)
        proc.poll.return_value = None
        with mock.patch.object(app.sys, "platform", "win32"), \
                mock.patch.object(app.subprocess, "run") as run:
            app._kill_tree(proc)
        self.assertIn("taskkill", run.call_args[0][0])

    # ---- closing the app while a report is being made
    def test_html_report_stops_when_canceled_and_leaves_nothing(self):
        out = os.path.join(self.d, "r.html")
        ev = threading.Event()
        ev.set()
        with self.assertRaises(app.ReportCanceled):
            app.write_report(out, self.rows, META, cancel_event=ev)
        self.assertEqual([n for n in os.listdir(self.d) if n.startswith("r.html")], [])

    def test_html_report_checks_cancel_while_it_works(self):
        out = os.path.join(self.d, "r.html")

        class LateCancel:
            def __init__(self):
                self.n = 0

            def is_set(self):
                self.n += 1
                return self.n > 3
        with self.assertRaises(app.ReportCanceled):
            app.write_report(out, self.rows, META, cancel_event=LateCancel())
        self.assertEqual([n for n in os.listdir(self.d) if n.startswith("r.html")], [])

    def test_html_report_without_cancel_still_writes(self):
        out = os.path.join(self.d, "r.html")
        app.write_report(out, self.rows, META)
        self.assertIn("<html", open(out, encoding="utf-8").read(200))
        self.assertEqual([n for n in os.listdir(self.d) if n.endswith(".part")], [])

    def test_end_live_exports_ends_a_browser_whose_worker_is_stuck(self):
        errors = []

        def work():
            try:
                self.write([self.browser("hang_child")], timeout=60)
            except app.ReportError as e:
                errors.append(e)
        t = threading.Thread(target=work, daemon=True)
        t.start()
        end = time.monotonic() + 15
        while not os.path.exists(self.pidfile) and time.monotonic() < end:
            time.sleep(0.05)
        pid = self.child_pid()
        app._end_live_exports()              # what closing the window does after its wait
        self.assertTrue(wait_dead(pid))
        self.assertEqual(leftovers(self.d), [])
        t.join(20)
        self.assertFalse(t.is_alive())
        app._end_live_exports()              # a second caller is harmless
        self.assertEqual(leftovers(self.d), [])

    # ---- the whole process tree ends, and the temporary folder goes, on every exit path
    def test_timeout_ends_the_helper_process(self):
        with self.assertRaises(app.ReportError):
            self.write([self.browser("hang_child")], timeout=6)
        self.assertTrue(wait_dead(self.child_pid()))
        self.assertEqual(leftovers(self.d), [])

    def test_cancel_ends_the_helper_process(self):
        ev = threading.Event()
        # cancel only once the helper exists, however slowly the fake browser started
        threading.Thread(target=lambda: (read_pid(self.pidfile), ev.set()), daemon=True).start()
        with self.assertRaises(app.ReportCanceled):
            self.write([self.browser("hang_child")], timeout=60, cancel_event=ev)
        self.assertTrue(wait_dead(self.child_pid()))
        self.assertEqual(leftovers(self.d), [])

    def test_success_ends_the_helper_process(self):
        self.write([self.browser("good_child_hang")])
        self.assertTrue(os.path.exists(self.out))
        self.assertTrue(wait_dead(self.child_pid()))
        self.assertEqual(leftovers(self.d), [])

    def test_helper_left_behind_by_a_failed_browser_is_ended(self):
        with self.assertRaises(app.ReportError):
            self.write([self.browser("child_then_exit")])
        self.assertTrue(wait_dead(self.child_pid()))
        self.assertEqual(leftovers(self.d), [])

    def test_unstartable_browser_cleans_up(self):
        with self.assertRaises(app.ReportError):
            self.write([os.path.join(self.d, "missing")])
        self.assertEqual(leftovers(self.d), [])


def when(w, cond, then, seconds=20):
    """Runs then() from the Tk loop once cond() holds. No nested update(): Tk 8.5 never returns."""
    end = time.monotonic() + seconds

    def step():
        if cond() or time.monotonic() > end:
            then()
        else:
            w.after(50, step)
    w.after(50, step)


class WindowClose(GuiCase):
    def test_closing_the_window_during_an_export_ends_the_browser(self):
        with tempfile.TemporaryDirectory() as d:
            share = os.path.join(d, "share")
            make_tree(share, {"a/f.txt": OLD})
            out_dir = os.path.join(d, "out")
            os.mkdir(out_dir)
            out = os.path.join(out_dir, "r.pdf")
            pidfile = os.path.join(d, "child.pid")
            browser = make_browser(d, "hang_child")
            seen = {}

            def check(w):
                w._save_report("pdf", "2", None)

                def started():
                    seen["pid"] = read_pid(pidfile)
                    seen["workdir"] = leftovers(out_dir)
                    w._on_close()
                when(w, lambda: os.path.exists(pidfile), started, 15)

            try:
                with mock.patch.dict(os.environ, {"FAKE_PIDFILE": pidfile}), \
                        mock.patch.object(app, "find_browsers", return_value=[browser]), \
                        mock.patch("tkinter.filedialog.asksaveasfilename", return_value=out):
                    self.drive(share, check, finished=lambda: "pid" in seen)
                self.assertTrue(seen["workdir"], "the export never started its work folder")
                self.assertTrue(wait_dead(seen["pid"]))
                self.assertEqual(leftovers(out_dir), [])
                self.assertFalse(os.path.exists(out))
            finally:
                if "pid" in seen:
                    try:
                        os.kill(seen["pid"], 9)
                    except OSError:
                        pass

    def test_close_does_not_wait_forever_and_still_cleans_up(self):
        with tempfile.TemporaryDirectory() as d:
            share = os.path.join(d, "share")
            make_tree(share, {"a/f.txt": OLD})
            out_dir = os.path.join(d, "out")
            os.mkdir(out_dir)
            pidfile = os.path.join(d, "child.pid")
            browser = make_browser(d, "hang_child")
            seen = {}

            def check(w):
                w._save_report("pdf", "2", None)

                def started():
                    seen["pid"] = read_pid(pidfile)
                    w.REPORT_JOIN_SECONDS = 0       # the worker is "stuck": do not wait for it
                    w._on_close()
                when(w, lambda: os.path.exists(pidfile), started, 15)

            try:
                with mock.patch.dict(os.environ, {"FAKE_PIDFILE": pidfile}), \
                        mock.patch.object(app, "find_browsers", return_value=[browser]), \
                        mock.patch("tkinter.filedialog.asksaveasfilename",
                                   return_value=os.path.join(out_dir, "r.pdf")):
                    self.drive(share, check, finished=lambda: "pid" in seen)
                self.assertTrue(wait_dead(seen["pid"]))
                self.assertEqual(leftovers(out_dir), [])
            finally:
                if "pid" in seen:
                    try:
                        os.kill(seen["pid"], 9)
                    except OSError:
                        pass

    def test_window_is_hidden_before_it_waits(self):
        with tempfile.TemporaryDirectory() as d:
            share = os.path.join(d, "share")
            make_tree(share, {"a/f.txt": OLD})
            seen = {}

            def check(w):
                w._end_report = lambda: seen.update(state=w.state())
                w._on_close()
                seen["closed"] = True
            self.drive(share, check, finished=lambda: "closed" in seen)
            self.assertEqual(seen["state"], "withdrawn")

    def test_cancel_button_cancels_the_export_without_touching_the_scan_flag(self):
        with tempfile.TemporaryDirectory() as d:
            share = os.path.join(d, "share")
            make_tree(share, {"a/f.txt": OLD})
            out = os.path.join(d, "r.pdf")
            browser = make_browser(d, "hang")
            seen = {}

            def check(w):
                with mock.patch("tkinter.filedialog.asksaveasfilename", return_value=out):
                    w._save_report("pdf", "2", None)
                seen["btn"] = str(w.cancel_btn.cget("state"))

                def canceled():
                    seen["status"] = w.status_var.get()
                    seen["report_btn"] = str(w.report_btn.cget("state"))
                w.after(500, w._cancel)
                when(w, lambda: "canceled" in w.status_var.get(), canceled)

            with mock.patch.object(app, "find_browsers", return_value=[browser]):
                self.drive(share, check, finished=lambda: "status" in seen)
            self.assertEqual(seen["btn"], "normal")
            self.assertIn("canceled", seen["status"])
            self.assertEqual(seen["report_btn"], "normal")
            self.assertFalse(os.path.exists(out))
            self.assertEqual(leftovers(d), [])


class ScanDuringExport(GuiCase):
    def test_scan_is_refused_during_an_export_and_changes_nothing(self):
        from tkinter import messagebox
        with tempfile.TemporaryDirectory() as d:
            share = os.path.join(d, "share")
            make_tree(share, {"a/f.txt": OLD})
            out = os.path.join(d, "r.pdf")
            browser = make_browser(d, "hang")
            seen = {}

            def check(w):
                before = w.period_text
                with mock.patch("tkinter.filedialog.asksaveasfilename", return_value=out):
                    w._save_report("pdf", "2", None)
                w.from_var.set("2020-01-01")
                with mock.patch.object(messagebox, "showinfo") as info:
                    w._start()
                seen["info"] = info.called
                seen["same"] = w.period_text == before
                seen["rows"] = bool(w.rows)
                w._cancel()
                when(w, lambda: "canceled" in w.status_var.get(), lambda: seen.update(done=1))

            with mock.patch.object(app, "find_browsers", return_value=[browser]):
                self.drive(share, check, finished=lambda: "done" in seen)
            self.assertTrue(seen["info"])
            self.assertTrue(seen["same"])
            self.assertTrue(seen["rows"])
