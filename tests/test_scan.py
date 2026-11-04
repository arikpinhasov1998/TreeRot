import os
import stat
import tempfile
import unittest
from datetime import datetime

from tests.helpers import NEW, OLD, app, make_tree, scan_rows

FROM = datetime(2024, 11, 4)


class ColorRules(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.root = d.name

    def colors(self, **kw):
        return {k: app.color_of(r) for k, r in scan_rows(self.root, FROM, **kw).items()}

    def test_new_file_deep_below_old_folders_turns_all_parents_green(self):
        make_tree(self.root, {"a/b/c/new.txt": NEW})
        for d in ("a/b/c", "a/b", "a"):
            p = os.path.join(self.root, *d.split("/"))
            os.utime(p, (OLD, OLD))
        c = self.colors()
        self.assertEqual({c["a"], c["a/b"], c["a/b/c"]}, {app.GREEN})

    def test_old_files_only_is_red(self):
        make_tree(self.root, {"old/f.txt": OLD})
        self.assertEqual(self.colors()["old"], app.RED)

    def test_empty_folder_is_gray(self):
        make_tree(self.root, {"empty": None})
        self.assertEqual(self.colors()["empty"], app.GRAY)

    def test_every_level_is_scanned(self):
        deep = "/".join(f"d{i}" for i in range(12))
        make_tree(self.root, {deep + "/f.txt": OLD})
        self.assertIn(deep, scan_rows(self.root, FROM))

    def test_exclusion_removes_folder_and_its_size(self):
        make_tree(self.root, {"keep/f.txt": OLD, "skip/f.txt": OLD})
        rows = scan_rows(self.root, FROM, excludes=["skip"])
        self.assertNotIn("skip", rows)
        self.assertEqual(rows["."]["info"].total_size, 100)

    @unittest.skipIf(os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0),
                     "permissions do not block this user")
    def test_unreadable_folder_is_gray_with_reason(self):
        make_tree(self.root, {"locked": None})
        p = os.path.join(self.root, "locked")
        os.chmod(p, 0)
        self.addCleanup(os.chmod, p, stat.S_IRWXU)
        row = scan_rows(self.root, FROM)["locked"]
        self.assertEqual(app.color_of(row), app.GRAY)
        self.assertIn("could not be opened", app.reason_text(row))


if __name__ == "__main__":
    unittest.main()
