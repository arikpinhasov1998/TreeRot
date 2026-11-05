import json
import os
import tempfile
import unittest
from unittest import mock

from tests.helpers import OLD, app, make_tree


class SavedDuringAScan(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.d = d.name
        self.settings = os.path.join(d.name, ".treerot.json")
        p = mock.patch.object(app, "SETTINGS_FILE", self.settings)
        p.start()
        self.addCleanup(p.stop)

    def test_what_the_window_saved_during_a_scan_survives_it(self):
        make_tree(self.d, {"s/f.txt": OLD})
        app.save_settings({"excludes": ["before"]})
        real = app.scan_tree

        def scan(*a, **kw):
            app.save_settings({"excludes": ["saved in the window"]})
            return real(*a, **kw)
        with mock.patch.object(app, "scan_tree", scan):
            rc = app.main([os.path.join(self.d, "s"), "--format", "summary", "-q",
                           "--progress", "none"])
        self.assertEqual(rc, 0)
        saved = app.load_settings()
        self.assertEqual(saved["excludes"], ["saved in the window"])
        self.assertEqual(len(saved["last_totals"]), 1)

    def test_a_failed_save_keeps_the_old_file_whole_and_leaves_nothing_behind(self):
        app.save_settings({"path": "/kept"})

        def broken(data, f, **kw):
            f.write('{"path": "/half')
            raise OSError(28, "No space left on device")
        with mock.patch.object(app.json, "dump", broken):
            app.save_settings({"path": "/new"})
        self.assertEqual(app.load_settings(), {"path": "/kept"})
        self.assertEqual(os.listdir(self.d), [".treerot.json"])

    def test_the_settings_file_is_replaced_whole(self):
        real, seen = os.replace, []

        def replace(src, dst):
            with open(src, encoding="utf-8") as f:
                seen.append((json.load(f), dst))
            real(src, dst)
        with mock.patch.object(app.os, "replace", replace):
            app.save_settings({"path": "/new"})
        self.assertEqual(seen, [({"path": "/new"}, self.settings)])
        self.assertEqual(app.load_settings(), {"path": "/new"})
