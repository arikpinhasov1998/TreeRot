"""Background scans: started as your own process (no password, no administrator), followed
through a status file, ended, removed, and reported by a desktop notification. No test starts
a real process, service or scheduled task except WholeCommand, which runs the exact worker."""
import json
import os
import plistlib
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from tests.helpers import WINDOWS_RUN_VALUES, app


def refusing_scheduler(cmd, **kw):
    """A Task Scheduler that will not delete: the task is still listed."""
    if "/Delete" in cmd:
        refusing_scheduler.name = cmd[cmd.index("/TN") + 1]
    if "/Query" in cmd:
        listing = '"\\%s","N/A","Ready"\r\n' % refusing_scheduler.name
        return subprocess.CompletedProcess(cmd, 0, listing.encode(), b"")
    return subprocess.CompletedProcess(cmd, 1, b"", b"Access is denied.")


def done(cmd, rc=0, out=b""):
    return subprocess.CompletedProcess(cmd, rc, out, b"")


class JobCase(unittest.TestCase):
    """Jobs are started for real except the process itself: spawn, the process table and every
    system tool are fakes, so nothing outside the temp folder is touched."""

    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.d = d.name
        self.procs = {}                # pid -> start time: the fake process table
        self.spawned, self.stopped, self.cmds = [], [], []
        patches = [
            mock.patch.object(app, "JOBS_DIR", os.path.join(d.name, "jobs")),
            mock.patch.object(app, "AUTOSTART_DIR", os.path.join(d.name, "autostart")),
            mock.patch.object(app, "LAUNCH_AGENTS_DIR", os.path.join(d.name, "agents")),
            # never the real schtasks, process launcher or process killer, on any system
            mock.patch.object(app, "_quiet_run", side_effect=app.BackgroundError("not in a test")),
            mock.patch.object(app, "_spawn_detached", side_effect=AssertionError("real spawn")),
            mock.patch.object(app, "_run_tool", side_effect=AssertionError("real tool")),
            mock.patch.object(app, "process_start", self.fake_start),
            mock.patch.object(app, "stop_process", self.fake_stop),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        WINDOWS_RUN_VALUES.clear()
        self.addCleanup(WINDOWS_RUN_VALUES.clear)

    def fake_start(self, pid, platform=None, run=None):
        return self.procs.get(pid)

    def fake_stop(self, pid, start, platform=None):
        self.stopped.append(pid)
        return self.procs.pop(pid, None) is not None

    def fake_spawn(self, cmd):
        self.spawned.append(cmd)
        pid = 4000 + len(self.spawned)
        self.procs[pid] = f"start-{pid}"
        return pid

    def run_ok(self, cmd, **kw):
        self.cmds.append(cmd)
        return done(cmd)

    def start(self, report="r.html", args=("--from", "2024-01-01"), platform="win32", runner=None):
        return app.start_background_scan(self.d, list(args), os.path.join(self.d, report),
                                         runner=runner or self.run_ok, spawn=self.fake_spawn,
                                         platform=platform)

    def legacy(self, report="old.html", **fields):
        """A scheduled-task record written by a version before this one."""
        job_id = f"20250101-000000-{os.urandom(2).hex()}"
        path = os.path.join(self.d, report)
        job = {"id": job_id, "task": app.TASK_PREFIX + job_id, "root": "\\\\srv\\s",
               "report": path, "status_file": path + app.STATUS_SUFFIX, "started": time.time()}
        job.update(fields)
        os.makedirs(app.JOBS_DIR, exist_ok=True)
        app._save_job(job)
        return job

    def write_status(self, job, **fields):
        data = {"state": "running", "percent": "5%", "counts": "c", "times": "t",
                "updated": time.time(), "report": None, "error": ""}
        data.update(fields)
        with open(job["status_file"], "w", encoding="utf-8") as f:
            json.dump(data, f)


class Command(unittest.TestCase):
    def test_from_source_runs_this_script_with_python(self):
        with mock.patch.object(app.sys, "frozen", False, create=True):
            cmd = app.worker_command("/data", ["--from", "2024-01-01"], "/r.html.status.json", "ID")
        self.assertEqual(cmd[1], os.path.abspath(app.__file__))
        self.assertEqual(cmd[2:], ["/data", "--from", "2024-01-01", "--progress", "none",
                                   "--status-file", "/r.html.status.json", "--job-id", "ID"])

    def test_frozen_runs_the_one_program_itself(self):
        with tempfile.NamedTemporaryFile() as exe, \
                mock.patch.object(app.sys, "frozen", True, create=True), \
                mock.patch.object(app.sys, "executable", exe.name):
            self.assertEqual(app.self_command(), [exe.name])

    def test_refuses_when_the_program_cannot_be_found(self):
        with mock.patch.object(app.sys, "executable", ""):
            with self.assertRaises(app.BackgroundError):
                app.self_command()

    def test_the_worker_options_are_hidden_but_parsed(self):
        a = app.build_parser().parse_args(["/x", "--job-id", "ID", "--status-file", "s"])
        self.assertEqual(a.job_id, "ID")
        self.assertTrue(app.build_parser().parse_args(["--login-check"]).login_check)
        self.assertNotIn("--job-id", app.build_parser().format_help())


class Arguments(unittest.TestCase):
    def test_settings_become_arguments(self):
        args = app.background_args("2024-01-01", "2024-12-31", ["-odd", "x"], created=False,
                                   follow_symlinks=True, precount=True)
        self.assertEqual(args, ["--format", "summary", "-q", "--from", "2024-01-01",
                                "--to", "2024-12-31", "--exclude=-odd", "--exclude=x",
                                "--created", "off", "--follow-symlinks", "--precount"])
        a = app.build_parser().parse_args(["/x"] + args)
        self.assertEqual(a.exclude, ["-odd", "x"])


class FolderCheck(unittest.TestCase):
    def test_missing_and_good_folders(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(app.check_background_folder(d))
            self.assertIn("does not exist", app.check_background_folder(os.path.join(d, "no")))

    def test_file_manager_shares_are_recognised_on_linux_only(self):
        gvfs = "/run/user/1000/gvfs/smb-share:server=nas,share=data/projects"
        self.assertTrue(app.is_file_manager_share(gvfs, "linux"))
        self.assertTrue(app.is_file_manager_share("/run/user/1000/gvfs/x", "linux"))
        for path in ("/mnt/nas/data", "/run/user/1000/other", "/home/u/gvfs/x"):
            self.assertFalse(app.is_file_manager_share(path, "linux"), path)
        self.assertFalse(app.is_file_manager_share(gvfs, "darwin"))
        self.assertFalse(app.is_file_manager_share(gvfs, "win32"))


class StartProcess(JobCase):
    def test_windows_and_macos_start_a_detached_copy_with_no_password(self):
        for platform in ("win32", "darwin"):
            with self.subTest(platform):
                job = self.start(f"{platform}.html", platform=platform)
                self.assertEqual(job["kind"], "process")
                self.assertEqual(job["pid"], 4000 + len(self.spawned))
                self.assertEqual(job["pid_start"], f"start-{job['pid']}")
                self.assertEqual(job["logoff"], "stops")
                cmd = self.spawned[-1]
                self.assertEqual(cmd[cmd.index("--job-id") + 1], job["id"])
                self.assertEqual(cmd[cmd.index("--status-file") + 1], job["status_file"])
                self.assertEqual(cmd[cmd.index("--report") + 1], job["report"])
        self.assertEqual(self.cmds, [])                  # no scheduler, no tool at all

    def test_the_record_is_saved_before_the_process_starts(self):
        seen = []

        def spawn(cmd):
            seen.append([j["id"] for j in app.load_jobs()])
            return self.fake_spawn(cmd)
        job = app.start_background_scan(self.d, [], os.path.join(self.d, "r.html"),
                                        runner=self.run_ok, spawn=spawn, platform="win32")
        self.assertEqual(seen, [[job["id"]]])
        self.assertEqual(app.load_jobs()[0]["pid"], job["pid"])

    def test_a_process_that_will_not_start_leaves_nothing_behind(self):
        def spawn(cmd):
            raise OSError("no such program")
        with self.assertRaises(app.BackgroundError) as c:
            app.start_background_scan(self.d, [], os.path.join(self.d, "r.html"),
                                      runner=self.run_ok, spawn=spawn, platform="win32")
        self.assertIn("no such program", str(c.exception))
        self.assertEqual(app.load_jobs(), [])
        self.assertEqual(WINDOWS_RUN_VALUES, {})

    def test_bad_input_is_refused_before_anything_starts(self):
        for report, args, words in (("r.txt", [], ".html"),
                                    (os.path.join("no", "r.html"), [], "does not exist"),
                                    ("r.html", ["--from", "2024-13-01"], "")):
            with self.subTest(report=report, args=args), self.assertRaises(app.BackgroundError) as c:
                self.start(report, args=args)
            self.assertIn(words, str(c.exception))
        self.assertEqual(self.spawned, [])
        self.assertEqual(app.load_jobs(), [])

    def test_relative_paths_become_full_ones(self):
        os.chdir(self.d)
        self.addCleanup(os.chdir, os.path.dirname(self.d))
        job = app.start_background_scan(".", [], "r.html", runner=self.run_ok,
                                        spawn=self.fake_spawn, platform="win32")
        self.assertTrue(os.path.isabs(job["root"]))
        self.assertTrue(os.path.isabs(job["report"]))

    def test_an_old_status_file_is_gone_before_the_scan_starts(self):
        path = os.path.join(self.d, "r.html.status.json")
        with open(path, "w") as f:
            f.write('{"state": "finished"}')
        seen = []

        def spawn(cmd):
            seen.append(os.path.exists(path))
            return self.fake_spawn(cmd)
        app.start_background_scan(self.d, [], os.path.join(self.d, "r.html"),
                                  runner=self.run_ok, spawn=spawn, platform="win32")
        self.assertEqual(seen, [False])

    def test_a_report_another_live_scan_is_writing_is_refused(self):
        job = self.start()
        self.write_status(job)
        with self.assertRaises(app.BackgroundError):
            self.start()
        self.assertEqual(len(self.spawned), 1)

    def test_a_finished_scan_of_the_same_report_is_replaced(self):
        old = self.start()
        self.write_status(old, state="finished", report=old["report"])
        new = self.start()
        self.assertEqual([j["id"] for j in app.load_jobs()], [new["id"]])

    def test_two_scans_in_the_same_second_get_their_own_ids(self):
        a, b = self.start("a.html"), self.start("b.html")
        self.assertNotEqual(a["id"], b["id"])


class StartSystemd(JobCase):
    def runner(self, systemd_run=0, linger=(b"no", b"yes")):
        lingers = list(linger)

        def run(cmd, **kw):
            self.cmds.append(cmd)
            if cmd[:2] == ["systemctl", "--user"] and cmd[2] == "show-environment":
                return done(cmd)
            if cmd[0] == "systemd-run":
                return done(cmd, systemd_run)
            if cmd[:2] == ["loginctl", "show-user"]:
                return done(cmd, 0, lingers.pop(0) if len(lingers) > 1 else lingers[0])
            return done(cmd)
        return run

    def setUp(self):
        super().setUp()
        p = mock.patch.object(app.shutil, "which", lambda name: "/usr/bin/" + name)
        p.start()
        self.addCleanup(p.stop)

    def test_linux_runs_a_user_service_and_turns_on_linger(self):
        job = self.start(platform="linux", runner=self.runner())
        self.assertEqual(job["kind"], "systemd")
        self.assertEqual(job["unit"], "treerot-" + job["id"])
        self.assertEqual(job["logoff"], "keeps")
        run = next(c for c in self.cmds if c[0] == "systemd-run")
        self.assertEqual(run[:4], ["systemd-run", "--user", "--unit", job["unit"]])
        self.assertIn("--collect", run)
        worker = run[run.index("--") + 1:]
        self.assertEqual(worker[worker.index("--job-id") + 1], job["id"])
        self.assertIn(["loginctl", "enable-linger"], self.cmds)
        self.assertNotIn("sudo", [c[0] for c in self.cmds])
        self.assertEqual(self.spawned, [])

    def test_linger_already_on_is_left_alone(self):
        job = self.start(platform="linux", runner=self.runner(linger=(b"yes",)))
        self.assertEqual(job["logoff"], "keeps")
        self.assertNotIn(["loginctl", "enable-linger"], self.cmds)

    def test_linger_refused_means_the_scan_stops_at_logout_and_says_so(self):
        job = self.start(platform="linux", runner=self.runner(linger=(b"no",)))
        self.assertEqual(job["logoff"], "stops")
        self.assertIn("log out", app.logoff_text(job, "linux"))

    def test_systemd_refusing_falls_back_to_a_plain_process(self):
        job = self.start(platform="linux", runner=self.runner(systemd_run=1))
        self.assertEqual(job["kind"], "process")
        self.assertNotIn("unit", job)
        self.assertEqual(job["logoff"], "maybe")
        self.assertEqual(len(self.spawned), 1)
        self.assertEqual(app.load_jobs()[0]["kind"], "process")

    def test_no_user_manager_means_a_plain_process(self):
        def run(cmd, **kw):
            self.cmds.append(cmd)
            return done(cmd, 1)
        job = self.start(platform="linux", runner=run)
        self.assertEqual(job["kind"], "process")
        self.assertFalse(any(c[0] == "systemd-run" for c in self.cmds))

    def test_alive_and_end_ask_systemd_about_exactly_this_unit(self):
        job = self.start(platform="linux", runner=self.runner())
        states = {"state": b"active"}

        def run(cmd, **kw):
            self.cmds.append(cmd)
            if cmd[2] == "is-active":
                return done(cmd, 0, states["state"])
            if cmd[2] == "stop":
                states["state"] = b"inactive"
            return done(cmd)
        self.write_status(job)
        self.assertEqual(app.job_row(job, run=run)[0], "running")
        self.cmds = []
        app.end_job(job, runner=run)
        self.assertEqual(self.cmds, [["systemctl", "--user", "stop", job["unit"]]])
        self.assertEqual(app.job_row(app.load_jobs()[0], run=run)[0], "ended")

    def test_a_unit_name_outside_our_own_is_never_touched(self):
        job = self.start(platform="linux", runner=self.runner())
        for unit in ("ssh", "treerot-other", "treerot-" + job["id"] + ".service", ""):
            with self.subTest(unit=unit):
                self.cmds = []
                with self.assertRaises(app.BackgroundError):
                    app.end_job(dict(job, unit=unit), runner=self.run_ok)
                self.assertEqual(self.cmds, [])


class JobStates(JobCase):
    def test_missing_file_says_it_may_have_failed_not_finished(self):
        job = self.start()
        state, detail = app.job_state(job)
        self.assertEqual(state, "starting")
        self.assertIn("failed", detail.lower())
        self.assertNotIn("finished", detail.lower())

    def test_still_nothing_after_the_grace_period_is_said_plainly(self):
        job = self.start()
        job["started"] = time.time() - app.STARTING_GRACE_SECONDS - 1
        state, detail = app.job_state(job)
        self.assertEqual(state, "silent")
        self.assertIn("did not start", detail)

    def test_unreadable_status_is_not_finished(self):
        job = self.start()
        with open(job["status_file"], "w", encoding="utf-8") as f:
            f.write("{half")
        self.assertEqual(app.job_state(job)[0], "starting")

    def test_stale_uses_the_status_rule_and_says_it_seems_to_have_stopped(self):
        job = self.start()
        self.write_status(job, updated=time.time() - app.STATUS_STALE_SECONDS + 30)
        self.assertEqual(app.job_state(job)[0], "running")
        self.write_status(job, updated=time.time() - app.STATUS_STALE_SECONDS - 30)
        state, detail = app.job_state(job)
        self.assertEqual(state, "stalled")
        self.assertIn("seems to have stopped", detail)

    def test_running_shows_progress(self):
        job = self.start()
        self.write_status(job)
        self.assertEqual(app.job_state(job)[1].split(), ["5%", "c", "t"])

    def test_failed_shows_the_reason_and_old_failed_is_not_stale(self):
        job = self.start()
        self.write_status(job, state="failed", error="no share", updated=1)
        self.assertEqual(app.job_state(job), ("failed", "no share"))

    def test_odd_values_in_the_status_file_do_not_break_the_panel(self):
        job = self.start()
        self.write_status(job, percent=5, counts=None, times=["x"])
        self.assertEqual(app.job_state(job)[0], "running")
        self.write_status(job, state="failed", error=7)
        self.assertEqual(app.job_state(job)[0], "failed")

    def test_a_process_gone_while_running_is_stopped_by_logoff_or_restart(self):
        job = self.start()
        self.write_status(job)
        del self.procs[job["pid"]]                   # what logging off does to it
        state, detail = app.job_state(job)
        self.assertEqual(state, "stopped")
        self.assertIn("logged off", detail)
        self.assertIn("stopped", app.JOB_OVER)

    def test_a_process_gone_before_any_status_is_stopped_at_once(self):
        job = self.start()
        del self.procs[job["pid"]]
        self.assertEqual(app.job_state(job)[0], "stopped")

    def test_a_reused_pid_is_not_the_scan(self):
        job = self.start()
        self.write_status(job)
        self.procs[job["pid"]] = "someone else's program"
        self.assertEqual(app.job_state(job)[0], "stopped")

    def test_when_the_system_cannot_tell_the_status_file_decides(self):
        job = self.start()
        self.write_status(job)

        def unknown(pid, platform=None, run=None):
            raise OSError("ps did not answer")
        with mock.patch.object(app, "process_start", unknown):
            self.assertEqual(app.job_state(job)[0], "running")

    def test_finished_and_failed_win_over_a_process_that_is_gone(self):
        job = self.start()
        del self.procs[job["pid"]]
        self.write_status(job, state="failed", error="x")
        self.assertEqual(app.job_state(job)[0], "failed")

    def test_ended_scan_is_not_shown_as_stopped_by_itself(self):
        job = self.start()
        self.write_status(job, updated=time.time() - 3600)
        app.end_job(job)
        self.assertEqual(app.job_state(app.load_jobs()[0])[0], "ended")


class EndAndRemove(JobCase):
    def test_end_stops_exactly_the_process_that_was_started(self):
        job = self.start()
        app.end_job(job)
        self.assertEqual(self.stopped, [job["pid"]])
        record = app.load_jobs()[0]
        self.assertTrue(record["ended"])
        self.assertTrue(record["notified"])            # you ended it: no notice

    def test_end_failure_is_reported_and_not_recorded(self):
        job = self.start()

        def refuse(pid, start, platform=None):
            raise OSError("Access is denied")
        with mock.patch.object(app, "stop_process", refuse), self.assertRaises(app.BackgroundError) as c:
            app.end_job(job)
        self.assertIn("Access is denied", str(c.exception))
        self.assertFalse(app.load_jobs()[0].get("ended"))

    def test_remove_forgets_the_scan_and_keeps_report_and_status(self):
        job = self.start()
        self.write_status(job, state="finished", report=job["report"])
        with open(job["report"], "w") as f:
            f.write("x")
        app.remove_job(job)
        self.assertEqual(app.load_jobs(), [])
        self.assertTrue(os.path.exists(job["report"]))
        self.assertTrue(os.path.exists(job["status_file"]))

    def test_a_record_not_of_ours_is_never_acted_on(self):
        job = self.start()
        for name, bad in (("other id", dict(job, id="20200101-000000-abcd")),
                          ("path id", dict(job, id=os.path.join("..", "keep"))),
                          ("unit added", dict(job, unit="treerot-" + job["id"])),
                          ("task added", dict(job, task="TreeRot-" + job["id"]))):
            for fn in (app.end_job, app.remove_job):
                with self.subTest(name=name, fn=fn.__name__), self.assertRaises(app.BackgroundError):
                    fn(bad)
        self.assertEqual(self.stopped, [])
        self.assertEqual(len(app.load_jobs()), 1)

    def test_the_record_on_disk_decides_not_the_copy_in_memory(self):
        job = self.start()
        path = os.path.join(app.JOBS_DIR, job["id"] + ".json")
        with open(path, encoding="utf-8") as f:
            record = json.load(f)
        record["pid"] = 1
        with open(path, "w", encoding="utf-8") as f:
            json.dump(record, f)
        app.end_job(job)
        self.assertEqual(self.stopped, [1])           # the pid on disk, never the one passed in


class Records(JobCase):
    def test_load_jobs_skips_anything_that_is_not_our_record(self):
        job = self.start()
        for name, text in (("a.json", "{half"), ("b.json", "[1]"),
                           ("c.json", json.dumps(dict(job, kind="weird"))),
                           ("d.json", json.dumps(job)),        # the name does not match its id
                           ("e.json", json.dumps({"id": "e", "task": "TreeRot-e"})),
                           ("f.json", json.dumps(dict(job, id="f", pid="1")))):
            with open(os.path.join(app.JOBS_DIR, name), "w", encoding="utf-8") as f:
                f.write(text)
        self.assertEqual([j["id"] for j in app.load_jobs()], [job["id"]])

    def test_a_crafted_record_cannot_point_the_panel_at_another_file(self):
        job = self.start()
        evil = os.path.join(self.d, "evil.exe")
        for name, fields in (
                ("exe", {"report": evil, "status_file": evil + ".status.json"}),
                ("no extension", {"report": os.path.join(self.d, "r"),
                                  "status_file": os.path.join(self.d, "r.status.json")}),
                ("status elsewhere", {"status_file": os.path.join(self.d, "other.json")})):
            with self.subTest(name):
                app._save_job(dict(job, **fields))
                self.assertEqual(app.load_jobs(), [])
        for report in ("r.html", "r.HTML", "r.pdf", "r.Pdf"):
            with self.subTest(report):
                path = os.path.join(self.d, report)
                app._save_job(dict(job, report=path, status_file=path + ".status.json"))
                self.assertEqual(len(app.load_jobs()), 1)

    def test_record_files_are_replaced_whole(self):
        job = self.start()
        real = app.os.replace
        with mock.patch.object(app.os, "replace", side_effect=real) as rep:
            app._save_job(job)
        rep.assert_called_once()
        self.assertEqual(rep.call_args[0][1], os.path.join(app.JOBS_DIR, job["id"] + ".json"))
        self.assertEqual(sorted(os.listdir(app.JOBS_DIR)), [job["id"] + ".json"])

    def test_no_password_anywhere(self):
        self.start()
        for name in os.listdir(app.JOBS_DIR):
            with open(os.path.join(app.JOBS_DIR, name), encoding="utf-8") as f:
                self.assertNotIn("password", f.read().lower())


class JobReport(JobCase):
    def make_report(self, job):
        with open(job["report"], "w", encoding="utf-8") as f:
            f.write("<html>")

    def test_only_a_finished_scan_offers_its_report(self):
        job = self.start()
        self.make_report(job)
        self.assertIsNone(app.job_report(job))                # no status
        self.write_status(job, report=job["report"])
        self.assertIsNone(app.job_report(job))                # running, with the path in the file
        self.write_status(job, state="failed", report=job["report"])
        self.assertIsNone(app.job_report(job))
        self.write_status(job, state="finished", report=job["report"])
        self.assertEqual(app.job_report(job), job["report"])

    def test_the_file_must_exist(self):
        job = self.start()
        self.write_status(job, state="finished", report=job["report"])
        self.assertIsNone(app.job_report(job))
        state, detail = app.job_state(job)
        self.assertEqual(state, "finished")
        self.assertIn("not found", detail)

    def test_a_status_file_cannot_point_somewhere_else(self):
        # The status file sits next to the report, often on a share others can write to.
        job = self.start()
        other = os.path.join(self.d, "other.exe")
        open(other, "w").close()
        self.write_status(job, state="finished", report=other)
        self.assertIsNone(app.job_report(job))


class OldScheduledTasks(JobCase):
    """Records from the version that used scheduled tasks with a stored password: they still
    show, and Remove still deletes the task (and with it the password)."""

    def test_they_still_load_and_show_their_state(self):
        job = self.legacy()
        self.assertEqual(app.job_kind(app.load_jobs()[0]), "task")
        self.write_status(job, state="finished", report=job["report"])
        self.assertEqual(app.job_state(job)[0], "finished")

    def test_remove_deletes_exactly_this_task(self):
        job = self.legacy()
        app.remove_job(job, runner=self.run_ok)
        self.assertEqual(self.cmds, [[app.schtasks_exe(), "/Delete", "/TN", job["task"], "/F"]])
        self.assertEqual(app.load_jobs(), [])

    def test_remove_keeps_the_record_while_the_task_still_exists(self):
        job = self.legacy()
        with self.assertRaises(app.BackgroundError):
            app.remove_job(job, runner=refusing_scheduler)
        self.assertEqual(len(app.load_jobs()), 1)

    def test_end_uses_the_scheduler(self):
        job = self.legacy()
        app.end_job(job, runner=self.run_ok)
        self.assertEqual(self.cmds, [[app.schtasks_exe(), "/End", "/TN", job["task"]]])
        self.assertTrue(app.load_jobs()[0]["ended"])

    def test_a_task_name_outside_our_own_is_never_touched(self):
        job = self.legacy()
        for name in ("\\Microsoft\\Windows\\Defrag\\ScheduledDefrag", "TreeRot-other", "*", ""):
            for fn in (app.remove_job, app.end_job):
                with self.subTest(name=name, fn=fn.__name__):
                    self.cmds = []
                    with self.assertRaises(app.BackgroundError):
                        fn(dict(job, task=name), runner=self.run_ok)
                    self.assertEqual(self.cmds, [])

    def test_nothing_can_remove_one_during_its_password_prompt(self):
        job = self.legacy(creating=True)
        with self.assertRaises(app.BackgroundError):
            app.remove_job(job, runner=self.run_ok)
        self.assertEqual(self.cmds, [])

    def test_finished_tasks_are_deleted_at_launch_and_new_scans_are_left_alone(self):
        old = self.legacy()
        self.write_status(old, state="finished", report=old["report"])
        new = self.start()
        self.write_status(new, state="finished", report=new["report"])
        app.clean_finished_jobs(runner=self.run_ok)
        self.assertEqual(self.cmds, [[app.schtasks_exe(), "/Delete", "/TN", old["task"], "/F"]])
        self.assertEqual(len(app.load_jobs()), 2)

    def test_why_an_old_task_never_started_is_still_explained(self):
        job = self.legacy(started=time.time() - app.STARTING_GRACE_SECONDS - 1)
        line = ('"HOST","\\TreeRot-x","N/A","Ready","Interactive/Background","x",'
                '"-2147023511","DOM\\me","C:\\x.exe"\r\n')

        def runner(cmd, **kw):
            return done(cmd, 0, line.encode())
        state, detail, _ = app.job_panel_row(job, runner=runner)
        self.assertEqual(state, "silent")
        self.assertIn("log on as a batch job", detail)

    def test_new_scans_never_ask_the_scheduler(self):
        job = self.start()
        app._save_job(dict(job, started=time.time() - app.STARTING_GRACE_SECONDS - 1))

        def runner(cmd, **kw):
            raise AssertionError("asked the scheduler")
        self.assertEqual(app.job_panel_row(app.load_jobs()[0], runner=runner)[0], "silent")


class Notices(JobCase):
    def setUp(self):
        super().setUp()
        self.shown = []
        self.can_show = True
        p = mock.patch.object(app, "notify", self.fake_notify)
        p.start()
        self.addCleanup(p.stop)

    def fake_notify(self, title, body, platform=None, run=None):
        if self.can_show:
            self.shown.append((title, body))
        return self.can_show

    def test_finished_failed_and_stopped_each_say_so_once(self):
        cases = (("finished", {"state": "finished"}, "finished"),
                 ("failed", {"state": "failed", "error": "share gone"}, "share gone"),
                 ("stopped", None, "logged off"))
        for name, status, words in cases:
            with self.subTest(name):
                self.shown = []
                job = self.start(f"{name}.html")
                if status:
                    self.write_status(job, report=job["report"], **status)
                else:
                    self.write_status(job)
                    del self.procs[job["pid"]]
                self.assertTrue(app.notify_job(job))
                self.assertEqual(len(self.shown), 1)
                self.assertIn(job["root"], self.shown[0][1])
                self.assertIn(words, " ".join(self.shown[0]))
                record = [j for j in app.load_jobs() if j["id"] == job["id"]][0]
                self.assertTrue(app.notify_job(record))
                self.assertEqual(len(self.shown), 1)      # never twice

    def test_a_running_scan_is_not_reported(self):
        job = self.start()
        self.write_status(job)
        self.assertFalse(app.notify_job(job))
        self.assertEqual(self.shown, [])

    def test_a_scan_you_ended_needs_no_notice(self):
        job = self.start()
        app.end_job(job)
        self.assertTrue(app.notify_job(app.load_jobs()[0]))
        self.assertEqual(self.shown, [])

    def test_nobody_logged_in_keeps_it_for_the_next_login(self):
        job = self.start()
        self.write_status(job, state="finished", report=job["report"])
        self.can_show = False
        self.assertFalse(app.notify_job(job))
        self.assertFalse(app.load_jobs()[0]["notified"])
        self.assertIn(app.LOGIN_CHECK_NAME, WINDOWS_RUN_VALUES)
        self.can_show = True
        with mock.patch.object(app.sys, "platform", "win32"):
            app.login_check(delay=0, platform="win32")
        self.assertEqual(len(self.shown), 1)
        self.assertTrue(app.load_jobs()[0]["notified"])
        self.assertNotIn(app.LOGIN_CHECK_NAME, WINDOWS_RUN_VALUES)

    def test_the_scan_itself_reports_when_it_ends(self):
        job = self.start()
        self.write_status(job, state="finished", report=job["report"])
        app.finish_job_notice(job["id"], job["status_file"])
        self.assertEqual(len(self.shown), 1)

    def test_a_notice_for_another_status_file_is_ignored(self):
        job = self.start()
        self.write_status(job, state="finished", report=job["report"])
        app.finish_job_notice(job["id"], os.path.join(self.d, "other.status.json"))
        self.assertEqual(self.shown, [])

    def test_the_scan_never_fails_because_of_a_notice(self):
        job = self.start()
        with mock.patch.object(app, "notify_job", side_effect=RuntimeError("boom")):
            app.finish_job_notice(job["id"], job["status_file"])


class LoginCheck(JobCase):
    def test_installed_when_a_scan_starts_and_removed_once_all_are_reported(self):
        job = self.start(platform="win32")
        self.assertIn(app.LOGIN_CHECK_NAME, WINDOWS_RUN_VALUES)
        self.assertIn("--login-check", WINDOWS_RUN_VALUES[app.LOGIN_CHECK_NAME])
        with mock.patch.object(app.sys, "platform", "win32"):
            app.remove_job(job)
        self.assertNotIn(app.LOGIN_CHECK_NAME, WINDOWS_RUN_VALUES)

    def test_linux_uses_an_autostart_entry(self):
        path = os.path.join(app.AUTOSTART_DIR, "treerot-login-check.desktop")
        app.install_login_check("linux")
        with open(path, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("[Desktop Entry]", text)
        self.assertIn('"--login-check"', text)
        self.assertIn("NoDisplay=true", text)
        app.remove_login_check("linux")
        self.assertFalse(os.path.exists(path))
        app.remove_login_check("linux")                 # already gone is fine

    def test_macos_uses_a_launch_agent_of_the_user(self):
        path = os.path.join(app.LAUNCH_AGENTS_DIR, app.LOGIN_CHECK_LABEL + ".plist")
        app.install_login_check("darwin")
        with open(path, "rb") as f:
            plist = plistlib.load(f)
        self.assertTrue(plist["RunAtLoad"])
        self.assertEqual(plist["ProgramArguments"][-1], "--login-check")
        app.remove_login_check("darwin")
        self.assertFalse(os.path.exists(path))

    def test_desktop_exec_quoting(self):
        self.assertEqual(app._desktop_exec(["/opt/my app/treerot", "--login-check"]),
                         '"/opt/my app/treerot" "--login-check"')
        self.assertEqual(app._desktop_exec(['a"b$c`d\\e', "50%"]),
                         '"a\\\\"b\\\\$c\\\\`d\\\\\\\\e" "50%%"')

    def test_the_login_check_command_runs_without_a_window(self):
        with mock.patch.object(app, "login_check", return_value=0) as check:
            self.assertEqual(app.main(["--login-check"]), 0)
        check.assert_called_once()


class Notify(unittest.TestCase):
    """The real notify() with fake tools: what each system is asked to run."""

    def setUp(self):
        from tests import helpers
        self.notify = helpers.REAL_NOTIFY
        self.cmds = []

    def tool(self, rc=0, display=b"2"):
        def run(cmd, env=None, **kw):
            self.cmds.append((cmd, env))
            if cmd[0] == "loginctl":
                return done(cmd, 0, display)
            return done(cmd, rc)
        return run

    def test_text_is_passed_as_data_never_inside_a_script(self):
        evil = "'; Remove-Item C:\\ -Recurse; \" $(x) `y`"
        self.notify("t", evil, platform="win32", run=self.tool())
        cmd, env = self.cmds[0]
        self.assertTrue(cmd[0].lower().endswith("powershell.exe"))
        self.assertNotIn(evil, " ".join(cmd))
        self.assertEqual(env["TREEROT_BODY"], evil)
        self.cmds = []
        self.notify("t", evil, platform="darwin", run=self.tool())
        cmd = self.cmds[0][0]
        self.assertEqual(cmd[0], "osascript")
        self.assertEqual(cmd[-1], evil)
        self.assertNotIn(evil, " ".join(cmd[:-1]))

    def test_linux_needs_a_desktop_session(self):
        with mock.patch.object(app.shutil, "which", lambda name: "/usr/bin/" + name):
            self.assertTrue(self.notify("t", "b", platform="linux", run=self.tool()))
            self.assertEqual(self.cmds[-1][0][:3], ["notify-send", "--app-name", app.APP_NAME])
            self.cmds = []
            self.assertFalse(self.notify("t", "b", platform="linux", run=self.tool(display=b"")))
            self.assertFalse(any(c[0] == "notify-send" for c, _ in self.cmds))

    def test_a_tool_that_fails_means_not_shown(self):
        with mock.patch.object(app.shutil, "which", lambda name: "/usr/bin/" + name):
            self.assertFalse(self.notify("t", "b", platform="linux", run=self.tool(rc=1)))
        self.assertFalse(self.notify("t", "b", platform="darwin", run=self.tool(rc=1)))


@unittest.skipUnless(sys.platform.startswith("linux"), "reads /proc")
class ProcessIdentity(unittest.TestCase):
    def test_this_process_has_a_start_and_a_missing_one_has_none(self):
        start = app.process_start(os.getpid())
        self.assertTrue(start)
        self.assertEqual(app.process_start(os.getpid()), start)
        self.assertIsNone(app.process_start(2 ** 22 + 12345))
        self.assertIsNone(app.process_start(0))
        self.assertIsNone(app.process_start(True))

    def test_stop_refuses_a_process_that_is_not_the_one_started(self):
        with mock.patch.object(app.os, "killpg") as kill:
            self.assertFalse(app.stop_process(os.getpid(), "not its start time"))
            self.assertFalse(app.stop_process(os.getpid(), None))
        kill.assert_not_called()


class WholeCommand(JobCase):
    def test_the_real_worker_scans_finishes_and_is_followed(self):
        """Everything but the detached launch: this runs the exact worker command line on a
        folder with spaces and non-English letters, and follows it the way the panel does."""
        root = os.path.join(self.d, "שיתוף עם רווח & co")
        os.makedirs(os.path.join(root, "keep"))
        os.makedirs(os.path.join(root, "-skip me"))
        with open(os.path.join(root, "-skip me", "f.txt"), "w") as f:
            f.write("x")
        out = os.path.join(self.d, "דוח & co")
        os.makedirs(out)
        csv_out = os.path.join(out, "rows.csv")
        args = app.background_args("2024-01-01", "", ["-skip me"], created=False) + ["-o", csv_out]
        job = app.start_background_scan(root, args, os.path.join(out, "r.html"),
                                        runner=self.run_ok, spawn=self.fake_spawn, platform="win32")
        env = dict(os.environ, HOME=self.d, USERPROFILE=self.d,   # no real settings or jobs
                   XDG_CONFIG_HOME=os.path.join(self.d, "config"))
        res = subprocess.run(self.spawned[0], env=env, capture_output=True, timeout=120)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(app.job_state(job)[0], "finished")
        self.assertEqual(app.job_report(job), job["report"])
        with open(csv_out, encoding="utf-8-sig") as f:
            self.assertIn("1 folder(s) excluded", f.read())


if __name__ == "__main__":
    unittest.main()
