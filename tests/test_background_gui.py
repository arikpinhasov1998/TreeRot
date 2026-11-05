"""The window's side of background scans. schtasks never runs here: _quiet_run and _console_run
are replaced for every test, and the buttons are normally only built on Windows."""
import os
import subprocess
import tempfile
import threading
import time
from unittest import mock

from tests.helpers import app
from tests.test_background import JobCase
from tests.test_gui import GuiCase, app_messagebox


def filedialog():
    from tkinter import filedialog as fd
    return fd


class BackgroundGui(GuiCase, JobCase):
    def setUp(self):
        JobCase.setUp(self)
        self.async_errors = []
        self.done = False
        self.tk_thread = threading.current_thread()
        self.schtasks = []
        self.schtasks_threads = []
        for patch in (mock.patch.object(app, "_quiet_run", self.fake_quiet),
                      mock.patch.object(app, "_console_run", self.no_console),
                      mock.patch.object(app, "JOBS_REFRESH_MS", 100)):
            patch.start()
            self.addCleanup(patch.stop)

    def fake_quiet(self, cmd):
        self.schtasks.append(cmd)
        self.schtasks_threads.append(threading.current_thread())
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    def no_console(self, cmd):
        raise AssertionError("a test tried to open the password console")

    def wait(self, w, cond, then, tries=400):
        """Runs then() on the Tk thread once cond() holds. Errors surface in the test."""
        left = [tries]

        def poll():
            try:
                if cond():
                    then()
                elif left[0] <= 0:
                    raise AssertionError("timed out waiting")
                else:
                    left[0] -= 1
                    w.after(25, poll)
                    return
            except Exception as e:
                self.async_errors.append(e)
        poll()

    def finish(self):
        self.done = True

    def run_case(self, check):
        def guarded(w):
            try:
                check(w)
            except Exception as e:
                self.async_errors.append(e)
        with tempfile.TemporaryDirectory() as d:
            self.drive(d, guarded, lambda: bool(self.async_errors) or self.done)
        if self.async_errors:
            raise self.async_errors[0]
        self.assertTrue(self.done, "the test ended before its last step")

    def row(self, w, job):
        tv = w._jobs_ui["tv"]
        return tv.set(job["id"], "state") if tv.exists(job["id"]) else None

    def press(self, w, name):
        w._jobs_ui[name].invoke()


class Buttons(BackgroundGui):
    def test_buttons_are_only_where_background_scans_are_available(self):
        with mock.patch.object(app, "background_available", return_value=False), \
                mock.patch.object(app, "clean_finished_jobs") as clean:
            def check(w):
                self.assertIsNone(w.bg_btn)
                self.assertIsNone(w.jobs_btn)
                self.finish()
            self.run_case(check)
        clean.assert_not_called()

    def test_buttons_open_the_two_flows(self):
        with mock.patch.object(app, "background_available", return_value=True):
            def check(w):
                self.assertEqual(str(w.bg_btn.cget("text")), "Run in background...")
                self.assertEqual(str(w.jobs_btn.cget("text")), "Background scans")
                self.assertEqual(self.schtasks, [])
                w.jobs_btn.invoke()
                self.assertTrue(w._jobs_ui["win"].winfo_exists())
                self.finish()
            self.run_case(check)


class Launch(BackgroundGui):
    def test_cleanup_at_launch_is_off_the_tk_thread_and_a_dead_share_cannot_hold_the_window(self):
        job = self.start()
        self.write_status(job, state="finished", report=job["report"])
        release = threading.Event()
        self.addCleanup(release.set)
        seen = []
        real = app.read_status

        def dead_share(path):
            seen.append(threading.current_thread())
            release.wait(30)
            return real(path)
        with mock.patch.object(app, "background_available", return_value=True), \
                mock.patch.object(app, "read_status", dead_share):
            def check(w):
                # The window opened and scanned a folder while the status read is still stuck.
                self.assertTrue(seen)
                self.assertNotIn(self.tk_thread, seen)
                self.assertEqual(self.schtasks, [])
                release.set()

                def deleted():
                    self.assertEqual(self.schtasks[0][1:4], ["/Delete", "/TN", job["task"]])
                    self.assertNotIn(self.tk_thread, self.schtasks_threads)
                    self.finish()
                self.wait(w, lambda: bool(self.schtasks), deleted)
            self.run_case(check)


class Panel(BackgroundGui):
    def test_rows_show_each_state_in_plain_words(self):
        starting, running = self.start("a.html"), self.start("b.html")
        stopped, done = self.start("c.html"), self.start("d.html")
        failed = self.start("e.html")
        self.write_status(running)
        self.write_status(stopped, updated=time.time() - 3600)
        self.write_status(done, state="finished", report=done["report"])
        self.write_status(failed, state="failed", error="No such share")

        def check(w):
            w._jobs_panel()

            def shown():
                tv = w._jobs_ui["tv"]
                self.assertEqual(self.row(w, starting), "Starting")
                self.assertEqual(self.row(w, running), "Running")
                self.assertEqual(self.row(w, stopped), "Stopped?")
                self.assertEqual(self.row(w, done), "Finished")
                self.assertEqual(tv.set(failed["id"], "detail"), "No such share")
                self.assertIn("seems to have stopped", tv.set(stopped["id"], "detail"))
                self.finish()
            self.wait(w, lambda: self.row(w, failed) == "Failed", shown)
        self.run_case(check)

    def test_folder_names_with_odd_characters_show_as_they_are(self):
        job = self.start()
        record = dict(job, root="\\\\srv\\שיתוף & {x} [y]\\")
        app._save_job(record)

        def check(w):
            w._jobs_panel()

            def shown():
                self.assertEqual(w._jobs_ui["tv"].item(job["id"], "text"), record["root"])
                self.finish()
            self.wait(w, lambda: self.row(w, job) == "Starting", shown)
        self.run_case(check)

    def test_a_dead_share_freezes_nothing_and_holds_up_no_other_row(self):
        dead, good = self.start("dead.html"), self.start("good.html")
        self.write_status(good)
        release = threading.Event()
        self.addCleanup(release.set)
        threads = []
        real = app.read_status

        def read(path):
            threads.append(threading.current_thread())
            if path == dead["status_file"]:
                release.wait(30)
            return real(path)
        with mock.patch.object(app, "read_status", read):
            def check(w):
                t0 = time.monotonic()
                w._jobs_panel()
                self.assertLess(time.monotonic() - t0, 1.0)

                def good_shown():
                    self.assertEqual(self.row(w, dead), "Checking")
                    self.assertNotIn(self.tk_thread, threads)
                    n = sum(1 for t in threads)

                    def after_refreshes():
                        # still one stuck read, however many refreshes went by
                        live = {t for t in threads if t.is_alive()}
                        self.assertLessEqual(len(live), 2)
                        release.set()
                        self.wait(w, lambda: self.row(w, dead) == "Starting", self.finish)
                    self.wait(w, lambda: len(threads) >= n + 3, after_refreshes)
                self.wait(w, lambda: self.row(w, good) == "Running", good_shown)
            self.run_case(check)

    def test_refresh_keeps_the_selection_and_follows_changes(self):
        job = self.start()

        def check(w):
            w._jobs_panel()

            def shown():
                w._jobs_ui["tv"].selection_set(job["id"])
                self.write_status(job)

                def changed():
                    self.assertEqual(w._jobs_ui["tv"].selection(), (job["id"],))
                    self.finish()
                self.wait(w, lambda: self.row(w, job) == "Running", changed)
            self.wait(w, lambda: self.row(w, job) == "Starting", shown)
        self.run_case(check)

    def test_a_second_click_does_not_open_a_second_panel(self):
        def check(w):
            w._jobs_panel()
            ui = w._jobs_ui
            w._jobs_panel()
            self.assertIs(w._jobs_ui, ui)
            ui["win"].destroy()
            self.assertIsNone(w._jobs_ui)
            w._jobs_panel()
            self.assertTrue(w._jobs_ui["win"].winfo_exists())
            self.finish()
        self.run_case(check)

    def test_closing_the_panel_with_a_read_in_flight_is_safe(self):
        job = self.start()
        release = threading.Event()
        self.addCleanup(release.set)
        real = app.read_status

        def read(path):
            release.wait(30)
            return real(path)
        with mock.patch.object(app, "read_status", read):
            def check(w):
                w._jobs_panel()

                def listed():
                    w._jobs_ui["win"].destroy()
                    release.set()
                    w.after(300, self.finish)
                self.wait(w, lambda: self.row(w, job) == "Checking", listed)
            self.run_case(check)


class OpenReport(BackgroundGui):
    def select_when(self, w, job, label, then):
        w._jobs_panel()

        def shown():
            w._jobs_ui["tv"].selection_set(job["id"])
            w.update()
            then()
        self.wait(w, lambda: self.row(w, job) == label, shown)

    def test_running_with_a_report_path_offers_nothing_to_open(self):
        job = self.start()
        with open(job["report"], "w") as f:
            f.write("x")
        self.write_status(job, report=job["report"])
        with mock.patch.object(app, "open_with_default_app") as opener:
            def check(w):
                def then():
                    self.assertEqual(str(w._jobs_ui["open"].cget("state")), "disabled")
                    self.press(w, "open")
                    w.after(200, self.finish)
                self.select_when(w, job, "Running", then)
            self.run_case(check)
        opener.assert_not_called()

    def test_finished_opens_off_the_tk_thread(self):
        job = self.start()
        with open(job["report"], "w") as f:
            f.write("x")
        self.write_status(job, state="finished", report=job["report"])
        opened = []

        def opener(path):
            opened.append((path, threading.current_thread()))
        with mock.patch.object(app, "open_with_default_app", opener):
            def check(w):
                def then():
                    self.assertEqual(str(w._jobs_ui["open"].cget("state")), "normal")
                    self.press(w, "open")

                    def done():
                        self.assertEqual(opened[0][0], job["report"])
                        self.assertIsNot(opened[0][1], self.tk_thread)
                        self.finish()
                    self.wait(w, lambda: bool(opened), done)
                self.select_when(w, job, "Finished", then)
            self.run_case(check)

    def test_finished_with_the_file_gone_offers_nothing(self):
        job = self.start()
        self.write_status(job, state="finished", report=job["report"])

        def check(w):
            def then():
                self.assertEqual(str(w._jobs_ui["open"].cget("state")), "disabled")
                self.assertIn("not found", w._jobs_ui["tv"].set(job["id"], "detail"))
                self.finish()
            self.select_when(w, job, "Finished", then)
        self.run_case(check)


class EndAndRemove(BackgroundGui):
    def selected(self, w, job, label, then):
        w._jobs_panel()

        def shown():
            w._jobs_ui["tv"].selection_set(job["id"])
            w.update()
            then()
        self.wait(w, lambda: self.row(w, job) == label, shown)

    def test_remove_a_finished_scan_runs_off_the_tk_thread_without_asking(self):
        job = self.start()
        self.write_status(job, state="finished", report=job["report"])
        with mock.patch.object(app_messagebox(), "askyesno") as ask:
            def check(w):
                def then():
                    self.press(w, "remove")

                    def gone():
                        self.assertEqual(app.load_jobs(), [])
                        self.assertEqual([c[1] for c in self.schtasks], ["/Delete"])
                        self.assertNotIn(self.tk_thread, self.schtasks_threads)
                        w.after(300, stays_gone)

                    def stays_gone():
                        self.assertIsNone(self.row(w, job))
                        self.finish()
                    self.wait(w, lambda: self.row(w, job) is None, gone)
                self.selected(w, job, "Finished", then)
            self.run_case(check)
        ask.assert_not_called()

    def test_remove_a_running_scan_asks_then_ends_before_deleting(self):
        job = self.start()
        self.write_status(job)
        with mock.patch.object(app_messagebox(), "askyesno", return_value=True) as ask:
            def check(w):
                def then():
                    self.press(w, "remove")

                    def gone():
                        self.assertEqual([c[1] for c in self.schtasks], ["/End", "/Delete"])
                        self.assertTrue(ask.called)
                        self.finish()
                    self.wait(w, lambda: self.row(w, job) is None, gone)
                self.selected(w, job, "Running", then)
            self.run_case(check)

    def test_answering_no_leaves_a_running_scan_alone(self):
        job = self.start()
        self.write_status(job)
        with mock.patch.object(app_messagebox(), "askyesno", return_value=False):
            def check(w):
                def then():
                    self.press(w, "remove")
                    w.after(300, nothing_happened)

                def nothing_happened():
                    self.assertEqual(self.schtasks, [])
                    self.assertEqual(len(app.load_jobs()), 1)
                    self.finish()
                self.selected(w, job, "Running", then)
            self.run_case(check)

    def test_a_failed_remove_says_why_and_keeps_the_row(self):
        job = self.start()
        self.write_status(job, state="finished", report=job["report"])
        self.schtasks_seen = False

        def refuse(cmd):
            self.schtasks_seen = True
            return subprocess.CompletedProcess(cmd, 0 if "/Query" in cmd else 1, b"", b"Access is denied.")
        with mock.patch.object(app, "_quiet_run", refuse):
            def check(w):
                def then():
                    self.press(w, "remove")

                    def told():
                        self.assertIn("Access is denied.", str(w._jobs_ui["note"].cget("text")))
                        self.assertEqual(len(app.load_jobs()), 1)
                        self.finish()
                    self.wait(w, lambda: self.schtasks_seen and self.row(w, job) == "Finished", told)
                self.selected(w, job, "Finished", then)
            self.run_case(check)

    def test_end_asks_then_ends_off_the_tk_thread(self):
        job = self.start()
        self.write_status(job)
        with mock.patch.object(app_messagebox(), "askyesno", return_value=True):
            def check(w):
                def then():
                    self.assertEqual(str(w._jobs_ui["end"].cget("state")), "normal")
                    self.press(w, "end")

                    def ended():
                        self.assertEqual([c[1] for c in self.schtasks], ["/End"])
                        self.assertNotIn(self.tk_thread, self.schtasks_threads)
                        self.finish()
                    self.wait(w, lambda: self.row(w, job) == "Ended", ended)
                self.selected(w, job, "Running", then)
            self.run_case(check)

    def test_a_finished_scan_cannot_be_ended(self):
        job = self.start()
        self.write_status(job, state="finished", report=job["report"])

        def check(w):
            def then():
                self.assertEqual(str(w._jobs_ui["end"].cget("state")), "disabled")
                self.finish()
            self.selected(w, job, "Finished", then)
        self.run_case(check)


class RunInBackground(BackgroundGui):
    def setUp(self):
        super().setUp()
        p = mock.patch.object(app_messagebox(), "showerror")
        self.showerror = p.start()
        self.addCleanup(p.stop)

    def test_bad_input_stops_before_anything_slow_starts(self):
        with mock.patch.object(app, "check_background_folder") as checker:
            def check(w):
                for path, d_from, d_to in (("", "2024-01-01", ""), (self.d, "nonsense", ""),
                                           (self.d, "", ""), (self.d, "2024-12-31", "2024-01-01")):
                    w.path_var.set(path)
                    w.from_var.set(d_from)
                    w.to_var.set(d_to)
                    w._run_background()
                w.after(200, self.finish)
            self.run_case(check)
        checker.assert_not_called()
        self.assertEqual(self.showerror.call_count, 4)

    def test_mapped_drive_is_refused_and_no_save_dialog_opens(self):
        with mock.patch.object(app, "is_mapped_drive", return_value=True), \
                mock.patch.object(filedialog(), "asksaveasfilename") as ask, \
                mock.patch.object(app, "start_background_scan") as start:
            def check(w):
                w.path_var.set(self.d)
                w._run_background()
                self.wait(w, lambda: self.showerror.called, self.finish)
            self.run_case(check)
        self.assertIn("\\\\server\\share", self.showerror.call_args[0][1])
        ask.assert_not_called()
        start.assert_not_called()

    def test_a_dead_folder_cannot_freeze_the_window_and_a_new_try_replaces_it(self):
        release = threading.Event()
        self.addCleanup(release.set)
        threads = []
        real = app.check_background_folder

        def slow(root):
            threads.append(threading.current_thread())
            if root == "\\\\dead\\share":
                release.wait(30)
                return "late answer about the dead share"
            return real(root)
        report = os.path.join(self.d, "r.html")
        with mock.patch.object(app, "check_background_folder", slow), \
                mock.patch.object(filedialog(), "asksaveasfilename", return_value=report), \
                mock.patch.object(app, "start_background_scan") as start:
            def check(w):
                w.path_var.set("\\\\dead\\share")
                t0 = time.monotonic()
                w._run_background()
                self.assertLess(time.monotonic() - t0, 1.0)
                w.path_var.set(self.d)
                w._run_background()
                release.set()

                def done():
                    self.assertNotIn(self.tk_thread, threads)
                    w.after(300, self.finish)
                self.wait(w, lambda: start.called, done)
            self.run_case(check)
        self.assertEqual(start.call_args[0][0], self.d)
        self.showerror.assert_not_called()

    def test_canceling_the_save_dialog_stops(self):
        with mock.patch.object(filedialog(), "asksaveasfilename", return_value=""), \
                mock.patch.object(app, "start_background_scan") as start:
            def check(w):
                w.path_var.set(self.d)
                w._run_background()
                w.after(400, self.finish)
            self.run_case(check)
        start.assert_not_called()

    def test_settings_reach_the_task_off_the_tk_thread_and_success_is_said(self):
        report = os.path.join(self.d, "r.html")
        seen = {}

        def start(root, args, rep):
            seen.update(root=root, args=args, report=rep, thread=threading.current_thread())
            return {}
        with mock.patch.object(filedialog(), "asksaveasfilename", return_value=report), \
                mock.patch.object(app, "start_background_scan", start):
            def check(w):
                w.path_var.set(self.d)
                w.from_var.set("2024-01-01")
                w.to_var.set("2024-12-31")
                w.created_var.set(False)
                w.symlink_var.set(True)
                w.precount_var.set(True)
                w.ex_list.delete(0, "end")
                w.ex_list.insert("end", "-dash & co")
                w._run_background()

                def told():
                    self.assertIn("log off", w.status_var.get())
                    self.finish()
                self.wait(w, lambda: "log off" in w.status_var.get(), told)
            self.run_case(check)
        self.assertIsNot(seen["thread"], self.tk_thread)
        self.assertEqual(seen["root"], self.d)
        self.assertEqual(seen["report"], report)
        a = app.build_parser().parse_args(["x"] + seen["args"])
        self.assertEqual(a.exclude, ["-dash & co"])
        self.assertEqual(a.date_from.strftime("%Y-%m-%d"), "2024-01-01")
        self.assertEqual(a.date_to.strftime("%Y-%m-%d"), "2024-12-31")
        self.assertEqual(a.created, "off")
        self.assertTrue(a.follow_symlinks)
        self.assertTrue(a.precount)

    def test_a_failure_is_shown_and_a_new_try_is_allowed(self):
        report = os.path.join(self.d, "r.html")

        def fail(root, args, rep):
            raise app.BackgroundError("The background task could not be created.")
        with mock.patch.object(filedialog(), "asksaveasfilename", return_value=report), \
                mock.patch.object(app, "start_background_scan", fail):
            def check(w):
                w.path_var.set(self.d)
                w._run_background()

                def told():
                    self.assertIn("could not be created", self.showerror.call_args[0][1])
                    self.assertIn("not started", w.status_var.get())
                    self.assertFalse(w._bg_starting)
                    self.finish()
                self.wait(w, lambda: self.showerror.called, told)
            self.run_case(check)

    def test_a_double_start_does_not_open_a_second_prompt(self):
        report = os.path.join(self.d, "r.html")
        release = threading.Event()
        self.addCleanup(release.set)
        calls = []

        def start(root, args, rep):
            calls.append(root)
            release.wait(30)
            return {}
        with mock.patch.object(filedialog(), "asksaveasfilename", return_value=report), \
                mock.patch.object(app, "start_background_scan", start):
            def check(w):
                w.path_var.set(self.d)
                w._run_background()

                def first_running():
                    w._run_background()
                    w.after(300, later)

                def later():
                    self.assertEqual(len(calls), 1)
                    release.set()
                    self.wait(w, lambda: not w._bg_starting, self.finish)
                self.wait(w, lambda: bool(calls), first_running)
            self.run_case(check)
