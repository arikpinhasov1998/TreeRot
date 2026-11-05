import json
import os
import tempfile
import unittest
from unittest import mock

from tests.helpers import OLD, app, make_tree


class Status(unittest.TestCase):
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
            self.assertFalse(os.path.exists(st + ".tmp"))

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
            self.assertFalse(os.path.exists(os.path.join(d, "x.json.tmp")))

    def test_failed_replace_leaves_old_file_and_no_tmp(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.json")
            w = app.StatusWriter(p)
            with mock.patch.object(app.os, "replace", side_effect=PermissionError("busy")):
                w.finish("finished")
            self.assertEqual(app.read_status(p)["state"], "running")
            self.assertFalse(os.path.exists(p + ".tmp"))

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
            with open(p, "wb") as f:
                f.write(b"\xff\xfe\x00")
            self.assertIsNone(app.read_status(p))


if __name__ == "__main__":
    unittest.main()
