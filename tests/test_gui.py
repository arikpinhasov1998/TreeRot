import gc
import os
import subprocess
import sys
import tempfile
import threading
import time
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
                    w._activate_more(more)
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

    def test_arrowing_onto_the_more_row_loads_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            make_tree(d, {"big/f%04d.txt" % n: OLD for n in range(5)})
            big = os.path.join(d, "big")
            results = {}

            def check(w):
                w._populate(big)
                more = app.MORE_IID + big
                w.tree.selection_set(more)
                w._on_select(None)
                results["loading"] = big in w.file_loading
                results["cached"] = big in w.file_cache
                self.done = True
            self.run_case(d, check)
            self.assertFalse(results["loading"])
            self.assertFalse(results["cached"])

    def test_click_and_enter_on_more_load_and_keep_focus_usable(self):
        with tempfile.TemporaryDirectory() as d:
            make_tree(d, {"big/f%04d.txt" % n: OLD for n in range(app.FILE_PAGE + 5)})
            big = os.path.join(d, "big")
            results = {}

            def check(w):
                w._populate(big)
                more = app.MORE_IID + big
                w.tree.identify_row = lambda y: more
                w.tree.selection_set(more)
                w._on_press(mock.Mock(y=1))
                w._on_click(mock.Mock(y=1))                 # a mouse click loads page 1

                def page1():
                    first = w.tree.get_children(big)[0]
                    results["sel1"] = (w.tree.selection(), w.tree.focus(), first)
                    more2 = app.MORE_IID + big
                    w.tree.selection_set(more2)
                    w.tree.focus(more2)
                    results["break"] = w._on_activate_key(None)   # Enter on the focused row
                    kids = w.tree.get_children(big)
                    new_first = [k for k in kids if k.startswith(app.FILE_IID)][app.FILE_PAGE]
                    results["sel2"] = (w.tree.selection(), w.tree.focus(), new_first)
                self.wait_files(w, big, page1)
            self.run_case(d, check)
            sel, focus, first = results["sel1"]
            self.assertEqual((sel, focus), ((first,), first))
            self.assertEqual(results["break"], "break")
            sel, focus, first = results["sel2"]
            self.assertEqual((sel, focus), ((first,), first))

    def test_at_most_four_listings_run_and_a_refresh_drops_the_queue(self):
        import threading
        import time
        with tempfile.TemporaryDirectory() as d:
            make_tree(d, {"f%d/x.txt" % n: OLD for n in range(6)})
            gate, lock = threading.Event(), threading.Lock()
            state = {"now": 0, "peak": 0, "calls": 0}
            results = {}

            def fake(path, *a):
                with lock:
                    state["now"] += 1
                    state["calls"] += 1
                    state["peak"] = max(state["peak"], state["now"])
                gate.wait(10)
                with lock:
                    state["now"] -= 1
                return [], ""

            def check(w):
                folders = [os.path.join(d, "f%d" % n) for n in range(6)]
                patcher = mock.patch.object(app, "list_folder_files", fake)
                patcher.start()                     # stays active until the test is cleaned up
                self.addCleanup(patcher.stop)
                self.addCleanup(gate.set)
                for f in folders:
                    w._load_files(f)

                def later():
                    results["calls_before"] = state["calls"]
                    w._refresh_tree()               # new generation: queued work is dropped
                    gate.set()
                    w.after(800, end)

                def end():
                    results["calls_after"] = state["calls"]
                    results["peak"] = state["peak"]
                    self.done = True
                w.after(500, later)
            self.run_case(d, check)
            self.assertEqual(results["calls_before"], 4)
            self.assertEqual(results["calls_after"], 4)
            self.assertEqual(results["peak"], 4)

    def test_open_in_file_manager_on_a_file_row_does_not_run_the_file(self):
        with tempfile.TemporaryDirectory() as d:
            make_tree(d, {"a/tool.exe": OLD})
            a = os.path.join(d, "a")
            exe = os.path.join(a, "tool.exe")
            results = {}

            def check(w):
                w._populate(a)
                w._load_files(a)

                def loaded():
                    w.tree.selection_set(app.FILE_IID + exe)
                    with mock.patch.object(app.subprocess, "Popen") as popen, \
                            mock.patch.object(app.os, "startfile", create=True) as sf:
                        w._open_path()
                    results["argv"] = popen.call_args[0][0] if popen.called else None
                    results["startfile"] = sf.called
                self.wait_files(w, a, loaded)
            self.run_case(d, check)
            self.assertEqual(results["argv"], app.file_manager_command(exe, True, app.sys.platform))
            self.assertFalse(results["startfile"])
            self.assertNotEqual(results["argv"], ["open", exe])

    def test_open_never_runs_a_folder_row_that_became_a_file(self):
        import shutil
        with tempfile.TemporaryDirectory() as d:
            make_tree(d, {"p/keep.txt": OLD, "p/f/x.txt": OLD})
            p, f = os.path.join(d, "p"), os.path.join(d, "p", "f")
            results = {}

            def check(w):
                w._populate(p)
                shutil.rmtree(f)
                with open(f, "wb") as fh:
                    fh.write(b"x")
                w.tree.selection_set(f)                 # the folder row, now a file on disk
                with mock.patch.object(app.subprocess, "Popen") as popen:
                    w._open_path()
                results["argv"] = popen.call_args[0][0] if popen.called else None
                self.done = True
            self.run_case(d, check)
            self.assertEqual(results["argv"], app.file_manager_command(f, True, app.sys.platform))

    def _hung_listing_case(self, dead_count, max_abandoned=None):
        """Folders dead0..N block on a gate; 'ok' lists normally. Returns what happened."""
        import threading
        real = app.list_folder_files
        gate = threading.Event()
        calls = []
        self.addCleanup(gate.set)

        def fake(path, *a):
            calls.append(os.path.basename(path))
            if os.path.basename(path).startswith("dead"):
                gate.wait(20)
            return real(path, *a)
        patches = [mock.patch.object(app, "list_folder_files", fake),
                   mock.patch.object(app, "LISTING_TIMEOUT", 0.3)]
        if max_abandoned is not None:
            patches.append(mock.patch.object(app, "MAX_ABANDONED", max_abandoned))
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        results = {}
        d = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, d, True)
        spec = {"dead%d/x.txt" % n: OLD for n in range(dead_count)}
        spec["ok/y.txt"] = NEW
        make_tree(d, spec)

        def check(w):
            for n in range(dead_count):
                w._populate(os.path.join(d, "dead%d" % n))
                w._load_files(os.path.join(d, "dead%d" % n))
            ok = os.path.join(d, "ok")
            w._populate(ok)
            w._load_files(ok)

            def snapshot(tag):
                results[tag] = {
                    "texts": [w.tree.item(k, "text") for n in range(dead_count)
                              for k in w.tree.get_children(os.path.join(d, "dead%d" % n))],
                    "reasons": [f["reason"] for k, f in w.file_rows.items()
                                if k.startswith(app.FILEERR_IID)],
                    "ok_rows": [w.file_rows[k]["name"] for k in w.tree.get_children(ok)
                                if k.startswith(app.FILE_IID)],
                    "active": w.file_active, "abandoned": len(w.file_abandoned),
                    "calls": list(calls)}

            def after_timeout():
                snapshot("timed_out")
                gate.set()                          # the dead shares answer, far too late
                w.after(600, final)

            def final():
                snapshot("late")
                self.done = True
            w.after(1500, after_timeout)
        self.run_case(d, check)
        return results

    def test_hung_listings_time_out_and_a_healthy_folder_still_lists(self):
        r = self._hung_listing_case(4)
        t = r["timed_out"]
        self.assertEqual(len(t["reasons"]), 4)
        self.assertTrue(all("did not respond" in x for x in t["reasons"]))
        self.assertEqual(t["ok_rows"], ["y.txt"])
        self.assertEqual(t["active"], 0)
        late = r["late"]
        self.assertEqual(len(late["reasons"]), 4)            # late results were discarded
        self.assertEqual(late["texts"], ["Files could not be listed"] * 4)
        self.assertEqual(late["abandoned"], 0)
        self.assertEqual(late["active"], 0)

    def test_too_many_abandoned_listings_show_an_error_instead_of_a_thread(self):
        r = self._hung_listing_case(4, max_abandoned=1)
        t = r["timed_out"]
        self.assertEqual(t["ok_rows"], [])
        self.assertEqual(len(t["reasons"]), 5)               # 4 timeouts + the refused one
        self.assertNotIn("ok", t["calls"])

    def test_a_failure_finishing_the_scan_cannot_leave_scan_disabled(self):
        with tempfile.TemporaryDirectory() as d:
            make_tree(d, {"a/one.txt": OLD})
            results = {}

            def check(w):
                def broken():
                    raise RuntimeError("tree exploded")
                w._refresh_tree = broken
                w.scan_btn.config(state="disabled")
                w.cancel_btn.config(state="normal")
                w.q.put(("done", w.rows, "since x", False, 0))
                with mock.patch.object(app_messagebox(), "showerror") as err, \
                        mock.patch.object(app.traceback, "print_exc") as tb:
                    w._poll()
                results["scan"] = str(w.scan_btn.cget("state"))
                results["cancel"] = str(w.cancel_btn.cget("state"))
                results["export"] = str(w.export_btn.cget("state"))
                results["dialog"] = err.called and "tree exploded" in str(err.call_args)
                results["logged"] = tb.called
                self.done = True
            self.run_case(d, check)
            self.assertEqual(results["scan"], "normal")
            self.assertEqual(results["cancel"], "disabled")
            self.assertEqual(results["export"], "normal")
            self.assertTrue(results["dialog"])
            self.assertTrue(results["logged"])

    def test_a_failure_midway_through_a_page_leaves_usable_rows(self):
        with tempfile.TemporaryDirectory() as d:
            make_tree(d, {"big/f%02d.txt" % n: OLD for n in range(10)})
            big = os.path.join(d, "big")
            results = {}

            def check(w):
                w._populate(big)
                real_insert = w.tree.insert
                count = [0]

                def flaky(parent, index, **kw):
                    if kw.get("iid", "").startswith(app.FILE_IID):
                        count[0] += 1
                        if count[0] == 4:
                            raise RuntimeError("insert failed")
                    return real_insert(parent, index, **kw)
                w.tree.insert = flaky
                w.tree.selection_set(app.MORE_IID + big)
                w.tree.focus(app.MORE_IID + big)
                w._load_files(big)

                def loaded():
                    kids = w.tree.get_children(big)
                    results["files"] = [k for k in kids if k.startswith(app.FILE_IID)]
                    results["err"] = [k for k in kids if k.startswith(app.FILEERR_IID)]
                    results["more"] = w.tree.exists(app.MORE_IID + big)
                    results["sel"] = w.tree.selection()
                    results["focus"] = w.tree.focus()
                    w.tree.insert = real_insert
                    w._activate_more(app.MORE_IID + big)         # the rest can still be fetched
                    results["after_retry"] = len([k for k in w.tree.get_children(big)
                                                  if k.startswith(app.FILE_IID)])
                self.wait_files(w, big, loaded)
            self.run_case(d, check)
            self.assertEqual(len(results["files"]), 3)
            self.assertEqual(len(results["err"]), 1)
            self.assertTrue(results["more"])
            self.assertEqual(results["sel"], (results["files"][0],))
            self.assertEqual(results["focus"], results["files"][0])
            self.assertEqual(results["after_retry"], 10)

    def test_release_on_more_loads_only_if_the_press_was_on_the_same_row(self):
        with tempfile.TemporaryDirectory() as d:
            make_tree(d, {"big/f%d.txt" % n: OLD for n in range(3)})
            big = os.path.join(d, "big")
            results = {}

            def check(w):
                w._populate(big)
                more = app.MORE_IID + big
                rows = {"press": big, "release": more}
                w.tree.identify_row = lambda y: rows["press"] if y == 1 else rows["release"]
                w._on_press(mock.Mock(y=1))             # pressed on the folder row...
                w._on_click(mock.Mock(y=2))             # ...and released on the MORE row
                results["dragged"] = big in w.file_loading or big in w.file_cache
                rows["press"] = more
                w._on_press(mock.Mock(y=1))             # pressed and released on MORE
                w._on_click(mock.Mock(y=2))
                results["clicked"] = big in w.file_loading or big in w.file_cache
                self.done = True
            self.run_case(d, check)
            self.assertFalse(results["dragged"])
            self.assertTrue(results["clicked"])

    def _patch_listing(self, fake, timeout=0.4):
        import threading
        gate = threading.Event()
        self.addCleanup(gate.set)
        for p in (mock.patch.object(app, "list_folder_files", fake),
                  mock.patch.object(app, "LISTING_TIMEOUT", timeout)):
            p.start()
            self.addCleanup(p.stop)
        return gate

    @staticmethod
    def _until(w, cond, then, tries=300):
        def poll(n=[tries]):
            if cond() or n[0] <= 0:
                then()
            else:
                n[0] -= 1
                w.after(50, poll)
        poll()

    def test_a_slow_listing_that_keeps_making_progress_is_not_timed_out(self):
        import time
        real = app.list_folder_files

        def slow(path, *a):
            progress = a[-1]
            for _ in range(12):                     # 1.2 s in total, never silent for 0.4 s
                time.sleep(0.1)
                progress()
            return real(path, *a)
        self._patch_listing(slow)
        with tempfile.TemporaryDirectory() as d:
            make_tree(d, {"a/one.txt": OLD, "a/two.txt": NEW})
            a = os.path.join(d, "a")
            results = {}

            def check(w):
                w._populate(a)
                w._load_files(a)

                def done():
                    results["names"] = sorted(f["name"] for k, f in w.file_rows.items()
                                              if k.startswith(app.FILE_IID))
                    results["err"] = [k for k in w.file_rows if k.startswith(app.FILEERR_IID)]
                    self.done = True
                self._until(w, lambda: a in w.file_cache, done)
            self.run_case(d, check)
            self.assertEqual(results["names"], ["one.txt", "two.txt"])
            self.assertEqual(results["err"], [])

    def test_a_listing_that_stalls_after_some_progress_gets_the_error_row(self):
        def stalls(path, *a):
            progress = a[-1]
            for _ in range(3):
                progress()
            gate.wait(20)
            return [], ""
        gate = self._patch_listing(stalls)
        with tempfile.TemporaryDirectory() as d:
            make_tree(d, {"a/one.txt": OLD})
            a = os.path.join(d, "a")
            results = {}

            def check(w):
                w._populate(a)
                w._load_files(a)

                def done():
                    results["reasons"] = [f["reason"] for k, f in w.file_rows.items()
                                          if k.startswith(app.FILEERR_IID)]
                    results["active"] = w.file_active
                    self.done = True
                self._until(w, lambda: a in w.file_cache, done)
            self.run_case(d, check)
            self.assertEqual(len(results["reasons"]), 1)
            self.assertIn("did not respond", results["reasons"][0])
            self.assertEqual(results["active"], 0)

    def test_reopening_a_timed_out_folder_retries(self):
        real = app.list_folder_files
        calls = []

        def first_hangs(path, *a):
            calls.append(path)
            if len(calls) == 1:
                gate.wait(20)
            return real(path, *a)
        gate = self._patch_listing(first_hangs)
        with tempfile.TemporaryDirectory() as d:
            make_tree(d, {"a/one.txt": OLD})
            a = os.path.join(d, "a")
            results = {}

            def check(w):
                w._populate(a)
                w._load_files(a)

                def timed_out():
                    results["cached_after_timeout"] = a in w.file_cache
                    results["err_row"] = w.tree.exists(app.FILEERR_IID + a)
                    w.tree.item(a, open=False)
                    w.tree.item(a, open=True)
                    w._load_files(a)                    # what reopening the folder does
                    self._until(w, lambda: a in w.file_cache, retried)

                def retried():
                    results["calls"] = len(calls)
                    results["rows"] = [f["name"] for k, f in w.file_rows.items()
                                       if k.startswith(app.FILE_IID)]
                    results["err_after"] = w.tree.exists(app.FILEERR_IID + a)
                    self.done = True
                self._until(w, lambda: w.tree.exists(app.FILEERR_IID + a), timed_out)
            self.run_case(d, check)
            self.assertFalse(results["cached_after_timeout"])
            self.assertTrue(results["err_row"])
            self.assertEqual(results["calls"], 2)
            self.assertEqual(results["rows"], ["one.txt"])
            self.assertFalse(results["err_after"])

    def test_a_thread_that_cannot_start_is_rolled_back_with_an_error_row(self):
        with tempfile.TemporaryDirectory() as d:
            make_tree(d, {"a/one.txt": OLD})
            a = os.path.join(d, "a")
            results = {}

            class NoThread:
                def __init__(self, *args, **kw):
                    pass

                def start(self):
                    raise RuntimeError("can't start new thread")

            def check(w):
                w._populate(a)
                with mock.patch.object(app.threading, "Thread", NoThread):
                    w._load_files(a)
                results["live"] = dict(w.file_live)
                results["active"] = w.file_active
                results["loading"] = a in w.file_loading
                results["cached"] = a in w.file_cache
                results["err"] = [f["reason"] for k, f in w.file_rows.items()
                                  if k.startswith(app.FILEERR_IID)]
                results["more_text"] = (w.tree.item(app.MORE_IID + a, "text")
                                        if w.tree.exists(app.MORE_IID + a) else None)
                self.done = True
            self.run_case(d, check)
            self.assertEqual(results["live"], {})
            self.assertEqual(results["active"], 0)
            self.assertFalse(results["loading"])
            self.assertFalse(results["cached"])
            self.assertEqual(len(results["err"]), 1)
            self.assertIn("no worker could be started", results["err"][0])
            self.assertIsNone(results["more_text"])


class ReportFailure(GuiCase):
    def test_any_error_in_the_export_worker_shows_and_the_window_recovers(self):
        from tkinter import filedialog
        with tempfile.TemporaryDirectory() as d:
            make_tree(d, {"a/f.txt": OLD})
            seen = {}
            bad = UnicodeEncodeError("utf-8", "caf\udce9", 3, 4, "surrogates not allowed")

            def check(w):
                def shown(title, msg):
                    seen.update(err=msg, button=str(w.report_btn.cget("state")),
                                status=w.status_var.get())
                err.side_effect = shown
                w._save_report("html", "2", None)

            with mock.patch.object(filedialog, "asksaveasfilename",
                                   return_value=os.path.join(d, "r.html")), \
                    mock.patch.object(app, "write_report", side_effect=bad), \
                    mock.patch.object(app_messagebox(), "showerror") as err:
                self.drive(d, check, lambda: "err" in seen)
            self.assertIn("surrogates", seen.get("err", ""))
            self.assertEqual(seen["button"], "normal")
            self.assertEqual(seen["status"], "The report was not saved.")


class ScanFolderCheck(GuiCase):
    """A mistyped share name can take a minute to fail: that wait must not be on the Tk thread."""

    def _blocked(self, d, wait=3):
        dead = os.path.join(d, "dead")
        real = os.path.isdir
        self.entered, self.release = threading.Event(), threading.Event()
        self.addCleanup(self.release.set)
        self.check_threads = []

        def isdir(path):
            if path == dead:
                self.check_threads.append(threading.current_thread())
                self.entered.set()
                self.release.wait(wait)
                return False
            return real(path)
        return dead, mock.patch.object(app.os.path, "isdir", isdir)

    def test_a_blocked_check_does_not_block_the_window(self):
        with tempfile.TemporaryDirectory() as d:
            make_tree(d, {"a/f.txt": OLD})
            dead, patch = self._blocked(d)
            seen, errors = {}, []

            def check(w):
                def later():
                    try:
                        seen["ticked_while_blocked"] = self.entered.is_set() and not self.release.is_set()
                        self.release.set()
                    except Exception as e:
                        errors.append(e)
                w.path_var.set(dead)
                t0 = time.monotonic()
                w._start()
                seen["start_seconds"] = time.monotonic() - t0
                seen["status"] = w.status_var.get()
                seen["scan_btn"] = str(w.scan_btn.cget("state"))
                seen["rows_kept"] = len(w.rows)
                w.after(200, later)

            def shown(title, msg):
                seen["error"] = msg
            with patch, mock.patch.object(app_messagebox(), "showerror", side_effect=shown):
                self.drive(d, check, lambda: "error" in seen)
            self.assertLess(seen["start_seconds"], 1)
            self.assertEqual(seen["status"], "Checking the folder...")
            self.assertEqual(seen["scan_btn"], "disabled")
            self.assertTrue(seen.get("ticked_while_blocked"))
            self.assertIsNot(self.check_threads[0], threading.current_thread())
            self.assertIn("not reachable", seen["error"])
            self.assertEqual(errors, [])

    def test_a_folder_that_fails_the_check_gives_the_buttons_back_and_keeps_the_results(self):
        with tempfile.TemporaryDirectory() as d:
            make_tree(d, {"a/f.txt": OLD})
            dead, patch = self._blocked(d, wait=0)
            seen = {}

            def check(w):
                before = len(w.rows)

                def shown(title, msg):
                    seen.update(scan=str(w.scan_btn.cget("state")),
                                cancel=str(w.cancel_btn.cget("state")),
                                report=str(w.report_btn.cget("state")),
                                kept=len(w.rows) == before and before > 0)
                err.side_effect = shown
                w.path_var.set(dead)
                w._start()
            with patch, mock.patch.object(app_messagebox(), "showerror") as err:
                self.drive(d, check, lambda: "scan" in seen)
            self.assertEqual((seen["scan"], seen["cancel"], seen["report"]),
                             ("normal", "disabled", "normal"))
            self.assertTrue(seen["kept"])

    def test_cancel_during_the_check_drops_its_late_answer(self):
        with tempfile.TemporaryDirectory() as d:
            make_tree(d, {"a/f.txt": OLD})
            dead, patch = self._blocked(d)
            seen = {}

            def check(w):
                def answered():
                    seen["scan_btn"] = str(w.scan_btn.cget("state"))
                    seen["done"] = True

                def canceled():
                    w._cancel()
                    seen["after_cancel"] = str(w.scan_btn.cget("state"))
                    self.release.set()
                    w.after(300, answered)
                w.path_var.set(dead)
                w._start()
                w.after(100, canceled)
            with patch, mock.patch.object(app_messagebox(), "showerror") as err:
                self.drive(d, check, lambda: seen.get("done"))
            self.assertEqual(seen["after_cancel"], "normal")
            self.assertEqual(seen["scan_btn"], "normal")
            self.assertFalse(err.called)

    def test_an_empty_path_and_a_bad_date_need_no_check(self):
        with tempfile.TemporaryDirectory() as d:
            make_tree(d, {"a/f.txt": OLD})

            def check(w):
                with mock.patch.object(app_messagebox(), "showerror") as err:
                    w.path_var.set("  ")
                    w._start()
                    self.assertEqual(err.call_args[0][0], "Invalid path")
                    w.path_var.set(d)
                    w.from_var.set("nonsense")
                    w._start()
                    self.assertEqual(err.call_args[0][0], "Invalid date")
                self.assertEqual(str(w.scan_btn.cget("state")), "normal")
            self.drive(d, check)


class OpenPath(GuiCase):
    def _is_file_for(self, make_row):
        with tempfile.TemporaryDirectory() as d:
            make_tree(d, {"a/f.txt": OLD})
            seen = {}

            def check(w):
                w.tree.selection_set(make_row(w, d))
                with mock.patch.object(app, "file_manager_command",
                                       return_value=["x"]) as cmd, \
                        mock.patch.object(app.subprocess, "Popen") as popen:
                    w._open_path()
                seen["is_file"] = cmd.call_args[0][1]
                seen["ran"] = popen.call_args[0][0]
            self.drive(d, check)
            self.assertEqual(seen["ran"], ["x"])
            return seen["is_file"]

    def test_a_real_folder_opens(self):
        self.assertFalse(self._is_file_for(lambda w, d: d))

    def test_a_path_that_cannot_be_checked_is_revealed_never_run(self):
        def vanished(w, d):
            import shutil
            shutil.rmtree(os.path.join(d, "a"))
            w._populate(d)
            return os.path.join(d, "a")
        self.assertTrue(self._is_file_for(vanished))


class NoBrowserHint(GuiCase):
    def test_the_export_dialog_names_every_browser_tried(self):
        with tempfile.TemporaryDirectory() as d:
            make_tree(d, {"a/f.txt": OLD})
            seen = {}

            def texts(widget):
                out = []
                for c in widget.winfo_children():
                    try:
                        out.append(str(c.cget("text")))
                    except Exception:
                        pass
                    out.extend(texts(c))
                return out

            def check(w):
                with mock.patch.object(app, "find_browser", return_value=None):
                    w._export_report()
                win = [c for c in w.winfo_children() if c.winfo_class() == "Toplevel"][-1]
                seen["texts"] = " ".join(texts(win))
                win.destroy()
            self.drive(d, check)
            for name in ("Edge", "Chrome", "Chromium", "Brave"):
                self.assertIn(name, seen["texts"])


class LevelChoices(GuiCase):
    def test_the_window_goes_to_twenty_like_the_report(self):
        with tempfile.TemporaryDirectory() as d:
            make_tree(d, {"a/f.txt": OLD})
            seen = {}

            def check(w):
                seen["values"] = list(w.tk.splitlist(w.levels_cb.cget("values")))
                w._show_levels("20")
                seen["level"] = w.levels_var.get()
            self.drive(d, check)
            self.assertEqual(seen["values"], [str(n) for n in range(1, 21)] + ["Unlimited"])
            self.assertEqual(seen["level"], "20")


def app_messagebox():
    from tkinter import messagebox
    return messagebox
