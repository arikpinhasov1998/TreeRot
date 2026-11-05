import contextlib
import io
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

from tests.helpers import OLD, app, make_tree
from tests.test_gui import tk_ok


class Awake(unittest.TestCase):
    def test_macos_runs_caffeinate_and_stops_it(self):
        popen = mock.Mock()
        with app.keep_awake("darwin", popen=popen, which=lambda n: "/usr/bin/caffeinate") as note:
            self.assertEqual(note, "")
            self.assertEqual(popen.call_args[0][0][0], "caffeinate")
        popen.return_value.terminate.assert_called_once()

    def test_linux_uses_systemd_inhibit(self):
        popen = mock.Mock()
        with app.keep_awake("linux", popen=popen, which=lambda n: "/bin/" + n) as note:
            self.assertEqual(note, "")
            self.assertEqual(popen.call_args[0][0][0], "systemd-inhibit")

    def test_linux_without_tool_gives_note_and_continues(self):
        with app.keep_awake("linux", which=lambda n: None) as note:
            self.assertIn("sleep", note)

    def test_windows_sets_and_clears_state(self):
        calls = []
        with app.keep_awake("win32", windows_api=calls.append) as note:
            self.assertEqual(note, "")
        self.assertEqual(calls, [0x80000001, 0x80000000])

    def test_failure_never_stops_the_scan(self):
        def boom(*a, **k):
            raise OSError("nope")
        with app.keep_awake("darwin", popen=boom, which=lambda n: "/x") as note:
            self.assertIn("sleep", note)

    def test_child_is_stopped_even_when_the_block_raises(self):
        popen = mock.Mock()
        with self.assertRaises(ValueError):
            with app.keep_awake("darwin", popen=popen, which=lambda n: "/x"):
                raise ValueError("scan failed")
        popen.return_value.terminate.assert_called_once()

    def test_release_all_stops_a_child_still_held(self):
        popen = mock.Mock()
        cm = app.keep_awake("darwin", popen=popen, which=lambda n: "/x")
        cm.__enter__()
        app.release_all_awake()
        popen.return_value.terminate.assert_called_once()
        cm.__exit__(None, None, None)          # releasing again is harmless

    def test_cli_prints_the_note_unless_quiet(self):
        with tempfile.TemporaryDirectory() as d:
            make_tree(d, {"a/f.txt": OLD})
            for extra, expect in (([], True), (["--quiet"], False)):
                err = io.StringIO()
                with mock.patch.object(app, "keep_awake",
                                       lambda: contextlib.nullcontext("NOSLEEP-NOTE")), \
                        mock.patch("sys.stderr", err), mock.patch("sys.stdout", io.StringIO()):
                    app.main(["--cli", d, "--progress", "none", "--format", "csv"] + extra)
                self.assertEqual("NOSLEEP-NOTE" in err.getvalue(), expect, extra)


@unittest.skipUnless(tk_ok(), "no display or tkinter")
class AwakeInWindow(unittest.TestCase):
    def _close_during_scan(self, popen_spy=None):
        """Starts a scan that never finishes by itself, closes the window, returns when the
        scan thread has stopped."""
        entered, left = threading.Event(), threading.Event()

        def slow_scan(root, cancel_event, *a, **k):
            entered.set()
            cancel_event.wait(20)
            return {}, True

        real_keep_awake = app.keep_awake

        @contextlib.contextmanager
        def tracked():
            try:
                with real_keep_awake() as note:
                    yield note
            finally:
                left.set()

        def ready(w):
            w.path_var.set(self.dir)
            w.created_var.set(False)
            w._start()

            def close():
                if entered.is_set():
                    w._on_close()
                else:
                    w.after(50, close)
            w.after(50, close)

        with mock.patch.object(app, "scan_tree", slow_scan), \
                mock.patch.object(app, "keep_awake", tracked):
            app.run_gui(on_ready=ready)
        return left

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        make_tree(self.dir, {"a/f.txt": OLD})
        self.addCleanup(shutil.rmtree, self.dir, True)

    def test_closing_during_a_scan_releases_keep_awake(self):
        left = self._close_during_scan()
        self.assertTrue(left.wait(5), "keep_awake was not released after the window closed")

    @unittest.skipUnless(sys.platform == "darwin" and shutil.which("caffeinate"),
                         "needs caffeinate")
    def test_closing_leaves_no_caffeinate_child(self):
        children = []
        real = subprocess.Popen

        def spy(*a, **k):
            p = real(*a, **k)
            children.append(p)
            return p
        with mock.patch.object(app.subprocess, "Popen", spy):
            self._close_during_scan()
        awake = [c for c in children if c.args[0] == "caffeinate"]
        self.assertTrue(awake)
        for c in awake:
            try:
                c.wait(5)
            except subprocess.TimeoutExpired:
                c.kill()
                self.fail("caffeinate still running after close")
