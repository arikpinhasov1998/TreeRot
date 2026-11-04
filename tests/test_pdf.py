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


def read_pid(path):
    with open(path) as f:
        return int(f.read())


def alive(pid):
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
            os.kill(read_pid(self.pidfile), 9)
        except (OSError, ValueError):
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

    # ---- the whole process tree ends, and the temporary folder goes, on every exit path
    @unittest.skipIf(os.name == "nt", "uses a POSIX shell wrapper and os.kill")
    def test_timeout_ends_the_helper_process(self):
        with self.assertRaises(app.ReportError):
            self.write([self.browser("hang_child")], timeout=2)
        self.assertTrue(wait_dead(self.child_pid()))
        self.assertEqual(leftovers(self.d), [])

    @unittest.skipIf(os.name == "nt", "uses a POSIX shell wrapper and os.kill")
    def test_cancel_ends_the_helper_process(self):
        ev = threading.Event()
        threading.Timer(1.0, ev.set).start()
        with self.assertRaises(app.ReportCanceled):
            self.write([self.browser("hang_child")], timeout=60, cancel_event=ev)
        self.assertTrue(wait_dead(self.child_pid()))
        self.assertEqual(leftovers(self.d), [])

    @unittest.skipIf(os.name == "nt", "uses a POSIX shell wrapper and os.kill")
    def test_success_ends_the_helper_process(self):
        self.write([self.browser("good_child_hang")])
        self.assertTrue(os.path.exists(self.out))
        self.assertTrue(wait_dead(self.child_pid()))
        self.assertEqual(leftovers(self.d), [])

    @unittest.skipIf(os.name == "nt", "uses a POSIX shell wrapper and os.kill")
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


@unittest.skipIf(os.name == "nt", "uses a POSIX shell wrapper and os.kill")
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
