"""The date range decides what is called unused, so its edges are tested exactly."""
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest import mock

from tests.helpers import app, make_tree


class ToDayEnds(unittest.TestCase):
    def test_the_to_date_includes_the_last_fraction_of_its_day(self):
        d = app.parse_date("2025-06-30", end_of_day=True)
        self.assertEqual(d, datetime(2025, 6, 30, 23, 59, 59, 999999))

    def test_a_file_in_the_last_second_of_the_to_day_is_used(self):
        d_to = app.parse_date("2025-06-30", end_of_day=True)
        with tempfile.TemporaryDirectory() as d:
            when = datetime(2025, 6, 30, 23, 59, 59, 500000).timestamp()
            make_tree(d, {"s/f.txt": when})
            folders, _ = app.scan_tree(d, excludes=None, stats={},
                                       date_from_ts=datetime(2025, 1, 1).timestamp(),
                                       date_to_ts=d_to.timestamp(), created="off")
            rows = app.build_rows(folders, datetime(2025, 1, 1), d_to)
        by = {os.path.basename(r["info"].path): r for r in rows}
        self.assertEqual(by["s"]["info"].range_files, 1)
        self.assertEqual(by["s"]["status"], "Active")
