import io
import os
import tempfile
import unittest
from datetime import datetime

from tests.helpers import OLD, app, make_tree, scan_rows


class Levels(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        make_tree(d.name, {"a/b/c/d/f.txt": OLD})
        self.rows = list(scan_rows(d.name, datetime(2024, 1, 1)).values())

    def lines(self, depth):
        out = io.StringIO()
        app.print_tree(self.rows, out, depth, "all", "name", False)
        return len(out.getvalue().splitlines())

    def test_shell_depth_limits_view(self):
        self.assertEqual(self.lines(1), 2)
        self.assertEqual(self.lines(2), 3)

    def test_shell_depth_zero_is_unlimited(self):
        self.assertEqual(self.lines(0), 5)

    def test_html_report_has_level_control(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "r.html")
            meta = {"root": "x", "excludes": [], "excluded_count": 0, "scanned_at": "now",
                    "elapsed": 1, "canceled": False, "activity": "modified", "computer": "c",
                    "basis_note": ""}
            app.write_html_report(p, self.rows, meta)
            with open(p, encoding="utf-8") as f:
                html = f.read()
        self.assertIn('id="levels"', html)
        self.assertIn("Unlimited", html)
