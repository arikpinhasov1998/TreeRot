import gc
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from tests.helpers import NEW, OLD, app, make_tree


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
    def drive(self, root, check, finished=None):
        """Opens the window, scans root, runs check(window) after the scan, then closes.
        If check starts async work, finished() says when it is done (waits up to 30 s)."""
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
                left = [300]

                def close():
                    left[0] -= 1
                    if finished is not None and not finished() and left[0] > 0:
                        w.after(100, close)
                    else:
                        w.after(500, w.destroy)
                w.after(1000, close)
            w.after(200, wait)
        app.run_gui(on_ready=ready)
        gc.collect()      # free the closed window's Tk variables on the main thread, not in a worker
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


class FilesInTree(GuiCase):
    def setUp(self):
        self.async_errors = []
        self.done = False

    def wait_files(self, w, folder, then, tries=400, done=True):
        def poll():
            try:
                if folder in w.file_cache:
                    then()
                    if done:
                        self.done = True
                elif tries_left[0] <= 0:
                    raise AssertionError("files were never listed for " + folder)
                else:
                    tries_left[0] -= 1
                    w.after(50, poll)
            except Exception as e:      # surfaces in the test, not only on stderr
                self.async_errors.append(e)
        tries_left = [tries]
        poll()

    def run_case(self, d, check):
        self.drive(d, check, lambda: bool(self.async_errors) or bool(self.done))
        if self.async_errors:
            raise self.async_errors[0]

    def test_opening_a_folder_lists_files_and_pages(self):
        with tempfile.TemporaryDirectory() as d:
            spec = {"big/f%04d.txt" % n: OLD for n in range(app.FILE_PAGE + 5)}
            spec["big/new.txt"] = NEW
            make_tree(d, spec)
            big = os.path.join(d, "big")
            results = {}

            def check(w):
                w._populate(big)
                w._load_files(big)

                def loaded():
                    results["page1"] = sum(k.startswith(app.FILE_IID)
                                           for k in w.tree.get_children(big))
                    results["more"] = w.tree.exists(app.MORE_IID + big)
                    file_iid = app.FILE_IID + os.path.join(big, "new.txt")
                    w.sort_var.set("Name (A-Z)")
                    w._show_file_page(big)
                    results["page2"] = sum(k.startswith(app.FILE_IID)
                                           for k in w.tree.get_children(big))
                    results["reason"] = w._tip_text(file_iid, True)
                    results["path"] = w._path_of(file_iid)
                self.wait_files(w, big, loaded)
            self.run_case(d, check)
            self.assertEqual(results["page1"], app.FILE_PAGE)
            self.assertTrue(results["more"])
            self.assertEqual(results["page2"], app.FILE_PAGE + 6)
            self.assertIn("within the period", results["reason"])
            self.assertEqual(results["path"], os.path.join(big, "new.txt"))

    def test_selecting_the_more_row_loads_the_next_page(self):
        with tempfile.TemporaryDirectory() as d:
            make_tree(d, {"big/f%04d.txt" % n: OLD for n in range(app.FILE_PAGE + 5)})
            big = os.path.join(d, "big")
            results = {}

            def check(w):
                w._populate(big)
                w._load_files(big)

                def loaded():
                    more = app.MORE_IID + big
                    w.tree.selection_set(more)
                    w._on_select(None)
                    results["files"] = sum(k.startswith(app.FILE_IID)
                                           for k in w.tree.get_children(big))
                    results["more_left"] = w.tree.exists(more)
                self.wait_files(w, big, loaded)
            self.run_case(d, check)
            self.assertEqual(results["files"], app.FILE_PAGE + 5)
            self.assertFalse(results["more_left"])

    def test_file_row_maps_to_its_real_path_from_the_menu_handlers(self):
        with tempfile.TemporaryDirectory() as d:
            make_tree(d, {"a/one.txt": OLD, "a/two.txt": NEW})
            a = os.path.join(d, "a")
            results = {}

            def check(w):
                w._populate(a)
                w._load_files(a)

                def loaded():
                    iid = app.FILE_IID + os.path.join(a, "two.txt")
                    w.tree.selection_set(iid)
                    w._copy_path()
                    results["clip"] = w.clipboard_get()
                    results["folder_iid_path"] = w._path_of(a)
                    w._copy_reason(True)
                    results["reason"] = w.clipboard_get()
                    w._on_select(None)
                    results["status"] = w.status_var.get()
                    ev = mock.Mock(y=0, x_root=0, x_Root=0)
                    w.tree.identify_row = lambda y: iid
                    with mock.patch.object(w.menu, "tk_popup"):
                        w._context_menu(ev)
                    results["exclude_state"] = str(w.menu.entrycget(
                        "Exclude this folder (applies on next scan)", "state"))
                self.wait_files(w, a, loaded)
            self.run_case(d, check)
            self.assertEqual(results["clip"], os.path.join(a, "two.txt"))
            self.assertEqual(results["folder_iid_path"], a)
            self.assertIn(os.path.join(a, "two.txt"), results["reason"])
            self.assertEqual(results["status"], os.path.join(a, "two.txt"))
            self.assertEqual(results["exclude_state"], "disabled")

    def test_listing_failure_shows_a_gray_row_with_the_reason(self):
        import shutil
        with tempfile.TemporaryDirectory() as d:
            make_tree(d, {"gone/one.txt": OLD})
            gone = os.path.join(d, "gone")
            results = {}

            def check(w):
                w._populate(gone)
                shutil.rmtree(gone)          # deleted after the scan
                w._load_files(gone)

                def loaded():
                    kids = [k for k in w.tree.get_children(gone) if k.startswith(app.FILEERR_IID)]
                    results["kids"] = kids
                    results["color"] = w.file_rows[kids[0]]["color"]
                    results["text"] = w.tree.item(kids[0], "text")
                    results["reason"] = w._tip_text(kids[0], False)
                self.wait_files(w, gone, loaded)
            self.run_case(d, check)
            self.assertEqual(len(results["kids"]), 1)
            self.assertEqual(results["color"], app.GRAY)
            self.assertEqual(results["text"], "Files could not be listed")
            self.assertIn("could not be listed", results["reason"])

    def test_error_row_does_not_collide_with_a_file_row(self):
        import shutil
        with tempfile.TemporaryDirectory() as d:
            make_tree(d, {"p/keep.txt": OLD, "p/f/x.txt": OLD})
            p, f = os.path.join(d, "p"), os.path.join(d, "p", "f")
            results = {}

            def check(w):
                w._populate(p)
                w._populate(f)
                shutil.rmtree(f)
                with open(f, "wb") as fh:          # the folder became a file
                    fh.write(b"x")
                w._load_files(p)

                def p_loaded():
                    w._load_files(f)
                    self.wait_files(w, f, f_loaded)

                def f_loaded():
                    results["file_row"] = w.tree.exists(app.FILE_IID + f)
                    results["err_row"] = w.tree.exists(app.FILEERR_IID + f)
                    results["err_in_rows"] = (app.FILEERR_IID + f) in w.file_rows
                    results["path"] = w._path_of(app.FILEERR_IID + f)
                self.wait_files(w, p, p_loaded, done=False)
            self.run_case(d, check)
            self.assertTrue(results["file_row"])
            self.assertTrue(results["err_row"])
            self.assertTrue(results["err_in_rows"])
            self.assertEqual(results["path"], f)

    def test_poll_survives_an_unexpected_error_and_keeps_later_messages(self):
        with tempfile.TemporaryDirectory() as d:
            make_tree(d, {"a/one.txt": OLD})
            results = {}

            def check(w):
                seen = []
                orig = w._files_loaded

                def boom(*a):
                    seen.append(a[1])
                    if len(seen) == 1:
                        raise RuntimeError("boom")
                    return orig(*a)
                w._files_loaded = boom
                w.q.put(("files", w.file_gen, "x", [], ""))
                w.q.put(("files", w.file_gen, "y", [], ""))
                job = w._poll_job
                w._poll()
                results["seen"] = len(seen)
                results["status"] = w.status_var.get()
                results["rescheduled"] = w._poll_job is not None and w._poll_job != job
                self.done = True
            self.run_case(d, check)
            self.assertEqual(results["seen"], 2)
            self.assertIn("boom", results["status"])
            self.assertTrue(results["rescheduled"])

    def test_listing_error_row_is_shown_under_a_color_filter(self):
        import shutil
        with tempfile.TemporaryDirectory() as d:
            make_tree(d, {"gone/one.txt": OLD})
            gone = os.path.join(d, "gone")
            results = {}

            def check(w):
                w._populate(gone)
                shutil.rmtree(gone)
                w.filter_var.set("Red only (not used)")
                w._load_files(gone)

                def loaded():
                    results["kids"] = [k for k in w.tree.get_children(gone)
                                       if k.startswith(app.FILEERR_IID)]
                self.wait_files(w, gone, loaded)
            self.run_case(d, check)
            self.assertEqual(len(results["kids"]), 1)


def app_messagebox():
    from tkinter import messagebox
    return messagebox
