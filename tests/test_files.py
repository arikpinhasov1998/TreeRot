import os
import tempfile
import unittest
from datetime import datetime
from unittest import mock

from tests.helpers import NEW, OLD, app, make_tree

LO = datetime(2024, 11, 4).timestamp()


def listing(d, **kw):
    args = dict(lo=LO, hi=None, created="off", activity="modified", period="since 2024-11-04")
    args.update(kw)
    return app.list_folder_files(d, **args)


class Files(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.d = d.name
        make_tree(self.d, {"new.txt": NEW, "old.txt": OLD, "sub/inner.txt": NEW})

    def test_colors_and_reasons(self):
        rows, err = listing(self.d)
        self.assertEqual(err, "")
        by = {r["name"]: r for r in rows}
        self.assertEqual(by["new.txt"]["color"], app.GREEN)
        self.assertEqual(by["old.txt"]["color"], app.RED)
        self.assertIn("within the period", by["new.txt"]["reason"])
        self.assertIn("outside the period", by["old.txt"]["reason"])

    def test_only_direct_files_are_listed(self):
        rows, _ = listing(self.d)
        self.assertNotIn("inner.txt", {r["name"] for r in rows})

    def test_to_date_is_respected(self):
        rows, _ = listing(self.d, hi=datetime(2025, 1, 1).timestamp())
        self.assertEqual({r["name"]: r["color"] for r in rows}["new.txt"], app.RED)

    def test_missing_folder_returns_error_text(self):
        rows, err = listing(os.path.join(self.d, "gone"))
        self.assertEqual(rows, [])
        self.assertIn("could not be listed", err)

    def test_unreadable_file_is_gray(self):
        class Bad:
            name = "bad.txt"
            path = os.path.join(self.d, "bad.txt")
            def is_symlink(self): return False
            def is_file(self, follow_symlinks=True): return True
            def stat(self, follow_symlinks=True):
                raise PermissionError(13, "Permission denied")
        class It:
            def __enter__(self): return iter([Bad()])
            def __exit__(self, *a): return False
        with mock.patch.object(app.os, "scandir", return_value=It()):
            rows, _ = listing(self.d)
        self.assertEqual(rows[0]["color"], app.GRAY)
        self.assertIn("Access denied", rows[0]["reason"])

    def test_sort_and_filter(self):
        rows, _ = listing(self.d)
        names = [r["name"] for r in app.sort_file_rows(rows, "Name (A-Z)")]
        self.assertEqual(names, ["new.txt", "old.txt"])
        self.assertEqual([r["name"] for r in app.filter_file_rows(rows, "Red only (not used)")],
                         ["old.txt"])
        self.assertEqual(len(app.filter_file_rows(rows, "All")), 2)
