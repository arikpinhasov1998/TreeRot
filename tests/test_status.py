import json
import os
import tempfile
import threading
import time
import unittest
from unittest import mock

from tests.helpers import OLD, app, make_tree


class Status(unittest.TestCase):
    def setUp(self):
        patch = mock.patch.object(app.StatusWriter, "RETRY_DELAY", 0)
        patch.start()
        self.addCleanup(patch.stop)

    def test_success_writes_finished(self):
        with tempfile.TemporaryDirectory() as d:
            make_tree(os.path.join(d, "s"), {"a/f.txt": OLD})
            st, rep = os.path.join(d, "x.json"), os.path.join(d, "r.html")
            rc = app.main([os.path.join(d, "s"), "--format", "summary", "--progress", "none",
                           "-q", "--report", rep, "--status-file", st])
            self.assertEqual(rc, 0)
            s = app.read_status(st)
            self.assertEqual(s["state"], "finished")
            self.assertEqual(s["report"], rep)
            self.assertTrue(os.path.exists(rep))
            self.assertEqual(sorted(s), ["counts", "error", "percent", "report", "state",
                                         "times", "updated"])
            self.assertEqual(os.listdir(d).count("x.json"), 1)
            self.assertFalse([n for n in os.listdir(d) if n.endswith(".tmp")])

    def test_bad_path_writes_failed(self):
        with tempfile.TemporaryDirectory() as d:
            st = os.path.join(d, "x.json")
            rc = app.main([os.path.join(d, "missing"), "--format", "summary", "-q",
                           "--status-file", st])
            self.assertEqual(rc, 2)
            s = app.read_status(st)
            self.assertEqual(s["state"], "failed")
            self.assertIn("is not a folder", s["error"])

    def test_report_failure_gives_reason(self):
        with tempfile.TemporaryDirectory() as d:
            make_tree(os.path.join(d, "s"), {"a/f.txt": OLD})
            st = os.path.join(d, "x.json")
            rep = os.path.join(d, "nodir", "r.html")
            rc = app.main([os.path.join(d, "s"), "--format", "summary", "-q",
                           "--report", rep, "--status-file", st])
            self.assertEqual(rc, 2)
            s = app.read_status(st)
            self.assertEqual(s["state"], "failed")
            self.assertIn("Cannot write the report", s["error"])

    def test_exception_writes_failed_and_reraises(self):
        with tempfile.TemporaryDirectory() as d:
            make_tree(os.path.join(d, "s"), {"a/f.txt": OLD})
            st = os.path.join(d, "x.json")
            with mock.patch.object(app, "scan_tree", side_effect=RuntimeError("boom")):
                with self.assertRaises(RuntimeError):
                    app.main([os.path.join(d, "s"), "-q", "--status-file", st])
            s = app.read_status(st)
            self.assertEqual((s["state"], s["error"]), ("failed", "boom"))

    def test_unwritable_status_never_stops_scan(self):
        with tempfile.TemporaryDirectory() as d:
            make_tree(os.path.join(d, "s"), {"a/f.txt": OLD})
            st = os.path.join(d, "no", "such", "dir", "x.json")
            rc = app.main([os.path.join(d, "s"), "--format", "summary", "-q",
                           "--status-file", st])
            self.assertEqual(rc, 0)

    def test_odd_write_errors_never_escape(self):
        with tempfile.TemporaryDirectory() as d:
            w = app.StatusWriter(os.path.join(d, "x.json"))
            with mock.patch.object(app.json, "dump", side_effect=TypeError("x")):
                w.finish("finished")                 # must not raise
            self.assertFalse([n for n in os.listdir(d) if n.endswith(".tmp")])

    def test_failed_replace_leaves_old_file_and_no_tmp(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.json")
            w = app.StatusWriter(p)
            with mock.patch.object(app.os, "replace", side_effect=PermissionError("busy")):
                w.finish("finished")
            self.assertEqual(app.read_status(p)["state"], "running")
            self.assertFalse([n for n in os.listdir(d) if n.endswith(".tmp")])

    def test_finish_retries_until_the_replace_works(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.json")
            w = app.StatusWriter(p)
            real, calls = os.replace, []

            def flaky(a, b):
                calls.append(1)
                if len(calls) <= 3:
                    raise PermissionError("reader has it open")
                real(a, b)
            with mock.patch.object(app.StatusWriter, "RETRY_DELAY", 0), \
                    mock.patch.object(app.os, "replace", side_effect=flaky):
                self.assertTrue(w.finish("finished"))
            self.assertEqual(len(calls), 4)
            self.assertEqual(app.read_status(p)["state"], "finished")

    def test_finish_gives_up_quietly_and_says_so(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.json")
            w = app.StatusWriter(p)
            with mock.patch.object(app.StatusWriter, "RETRY_DELAY", 0), \
                    mock.patch.object(app.os, "replace",
                                      side_effect=PermissionError("busy")) as rp:
                self.assertFalse(w.finish("failed", "x"))
            self.assertEqual(rp.call_count, app.StatusWriter.FINISH_TRIES)
            self.assertFalse([n for n in os.listdir(d) if n.endswith(".tmp")])

    def test_scan_result_unchanged_when_final_write_never_works(self):
        with tempfile.TemporaryDirectory() as d:
            make_tree(os.path.join(d, "s"), {"a/f.txt": OLD})
            with mock.patch.object(app.StatusWriter, "RETRY_DELAY", 0), \
                    mock.patch.object(app.StatusWriter, "_write_file", return_value=False):
                rc = app.main([os.path.join(d, "s"), "--format", "summary", "-q",
                               "--status-file", os.path.join(d, "x.json")])
            self.assertEqual(rc, 0)

    def test_temp_file_name_is_per_process(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.json")
            seen = []
            real = os.replace

            def spy(a, b):
                seen.append(a)
                real(a, b)
            with mock.patch.object(app.os, "replace", side_effect=spy):
                app.StatusWriter(p).finish("finished")
            self.assertTrue(seen)
            self.assertTrue(all(str(os.getpid()) in os.path.basename(a) for a in seen), seen)

    def test_report_path_is_stored_absolute(self):
        with tempfile.TemporaryDirectory() as d:
            make_tree(os.path.join(d, "s"), {"a/f.txt": OLD})
            st = os.path.join(d, "x.json")
            old = os.getcwd()
            os.chdir(d)
            try:
                rc = app.main([os.path.join(d, "s"), "--format", "summary", "-q",
                               "--report", "r.html", "--status-file", st])
            finally:
                os.chdir(old)
            self.assertEqual(rc, 0)
            rep = app.read_status(st)["report"]
            self.assertTrue(os.path.isabs(rep))
            self.assertTrue(os.path.exists(rep))

    def test_no_report_claimed_when_none_was_written(self):
        with tempfile.TemporaryDirectory() as d:
            make_tree(os.path.join(d, "s"), {"a/f.txt": OLD})
            st, rep = os.path.join(d, "x.json"), os.path.join(d, "r.html")
            with mock.patch.object(app, "scan_tree", return_value=({}, False)):
                rc = app.main([os.path.join(d, "s"), "--format", "summary", "-q",
                               "--report", rep, "--status-file", st])
            self.assertEqual(rc, 0)
            self.assertFalse(os.path.exists(rep))
            self.assertIsNone(app.read_status(st)["report"])

    def test_failed_runs_never_claim_a_report(self):
        P = {"phase": "scan", "fraction": 0.5, "exact": False, "folders": 1, "files": 2,
             "bytes": 3}
        with tempfile.TemporaryDirectory() as d:
            make_tree(os.path.join(d, "s"), {"a/f.txt": OLD})
            src, st, rep = os.path.join(d, "s"), os.path.join(d, "x.json"), os.path.join(d, "r.html")
            args = [src, "--format", "summary", "-q", "--report", rep, "--status-file", st]
            cases = [
                ("ReportError", mock.patch.object(app, "write_report",
                                                  side_effect=app.ReportError("nope")), None),
                ("OSError", mock.patch.object(app, "write_report",
                                              side_effect=OSError("disk")), None),
                ("exception", mock.patch.object(app, "scan_tree",
                                                side_effect=RuntimeError("boom")),
                 RuntimeError),
                ("interrupt", mock.patch.object(app, "scan_tree",
                                                side_effect=KeyboardInterrupt), KeyboardInterrupt),
            ]
            for name, patch, exc in cases:
                with self.subTest(name), patch:
                    if exc:
                        with self.assertRaises(exc):
                            app.run_cli(app.build_parser().parse_args(args), src)
                    else:
                        self.assertEqual(app.main(args), 2)
                s = app.read_status(st)
                self.assertEqual(s["state"], "failed")
                self.assertIsNone(s["report"])
            self.assertFalse(os.path.exists(rep))
            bad = os.path.join(d, "missing")
            self.assertEqual(app.main([bad, "-q", "--report", rep, "--status-file", st]), 2)
            self.assertIsNone(app.read_status(st)["report"])

    def test_finished_keeps_the_report_and_failed_drops_it(self):
        with tempfile.TemporaryDirectory() as d:
            w = app.StatusWriter(os.path.join(d, "x.json"), "/r.html")
            self.assertEqual(app.read_status(w.path)["report"], "/r.html")
            w.finish("failed", "x")
            self.assertIsNone(app.read_status(w.path)["report"])

    def test_nothing_changes_after_finish(self):
        P = {"phase": "scan", "fraction": 0.5, "exact": False, "folders": 1, "files": 2,
             "bytes": 3}
        with tempfile.TemporaryDirectory() as d:
            w = app.StatusWriter(os.path.join(d, "x.json"), "/r.html")
            self.assertTrue(w.finish("finished"))
            before = app.read_status(w.path)
            w.update(P)
            self.assertFalse(w._write("running", wait=0))
            self.assertEqual(w.finish("failed", "late"), True)
            self.assertEqual(app.read_status(w.path), before)

    def test_updates_are_throttled(self):
        with tempfile.TemporaryDirectory() as d:
            w = app.StatusWriter(os.path.join(d, "x.json"))
            p = {"phase": "scan", "fraction": 0.5, "exact": False, "folders": 1, "files": 2,
                 "bytes": 3}
            with mock.patch.object(w, "_write") as wr:
                for _ in range(5):
                    w.update(p)
            self.assertEqual(wr.call_count, 1)

    def test_missing_or_corrupt_file_reads_none(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.json")
            self.assertIsNone(app.read_status(p))
            with open(p, "w") as f:
                f.write("{")
            self.assertIsNone(app.read_status(p))
            for text in ("[]", "3", "null", '"s"'):
                with open(p, "w") as f:
                    f.write(text)
                self.assertIsNone(app.read_status(p), text)
            for text in ("{}", '{"state": "weird"}', '{"state": 3}'):
                with open(p, "w") as f:
                    f.write(text)
                self.assertIsNone(app.read_status(p), text)
            for st in ("running", "finished", "failed"):
                with open(p, "w") as f:
                    f.write('{"state": "%s"}' % st)
                self.assertEqual(app.read_status(p)["state"], st)
            with open(p, "wb") as f:
                f.write(b"\xff\xfe\x00")
            self.assertIsNone(app.read_status(p))


class Heartbeat(unittest.TestCase):
    def _writer(self, d, beat=0.05):
        patches = [mock.patch.object(app.StatusWriter, "RETRY_DELAY", 0),
                   mock.patch.object(app.StatusWriter, "HEARTBEAT", beat)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        path = os.path.join(d, "x.json")
        w = app.StatusWriter(path)
        self.addCleanup(w.finish, "failed")
        return w, path

    def wait_for(self, cond, secs=5):
        end = time.monotonic() + secs
        while time.monotonic() < end:
            if cond():
                return True
            time.sleep(0.01)
        return False

    def test_heartbeat_keeps_updated_fresh_and_state_running(self):
        with tempfile.TemporaryDirectory() as d:
            w, path = self._writer(d)
            first = app.read_status(path)["updated"]
            self.assertTrue(self.wait_for(lambda: app.read_status(path)["updated"] > first))
            self.assertEqual(app.read_status(path)["state"], "running")

    def test_heartbeat_repeats_the_latest_progress(self):
        with tempfile.TemporaryDirectory() as d:
            w, path = self._writer(d, beat=0.05)
            w._write("running", "42%", "c", "t")
            u = app.read_status(path)["updated"]
            self.assertTrue(self.wait_for(lambda: app.read_status(path)["updated"] > u))
            self.assertEqual(app.read_status(path)["percent"], "42%")

    def test_finish_stops_heartbeat_and_state_sticks(self):
        with tempfile.TemporaryDirectory() as d:
            w, path = self._writer(d)
            self.assertTrue(w.finish("finished"))
            u = app.read_status(path)["updated"]
            time.sleep(0.3)
            s = app.read_status(path)
            self.assertEqual((s["state"], s["updated"]), ("finished", u))
            self.assertFalse(w._thread.is_alive())

    def test_beat_after_finish_writes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            w, path = self._writer(d, beat=60)
            w.finish("finished")
            with mock.patch.object(w, "_write_file") as wf:
                w._beat()
            wf.assert_not_called()

    def test_update_skips_instead_of_waiting_for_a_blocked_write(self):
        with tempfile.TemporaryDirectory() as d:
            w, path = self._writer(d, beat=60)
            gate, entered = threading.Event(), threading.Event()

            def stuck(data):
                entered.set()
                gate.wait(10)
                return True
            p = {"phase": "scan", "fraction": 0.5, "exact": False, "folders": 1, "files": 2,
                 "bytes": 3}
            with mock.patch.object(w, "_write_file", side_effect=stuck):
                t = threading.Thread(target=w._beat)
                t.start()
                self.assertTrue(entered.wait(5))
                t0 = time.monotonic()
                w.update(p)
                self.assertLess(time.monotonic() - t0, 1)
                gate.set()
                t.join(5)

    def test_finish_waits_only_a_bounded_time(self):
        with tempfile.TemporaryDirectory() as d:
            w, path = self._writer(d, beat=60)
            with mock.patch.object(app.StatusWriter, "LOCK_WAIT", 0.1):
                w._lock.acquire()
                try:
                    t0 = time.monotonic()
                    self.assertFalse(w.finish("finished"))
                    self.assertLess(time.monotonic() - t0, 2)
                finally:
                    w._lock.release()

    def test_finish_cannot_hang_on_a_stalled_write(self):
        with tempfile.TemporaryDirectory() as d:
            w, path = self._writer(d, beat=60)
            gate = threading.Event()
            with mock.patch.object(app.StatusWriter, "FINISH_TIMEOUT", 0.3), \
                    mock.patch.object(w, "_write_file",
                                      side_effect=lambda data: gate.wait(10) and False):
                t0 = time.monotonic()
                try:
                    self.assertFalse(w.finish("finished"))
                    self.assertLess(time.monotonic() - t0, 3)
                    self.assertTrue(w._final_thread.is_alive())
                    self.assertTrue(w._final_thread.daemon)
                finally:
                    gate.set()
                    w._final_thread.join(5)
            self.assertFalse(w._final_thread.is_alive())

    def test_concurrent_finishes_write_once(self):
        with tempfile.TemporaryDirectory() as d:
            w, path = self._writer(d, beat=60)
            calls = []

            def slow(data):
                calls.append(data["state"])
                time.sleep(0.2)
                return True
            with mock.patch.object(w, "_write_file", side_effect=slow):
                ts = [threading.Thread(target=w.finish, args=("finished",)) for _ in range(4)]
                for t in ts:
                    t.start()
                for t in ts:
                    t.join(5)
            self.assertEqual(calls, ["finished"])

    def test_status_is_stale(self):
        now = 1000.0
        stale = app.STATUS_STALE_SECONDS
        self.assertEqual(stale, 120)
        run = {"state": "running", "updated": now - stale - 1}
        self.assertTrue(app.status_is_stale(run, now))
        self.assertFalse(app.status_is_stale({"state": "running", "updated": now - 5}, now))
        self.assertFalse(app.status_is_stale({"state": "finished", "updated": 0}, now))
        self.assertFalse(app.status_is_stale({"state": "failed", "updated": 0}, now))
        self.assertTrue(app.status_is_stale({"state": "running", "updated": "x"}, now))
        self.assertTrue(app.status_is_stale({"state": "running"}, now))
        self.assertFalse(app.status_is_stale(None, now))
        self.assertTrue(app.status_is_stale({"state": "running", "updated": time.time() - 999}))


if __name__ == "__main__":
    unittest.main()
