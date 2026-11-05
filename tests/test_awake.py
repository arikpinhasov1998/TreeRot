import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from tests.helpers import OLD, app, make_tree
from tests.test_gui import tk_ok


def running_popen():
    """A Popen stand-in whose child is still running when first checked."""
    popen = mock.Mock()
    popen.return_value.wait.side_effect = [subprocess.TimeoutExpired("x", 0.2), 0, 0]
    return popen


class Awake(unittest.TestCase):
    def test_macos_runs_caffeinate_and_stops_it(self):
        popen = running_popen()
        with app.keep_awake("darwin", popen=popen, which=lambda n: "/usr/bin/caffeinate") as note:
            self.assertEqual(note, "")
            self.assertEqual(popen.call_args[0][0][0], "caffeinate")
        popen.return_value.terminate.assert_called_once()

    def test_linux_uses_systemd_inhibit(self):
        popen = running_popen()
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
        popen = running_popen()
        with self.assertRaises(ValueError):
            with app.keep_awake("darwin", popen=popen, which=lambda n: "/x"):
                raise ValueError("scan failed")
        popen.return_value.terminate.assert_called_once()

    def test_a_helper_that_exits_at_once_gives_the_note(self):
        popen = mock.Mock()
        popen.return_value.wait.return_value = 1          # already gone
        with app.keep_awake("linux", popen=popen, which=lambda n: "/bin/" + n) as note:
            self.assertIn("sleep", note)
        self.assertEqual(app._AWAKE_CHILDREN, {})

    def test_a_real_helper_that_fails_at_once_gives_the_note(self):
        with tempfile.TemporaryDirectory() as d:
            for name in ("caffeinate", "systemd-inhibit"):
                path = os.path.join(d, name)
                with open(path, "w") as f:
                    f.write("#!/bin/sh\nexit 1\n")
                os.chmod(path, 0o755)
                subprocess.run([path])            # the first run of a new file is slow on macOS
            with mock.patch.dict(os.environ, {"PATH": d + os.pathsep + os.environ["PATH"]}):
                for plat in ("darwin", "linux"):
                    with app.keep_awake(plat) as note:
                        self.assertIn("sleep", note, plat)

    def test_release_all_stops_a_child_still_held(self):
        popen = running_popen()
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


class StopHelper(unittest.TestCase):
    def test_a_child_that_ignores_terminate_is_killed(self):
        code = ("import signal, time\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
                "print('ready', flush=True)\ntime.sleep(60)")
        p = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE)
        self.addCleanup(p.stdout.close)
        p.stdout.readline()                   # the handler is installed
        try:
            app._stop_helper(p)
            self.assertIsNotNone(p.poll(), "the child survived SIGTERM and was not killed")
        finally:
            if p.poll() is None:
                p.kill()
                p.wait()

    def test_kill_is_used_after_terminate_times_out(self):
        child = mock.Mock()
        child.wait.side_effect = [subprocess.TimeoutExpired("x", 2), 0]
        app._stop_helper(child)
        child.terminate.assert_called_once()
        child.kill.assert_called_once()


def gone(pid, wait=5):
    """True once no process has this pid (polls for up to `wait` seconds)."""
    end = time.monotonic() + wait
    while time.monotonic() < end:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.05)
    return False


@unittest.skipIf(sys.platform == "win32", "POSIX shell and process groups")
class LinuxHelper(unittest.TestCase):
    def test_stopping_ends_the_forked_child_too(self):
        with tempfile.TemporaryDirectory() as d:
            fake = os.path.join(d, "systemd-inhibit")
            with open(fake, "w") as f:       # forks its command (does not exec it), like the real one
                f.write('#!/bin/sh\nwhile [ "${1#--}" != "$1" ]; do shift; done\n'
                        '"$@" &\necho $$ $! > "$PIDS"\nwait\n')
            os.chmod(fake, 0o755)
            pids = os.path.join(d, "pids")
            env = {"PATH": d + os.pathsep + os.environ["PATH"], "PIDS": pids}
            with mock.patch.dict(os.environ, env):
                with app.keep_awake("linux") as note:
                    self.assertEqual(note, "")
                    end = time.monotonic() + 5
                    while not os.path.exists(pids) and time.monotonic() < end:
                        time.sleep(0.05)
                    with open(pids) as f:
                        parent, child = [int(x) for x in f.read().split()]
                    os.kill(child, 0)         # both alive while held
            self.assertTrue(gone(parent), "systemd-inhibit stayed alive")
            self.assertTrue(gone(child), "its child was orphaned")

    def test_helper_is_started_in_its_own_group(self):
        popen = running_popen()
        with app.keep_awake("linux", popen=popen, which=lambda n: "/bin/" + n):
            pass
        self.assertTrue(popen.call_args[1].get("start_new_session"))

    def test_watcher_exits_by_itself_when_treerot_is_gone(self):
        dead = subprocess.Popen(["sleep", "0"])
        dead.wait()
        w = subprocess.Popen(app.awake_watcher_args(dead.pid, interval="0.2"))
        try:
            w.wait(timeout=10)
        except subprocess.TimeoutExpired:
            w.kill()
            self.fail("the watcher outlived the process it watches")

    def test_watcher_keeps_running_while_treerot_lives(self):
        w = subprocess.Popen(app.awake_watcher_args(os.getpid(), interval="0.2"))
        try:
            with self.assertRaises(subprocess.TimeoutExpired):
                w.wait(timeout=1)
        finally:
            w.kill()
            w.wait()


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
