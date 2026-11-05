"""The date range decides what is called unused, so its edges are tested exactly."""
import io
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest import mock

from tests.helpers import OLD, app, make_tree


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


FROM = datetime(2025, 1, 1)
TO = datetime(2025, 6, 30, 12, 0, 0)    # whole seconds survive the trip through a file's time
LO, HI = FROM.timestamp(), TO.timestamp()


def scanned_in_range(mtime, lo=LO, hi=HI, created="off"):
    with tempfile.TemporaryDirectory() as d:
        make_tree(d, {"s/f.txt": mtime})
        folders, _ = app.scan_tree(d, excludes=None, stats={}, date_from_ts=lo, date_to_ts=hi,
                                   created=created)
    return next(f for p, f in folders.items() if os.path.basename(p) == "s").range_files == 1


def listed_color(mtime, lo=LO, hi=HI, created="off"):
    with tempfile.TemporaryDirectory() as d:
        make_tree(d, {"f.txt": mtime})
        rows, _ = app.list_folder_files(d, lo=lo, hi=hi, created=created, activity="modified",
                                        period="p")
    return rows[0]["color"]


class Boundaries(unittest.TestCase):
    CASES = [("a second before From", LO - 1, False), ("exactly From", LO, True),
             ("a second after From", LO + 1, True), ("a second before To", HI - 1, True),
             ("exactly To", HI, True), ("a second after To", HI + 1, False)]

    def test_the_scan_at_each_edge(self):
        for name, when, inside in self.CASES:
            with self.subTest(name):
                self.assertEqual(scanned_in_range(when), inside)

    def test_the_file_list_agrees_with_the_scan(self):
        for name, when, inside in self.CASES:
            with self.subTest(name):
                self.assertEqual(listed_color(when), app.GREEN if inside else app.RED)

    def test_only_a_from_date_has_no_upper_edge(self):
        self.assertTrue(scanned_in_range(HI + 86400, hi=None))
        self.assertFalse(scanned_in_range(LO - 1, hi=None))

    def test_only_a_to_date_has_no_lower_edge(self):
        self.assertTrue(scanned_in_range(LO - 86400, lo=None))
        self.assertFalse(scanned_in_range(HI + 1, lo=None))

    def test_typed_dates_cover_the_whole_of_the_to_day_and_no_more(self):
        lo = app.parse_date("2025-01-01").timestamp()
        hi = app.parse_date("2025-06-30", end_of_day=True).timestamp()
        day = datetime(2025, 6, 30)
        for when, inside in ((day, True), (day + timedelta(hours=23, minutes=59, seconds=59), True),
                             (day + timedelta(hours=23, minutes=59, seconds=59, milliseconds=500), True),
                             (day + timedelta(days=1), False), (datetime(2025, 1, 1), True),
                             (datetime(2025, 1, 1) - timedelta(seconds=1), False)):
            with self.subTest(when=when):
                self.assertEqual(scanned_in_range(when.timestamp(), lo, hi), inside)


class CreatedBoundaries(unittest.TestCase):
    """An old modified date, with the creation date on each side of the edges."""
    OUTSIDE = LO - 86400 * 400

    def test_the_created_date_has_the_same_edges(self):
        for name, created_at, inside in Boundaries.CASES:
            with self.subTest(name), mock.patch.object(app, "file_created",
                                                       return_value=created_at):
                self.assertEqual(scanned_in_range(self.OUTSIDE, created="auto"), inside)
                self.assertEqual(listed_color(self.OUTSIDE, created="auto"),
                                 app.GREEN if inside else app.RED)

    def test_off_ignores_the_created_date(self):
        now = datetime.now().timestamp()
        self.assertFalse(scanned_in_range(self.OUTSIDE, lo=now - 3600, hi=None, created="off"))

    def test_a_real_file_just_created_counts_where_the_system_keeps_it_apart(self):
        # macOS moves the birth time back along with an older modified time, so only ctime on a
        # system without a birth time can show this with a real file.
        if hasattr(os.stat_result, "st_birthtime"):
            self.skipTest("the birth time follows an older modified time here")
        now = datetime.now().timestamp()
        self.assertTrue(scanned_in_range(self.OUTSIDE, lo=now - 3600, hi=None, created="ctime"))


class PeriodBounds(unittest.TestCase):
    def test_every_refusal_reads_as_a_bad_date(self):
        for exc in (ValueError("x"), OSError(22, "x"), OverflowError("x")):
            class Refuses(datetime):
                def timestamp(self):
                    raise exc
            with self.subTest(type(exc).__name__):
                with self.assertRaises(ValueError):
                    app.period_bounds(Refuses(1900, 1, 1), None)
                with self.assertRaises(ValueError):
                    app.period_bounds(None, Refuses(1900, 1, 1))

    def test_usable_dates_and_blanks(self):
        self.assertEqual(app.period_bounds(FROM, TO), (LO, HI))
        self.assertEqual(app.period_bounds(None, None), (None, None))


class ShellDates(unittest.TestCase):
    def _run(self, *extra):
        err = io.StringIO()
        with tempfile.TemporaryDirectory() as d:
            make_tree(d, {"s/f.txt": OLD})
            st = os.path.join(d, "x.json")
            with mock.patch.object(sys, "stderr", err):
                rc = app.main([os.path.join(d, "s"), "--format", "summary", "-q", "--progress", "none",
                               "--status-file", st] + list(extra))
            status = app.read_status(st)
        return rc, err.getvalue(), status

    def test_a_from_date_before_any_time_is_a_clear_error(self):
        rc, err, status = self._run("--from", "0001-01-01")
        self.assertEqual(rc, 2)
        self.assertIn(app.DATE_RANGE_MSG, err)
        self.assertNotIn("Traceback", err)
        self.assertEqual(status["state"], "failed")
        self.assertIn(app.DATE_RANGE_MSG, status["error"])

    def test_a_date_windows_refuses_is_a_clear_error(self):
        with mock.patch.object(app, "period_bounds", side_effect=ValueError("x")):
            rc, err, _ = self._run("--from", "1900-01-01")
        self.assertEqual(rc, 2)
        self.assertIn(app.DATE_RANGE_MSG, err)

    def test_years_too_far_back_is_a_clear_error(self):
        rc, err, _ = self._run("--years", "5000")
        self.assertEqual(rc, 2)
        self.assertIn(app.DATE_RANGE_MSG, err)


class Messages(unittest.TestCase):
    def test_a_bad_format_and_a_bad_range_say_different_things(self):
        self.assertIn("YYYY-MM-DD", app.DATE_FORMAT_MSG)
        self.assertNotIn("YYYY-MM-DD", app.DATE_RANGE_MSG)
        self.assertIn("outside the range", app.DATE_RANGE_MSG)

    def test_read_period(self):
        d_from, d_to, lo, hi = app.read_period("2025-01-01", "")
        self.assertEqual((d_from, d_to, lo, hi), (FROM, None, LO, None))
        with self.assertRaises(ValueError) as c:
            app.read_period("nonsense", "")
        self.assertEqual(str(c.exception), app.DATE_FORMAT_MSG)
        with self.assertRaises(ValueError) as c:
            app.read_period("0001-01-01", "")
        self.assertEqual(str(c.exception), app.DATE_RANGE_MSG)
