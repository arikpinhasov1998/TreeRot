import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from tests.helpers import OLD, app, make_tree


def tk_ok():
    """Probes in a child process: on Tk 9 / macOS, creating and destroying a Tk root in this
    process and then opening the real window aborts the interpreter."""
    try:
        r = subprocess.run([sys.executable, "-c", "import tkinter; tkinter.Tk().destroy()"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
        return r.returncode == 0
    except Exception:
        return False


@unittest.skipUnless(tk_ok(), "no display or tkinter")
class GuiCase(unittest.TestCase):
    def drive(self, root, check):
        """Opens the window, scans root, runs check(window) after the scan, then closes."""
        errors = []

        def ready(w):
            w.path_var.set(root)
            w.from_var.set("2024-11-04")
            w.created_var.set(False)
            w._start()

            def wait():
                if str(w.scan_btn.cget("state")) != "normal":
                    w.after(100, wait)
                    return
                try:
                    check(w)
                except Exception as e:
                    errors.append(e)
                w.after(1500, w.destroy)
            w.after(200, wait)
        app.run_gui(on_ready=ready)
        if errors:
            raise errors[0]


class ShowLevels(GuiCase):
    def test_levels_open_exactly_that_deep(self):
        with tempfile.TemporaryDirectory() as d:
            make_tree(d, {"a/b/c/f.txt": OLD})

            def check(w):
                w._show_levels("2")
                self.assertTrue(w.tree.exists(os.path.join(d, "a", "b")))
                self.assertFalse(w.tree.exists(os.path.join(d, "a", "b", "c")))
                w._show_levels("Unlimited")
                self.assertTrue(w.tree.exists(os.path.join(d, "a", "b", "c")))
            self.drive(d, check)

    def test_unlimited_then_one_closes_deeper_rows(self):
        with tempfile.TemporaryDirectory() as d:
            make_tree(d, {"a/b/c/f.txt": OLD})

            def check(w):
                w._show_levels("Unlimited")
                self.assertTrue(w.tree.item(os.path.join(d, "a", "b"), "open"))
                w._show_levels("1")
                self.assertTrue(w.tree.item(d, "open"))
                self.assertFalse(w.tree.item(os.path.join(d, "a"), "open"))
                self.assertFalse(w.tree.item(os.path.join(d, "a", "b"), "open"))
                self.assertEqual(w.levels_var.get(), "1")
            self.drive(d, check)

    def test_stale_level_is_blanked(self):
        with tempfile.TemporaryDirectory() as d:
            make_tree(d, {"a/b/c/f.txt": OLD})

            def check(w):
                self.assertEqual(w.levels_var.get(), "")
                for action in (w._refresh_tree, w._expand_to_red, w._expand_all, w._collapse_all):
                    w._show_levels("2")
                    self.assertEqual(w.levels_var.get(), "2")
                    action()
                    self.assertEqual(w.levels_var.get(), "")
            self.drive(d, check)

    def test_large_tree_guard(self):
        with tempfile.TemporaryDirectory() as d:
            make_tree(d, {"a/b/c/f.txt": OLD})

            def check(w):
                self.assertEqual(w._count_to_level(1), 2)
                self.assertEqual(w._count_to_level(3), 4)
                w._show_levels("1")
                self.assertFalse(w.tree.item(os.path.join(d, "a"), "open"))
                w._count_to_level = lambda limit: 20001
                with mock.patch.object(app_messagebox(), "askyesno", return_value=False) as m:
                    w._show_levels("3")
                self.assertTrue(m.called)
                self.assertEqual(w.levels_var.get(), "")
                self.assertFalse(w.tree.item(os.path.join(d, "a"), "open"))
            self.drive(d, check)


def app_messagebox():
    from tkinter import messagebox
    return messagebox
