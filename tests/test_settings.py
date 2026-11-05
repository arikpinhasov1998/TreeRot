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


class UnreadableSettings(unittest.TestCase):
    """A read that fails is not an empty file: saving over it would wipe the user's exclusions."""
    KEPT = '{"excludes": ["keep me"]}'

    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.d = d.name
        self.settings = os.path.join(d.name, ".treerot.json")
        self.old = os.path.join(d.name, ".old.json")
        for name, path in (("SETTINGS_FILE", self.settings), ("OLD_SETTINGS_FILE", self.old)):
            p = mock.patch.object(app, name, path)
            p.start()
            self.addCleanup(p.stop)
        with open(self.settings, "w", encoding="utf-8") as f:
            f.write(self.KEPT)

    def on_disk(self):
        with open(self.settings, encoding="utf-8") as f:
            return f.read()

    def refusing_reads(self):
        real, path = open, self.settings

        def fake(file, mode="r", *a, **kw):
            if file == path and "r" in mode:
                raise PermissionError(13, "Sharing violation", file)
            return real(file, mode, *a, **kw)
        return mock.patch("builtins.open", fake)

    def test_read_settings_tells_a_failure_from_a_missing_file(self):
        self.assertEqual(app.read_settings(), {"excludes": ["keep me"]})
        with self.refusing_reads():
            self.assertIsNone(app.read_settings())
        for bad in ('{"excludes": [', "[1, 2]"):
            with open(self.settings, "w", encoding="utf-8") as f:
                f.write(bad)
            self.assertIsNone(app.read_settings())
        os.remove(self.settings)
        self.assertEqual(app.read_settings(), {})

    def test_a_folder_that_cannot_be_reached_is_not_a_missing_file(self):
        with mock.patch.object(app, "SETTINGS_FILE", os.path.join(self.d, "gone", "s.json")):
            self.assertIsNone(app.read_settings())

    def test_a_failed_read_does_not_bring_back_the_old_files_settings(self):
        with open(self.old, "w", encoding="utf-8") as f:
            f.write('{"excludes": ["older"]}')
        with self.refusing_reads():
            self.assertIsNone(app.read_settings())
            self.assertEqual(app.load_settings(), {})
        self.assertEqual(self.on_disk(), self.KEPT)

    def test_a_broken_old_file_does_not_block_a_first_save(self):
        os.remove(self.settings)
        with open(self.old, "w", encoding="utf-8") as f:
            f.write("{broken")
        self.assertEqual(app.read_settings(), {})

    def _scan(self):
        make_tree(self.d, {"s/f.txt": OLD})
        rc = app.main([os.path.join(self.d, "s"), "--from", "2024-01-01", "--format", "summary",
                       "-q", "--progress", "none"])
        self.assertEqual(rc, 0)

    def test_the_scan_skips_its_save_when_the_read_fails(self):
        with self.refusing_reads():
            self._scan()
        self.assertEqual(self.on_disk(), self.KEPT)

    def test_the_scan_saves_its_totals_when_the_file_is_truly_missing(self):
        os.remove(self.settings)
        self._scan()
        self.assertEqual(len(app.load_settings()["last_totals"]), 1)
