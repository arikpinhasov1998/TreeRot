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
