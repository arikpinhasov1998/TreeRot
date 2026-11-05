import csv
import json
import os
import re
import tempfile
import unittest
from datetime import datetime
from unittest import mock

from tests.helpers import OLD, app, make_tree, scan_rows

PRE_1970 = -86400 * 400


class WindowsDatetime(datetime):
    """What Windows does: fromtimestamp refuses any time before 1970."""
    @classmethod
    def fromtimestamp(cls, ts, tz=None):
        if ts < 0:
            raise OSError(22, "Invalid argument")
        return datetime.fromtimestamp(ts, tz)


def meta_for(root="x"):
    return {"root": root, "excludes": [], "excluded_count": 0, "scanned_at": "now", "elapsed": 1,
            "canceled": False, "activity": "modified", "computer": "c", "basis_note": ""}


class Pre1970(unittest.TestCase):
    def test_a_time_windows_refuses_still_formats(self):
        with mock.patch.object(app, "datetime", WindowsDatetime):
            self.assertEqual(app.fmt_ts(-86400), "1969-12-31 00:00")

    def test_every_error_fromtimestamp_can_raise_is_handled(self):
        for exc in (OSError(22, "x"), OverflowError("x"), ValueError("x")):
            class Refuses(datetime):
                @classmethod
                def fromtimestamp(cls, ts, tz=None):
                    raise exc
            with mock.patch.object(app, "datetime", Refuses):
                self.assertEqual(app.fmt_ts(-86400), "1969-12-31 00:00")

    def test_a_time_no_date_can_hold_gives_blank(self):
        self.assertEqual(app.fmt_ts(1e300), "")

    def test_a_pre_1970_folder_does_not_lose_the_report_or_the_listing(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(app, "datetime", WindowsDatetime):
            make_tree(d, {"ancient/f.txt": PRE_1970})
            rows = list(scan_rows(d, datetime(2024, 1, 1)).values())
            data = app.report_data(rows, meta_for(d))
            self.assertEqual(len(data["rows"]), 2)
            listed, err = app.list_folder_files(os.path.join(d, "ancient"), lo=0, hi=None,
                                                created="off", activity="modified", period="p")
            self.assertEqual(err, "")
            self.assertEqual([r["name"] for r in listed], ["f.txt"])


class EmbeddedData(unittest.TestCase):
    def _embedded(self, html):
        m = re.search(r'id="report-data"[^>]*>(.*?)</script>', html, re.S)
        return m.group(1)

    def test_names_that_could_break_the_script_stay_valid_json(self):
        for name in ("a<!--b", "a</script>b", "a<b"):
            with tempfile.TemporaryDirectory() as d:
                folder = os.path.join(d, "s")
                make_tree(folder, {"x/f.txt": OLD})
                rows = list(scan_rows(folder, datetime(2024, 1, 1)).values())
                meta = dict(meta_for(folder), excludes=[name], root=name)
                out = os.path.join(d, "r.html")
                app.write_html_report(out, rows, meta)
                with open(out, encoding="utf-8") as f:
                    html = f.read()
            raw = self._embedded(html)
            self.assertNotIn("<", raw)
            data = json.loads(raw)
            self.assertEqual(data["meta"]["excludes"], [name])
            self.assertEqual(data["meta"]["root"], name)


class SurrogateNames(unittest.TestCase):
    """Linux can hand back file names that are not UTF-8, as lone surrogates."""
    BAD = "caf\udce9"

    def _rows(self, d):
        make_tree(d, {"x/f.txt": OLD})
        rows = list(scan_rows(d, datetime(2024, 1, 1)).values())
        for r in rows:
            if r["info"].parent is not None:
                r["info"].path = os.path.join(d, self.BAD)
        return rows

    def test_html_report_is_written(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "r.html")
            app.write_html_report(out, self._rows(d), meta_for(d))
            with open(out, encoding="utf-8") as f:
                self.assertIn("caf", f.read())
            self.assertEqual(os.path.exists(out + ".part"), False)

    def test_csv_is_written(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "r.csv")
            app.write_csv(out, self._rows(d))
            with open(out, encoding="utf-8-sig", newline="") as f:
                self.assertEqual(len(list(csv.reader(f))), 3)


class FindingAndName(unittest.TestCase):
    def _page(self, d, spec):
        make_tree(d, spec)
        rows = list(scan_rows(d, datetime(2024, 1, 1)).values())
        out = os.path.join(d, "r.html")
        app.write_html_report(out, rows, meta_for("<x>"))
        with open(out, encoding="utf-8") as f:
            return f.read(), rows

    def test_the_report_carries_treerots_name(self):
        with tempfile.TemporaryDirectory() as d:
            html, _ = self._page(d, {"a/f.txt": OLD})
        self.assertIn("<title>TreeRot report - &lt;x&gt;</title>", html)
        self.assertIn("<span>TreeRot report</span>", html)
        self.assertNotIn("Folder activity report", html)

    def test_the_finding_counts_files_and_folders_not_bytes(self):
        # no JavaScript engine in the tests: the data is real, the condition is read from the page
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "a", "empty.txt")
            os.makedirs(os.path.dirname(path))
            open(path, "wb").close()
            os.utime(path, (OLD, OLD))
            html, rows = self._page(d, {})
            sm = app.report_data(rows, meta_for(d))["summary"]
        self.assertEqual(sm["total"], 0)
        self.assertGreater(sm["files"], 0)
        self.assertGreater(sm["colors"]["red"]["folders"], 0)
        self.assertIn("textContent = S.files === 0\n", html)
        self.assertIn(": (C.red.folders === 0\n", html)
        self.assertNotIn("C.red.bytes === 0", html)


class SurrogateTextOutput(unittest.TestCase):
    def test_o_file_tree_output_survives_a_name_that_is_not_utf8(self):
        real = app.build_rows

        def renamed(*a, **kw):
            rows = real(*a, **kw)
            for r in rows:
                if r["info"].parent is not None:
                    r["info"].path = os.path.join(r["info"].parent, "caf\udce9")
            return rows
        with tempfile.TemporaryDirectory() as d:
            make_tree(os.path.join(d, "s"), {"x/f.txt": OLD})
            out = os.path.join(d, "out.txt")
            with mock.patch.object(app, "build_rows", renamed):
                rc = app.main([os.path.join(d, "s"), "--from", "2024-01-01", "--format", "tree",
                               "-q", "--progress", "none", "-o", out])
            self.assertEqual(rc, 0)
            with open(out, encoding="utf-8") as f:
                self.assertIn("caf", f.read())
