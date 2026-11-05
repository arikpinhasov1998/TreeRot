import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import xml.etree.ElementTree as ET
from unittest import mock

from tests.helpers import app

NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}


def windows_argv(line):
    """Splits a command line by the rules Windows programs use (CommandLineToArgvW)."""
    args, cur, i, in_quotes, have = [], [], 0, False, False
    while i < len(line):
        c = line[i]
        if c == "\\":
            n = 0
            while i < len(line) and line[i] == "\\":
                n += 1
                i += 1
            if i < len(line) and line[i] == '"':
                cur.append("\\" * (n // 2))
                have = True
                if n % 2:
                    cur.append('"')
                    i += 1
            else:
                cur.append("\\" * n)
                have = True
            continue
        if c == '"':
            in_quotes = not in_quotes
            have = True
        elif c in " \t" and not in_quotes:
            if have or cur:
                args.append("".join(cur))
            cur, have = [], False
        else:
            cur.append(c)
            have = True
        i += 1
    if have or cur:
        args.append("".join(cur))
    return args


class Mapped(unittest.TestCase):
    def test_network_drive_letter_is_mapped(self):
        self.assertTrue(app.is_mapped_drive("Z:\\data", drive_type=lambda d: 4))

    def test_local_drive_and_unc_are_not(self):
        self.assertFalse(app.is_mapped_drive("C:\\data", drive_type=lambda d: 3))
        self.assertFalse(app.is_mapped_drive("\\\\srv\\share", drive_type=lambda d: 4))
        self.assertFalse(app.is_mapped_drive("/srv/share", drive_type=lambda d: 4))

    def test_forward_slashes_and_long_path_prefix_are_still_mapped(self):
        self.assertTrue(app.is_mapped_drive("Z:/data/r.html", drive_type=lambda d: 4))
        self.assertTrue(app.is_mapped_drive("\\\\?\\Z:\\data", drive_type=lambda d: 4))
        self.assertFalse(app.is_mapped_drive("\\\\?\\UNC\\srv\\s", drive_type=lambda d: 4))

    def test_asks_windows_about_the_drive_root(self):
        seen = []
        app.is_mapped_drive("z:\\data", drive_type=lambda d: seen.append(d) or 3)
        self.assertEqual(seen, ["Z:\\"])

    @unittest.skipIf(sys.platform == "win32", "elsewhere there are no drive letters")
    def test_without_windows_nothing_is_mapped(self):
        self.assertFalse(app.is_mapped_drive("Z:\\data"))


class Xml(unittest.TestCase):
    def test_runs_when_logged_off_with_no_time_limit(self):
        root = ET.fromstring(app.build_task_xml("C:\\T\\TreeRot-cli.exe",
                                                ["\\\\srv\\שיתוף", "--from", "2024-01-01"],
                                                "DOM\\me"))
        self.assertEqual(root.find("t:Principals/t:Principal/t:UserId", NS).text, "DOM\\me")
        self.assertEqual(root.find("t:Principals/t:Principal/t:LogonType", NS).text, "Password")
        self.assertEqual(root.find("t:Settings/t:ExecutionTimeLimit", NS).text, "PT0S")
        self.assertEqual(root.find("t:Settings/t:DisallowStartIfOnBatteries", NS).text, "false")
        self.assertEqual(root.find("t:Actions/t:Exec/t:Command", NS).text, "C:\\T\\TreeRot-cli.exe")
        self.assertIn("שיתוף", root.find("t:Actions/t:Exec/t:Arguments", NS).text)

    def test_special_characters_are_escaped(self):
        ET.fromstring(app.build_task_xml("x.exe", ["a&b<c>"], "me"))

    def test_every_value_survives_the_xml_and_the_command_line(self):
        nasty = ["\\\\srv\\שיתוף עם רווח\\", "a&b<c>", 'he said "hi"', "it's", "]]>", "&amp;",
                 "C:\\Program Files\\x\\", "trailing\\\\", "", "tab\there", "100%", "*.tmp",
                 "{braces}", "emoji \U0001F600"]
        for value in nasty:
            with self.subTest(value=value):
                root = ET.fromstring(app.build_task_xml(
                    "C:\\Program Files & Co\\<T>\\TreeRot-cli.exe", ["--exclude", value], "D&M\\m<e"))
                self.assertEqual(root.find("t:Actions/t:Exec/t:Command", NS).text,
                                 "C:\\Program Files & Co\\<T>\\TreeRot-cli.exe")
                self.assertEqual(root.find("t:Principals/t:Principal/t:UserId", NS).text, "D&M\\m<e")
                line = root.find("t:Actions/t:Exec/t:Arguments", NS).text
                self.assertEqual(windows_argv(line), ["--exclude", value])

    def test_a_value_xml_cannot_carry_is_refused_not_changed(self):
        for value in ("a\x01b", "a\nb", "a\rb", "a\ud800b"):
            with self.subTest(value=value), self.assertRaises(app.BackgroundError):
                app.build_task_xml("x.exe", ["--exclude", value], "me")

    def test_no_trigger_so_no_start_time_can_pass_while_the_password_is_typed(self):
        root = ET.fromstring(app.build_task_xml("x.exe", [], "me"))
        self.assertIsNone(root.find("t:Triggers", NS))
        self.assertEqual(root.find("t:Settings/t:AllowStartOnDemand", NS).text, "true")
        self.assertEqual(root.find("t:Settings/t:Enabled", NS).text, "true")

    def test_logon_type_can_be_chosen_for_the_build_machine(self):
        root = ET.fromstring(app.build_task_xml("x.exe", [], "me", logon_type="S4U"))
        self.assertEqual(root.find("t:Principals/t:Principal/t:LogonType", NS).text, "S4U")

    def test_has_no_place_for_a_password(self):
        text = app.build_task_xml("x.exe", ["a"], "me")
        root = ET.fromstring(text)
        tags = [e.tag.split("}")[1].lower() for e in root.iter()]
        self.assertFalse([t for t in tags if "password" in t])

    def test_written_as_utf16_it_is_still_valid(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "t.xml")
            app.write_task_xml(p, app.build_task_xml("x.exe", ["\\\\srv\\שיתוף&"], "me"))
            with open(p, "rb") as f:
                raw = f.read()
            self.assertIn(raw[:2], (b"\xff\xfe", b"\xfe\xff"))
            self.assertIn("שיתוף&", ET.fromstring(raw).find("t:Actions/t:Exec/t:Arguments", NS).text)


class Command(unittest.TestCase):
    def test_from_source_runs_this_script_with_python(self):
        exe, args = app.background_command("\\\\srv\\s", ["--from", "2024-01-01"], "C:\\s.json")
        self.assertEqual(exe, sys.executable)
        self.assertEqual(os.path.basename(args[0]), os.path.basename(app.__file__))
        self.assertTrue(os.path.isabs(args[0]))
        self.assertEqual(args[1:], ["\\\\srv\\s", "--from", "2024-01-01",
                                    "--progress", "none", "--status-file", "C:\\s.json"])

    def test_from_source_refuses_when_python_cannot_be_found(self):
        with mock.patch.object(app.sys, "executable", ""), self.assertRaises(app.BackgroundError):
            app.background_command("\\\\srv\\s", [], "s.json")

    def test_frozen_uses_the_cli_next_to_the_window_exe(self):
        with tempfile.TemporaryDirectory() as d:
            cli = os.path.join(d, "TreeRot-cli.exe")
            open(cli, "w").close()
            with mock.patch.object(app.sys, "frozen", True, create=True), \
                    mock.patch.object(app.sys, "executable", os.path.join(d, "TreeRot.exe")):
                exe, args = app.background_command("\\\\srv\\s", [], "s.json")
            self.assertEqual(exe, cli)
            self.assertEqual(args[0], "\\\\srv\\s")

    def test_frozen_without_the_cli_is_refused_by_name(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(app.sys, "frozen", True, create=True), \
                    mock.patch.object(app.sys, "executable", os.path.join(d, "TreeRot.exe")), \
                    self.assertRaises(app.BackgroundError) as c:
                app.background_command("\\\\srv\\s", [], "s.json")
            self.assertIn("TreeRot-cli.exe", str(c.exception))

    def test_schtasks_is_named_in_full_on_windows(self):
        # A schtasks.exe dropped in the current folder must never be the one given the console.
        path = app.schtasks_exe(platform="win32", environ={"SystemRoot": "D:\\Win"})
        self.assertEqual(path, "D:\\Win\\System32\\schtasks.exe")
        self.assertEqual(app.schtasks_exe(platform="win32", environ={}),
                         "C:\\Windows\\System32\\schtasks.exe")


class Arguments(unittest.TestCase):
    def test_every_setting_reaches_the_scan(self):
        args = app.background_args("2024-01-01", "2024-12-31", ["a"], created=False,
                                   follow_symlinks=True, precount=True)
        a = app.build_parser().parse_args(["x"] + args)
        self.assertEqual(a.date_from.strftime("%Y-%m-%d"), "2024-01-01")
        self.assertEqual(a.date_to.strftime("%Y-%m-%d"), "2024-12-31")
        self.assertEqual(a.exclude, ["a"])
        self.assertEqual(a.created, "off")
        self.assertTrue(a.follow_symlinks)
        self.assertTrue(a.precount)
        self.assertTrue(a.quiet)

    def test_optional_settings_stay_out_when_off(self):
        args = app.background_args("", "2024-12-31", [], created=True,
                                   follow_symlinks=False, precount=False)
        a = app.build_parser().parse_args(["x"] + args)
        self.assertIsNone(a.date_from)
        self.assertIsNone(a.exclude)
        self.assertEqual(a.created, "auto")
        self.assertFalse(a.follow_symlinks)
        self.assertFalse(a.precount)

    def test_exclusions_reach_the_scan_unchanged(self):
        excludes = ["-starts-with-dash", "--from", "a=b", "with space", "שיתוף", 'q"uote', "a&b<c>",
                    "*.tmp", "\\\\srv\\s\\old\\", "it's", " padded "]
        args = app.background_args("2024-01-01", "", excludes, created=True,
                                   follow_symlinks=False, precount=False)
        root = ET.fromstring(app.build_task_xml("x.exe", ["\\\\srv\\s"] + args, "me"))
        argv = windows_argv(root.find("t:Actions/t:Exec/t:Arguments", NS).text)
        a = app.build_parser().parse_args(argv)
        self.assertEqual(a.exclude, excludes)
        self.assertEqual(a.path, "\\\\srv\\s")


class FolderCheck(unittest.TestCase):
    def test_mapped_missing_and_good_folders(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(app.check_background_folder(d))
            self.assertIn("not reachable", app.check_background_folder(os.path.join(d, "no")))
            with mock.patch.object(app, "is_mapped_drive", return_value=True):
                self.assertIn("\\\\server\\share", app.check_background_folder(d))


class Consoles(unittest.TestCase):
    """How schtasks is started. subprocess.run is replaced: it never really runs."""

    def test_password_console_is_real_and_nothing_captures_it(self):
        with mock.patch.object(app.subprocess, "run") as run, \
                mock.patch.object(app.sys, "platform", "win32"):
            app._console_run(["schtasks", "/RP", "*"])
        kw = run.call_args[1]
        self.assertEqual(kw.get("creationflags"), 0x00000010)     # CREATE_NEW_CONSOLE
        for key in ("stdin", "stdout", "stderr", "input", "capture_output", "env", "text"):
            self.assertNotIn(key, kw)

    def test_quiet_run_cannot_hang_and_shows_no_window(self):
        with mock.patch.object(app.subprocess, "run") as run, \
                mock.patch.object(app.sys, "platform", "win32"):
            app._quiet_run(["schtasks", "/Query"])
        kw = run.call_args[1]
        self.assertEqual(kw.get("creationflags"), 0x08000000)     # CREATE_NO_WINDOW
        self.assertEqual(kw.get("stdin"), subprocess.DEVNULL)
        self.assertTrue(kw.get("timeout"))

    def test_a_schtasks_that_does_not_answer_is_a_failure(self):
        def slow(cmd, **kw):
            raise subprocess.TimeoutExpired(cmd, 1)
        with mock.patch.object(app.subprocess, "run", slow), \
                mock.patch.object(app.sys, "platform", "win32"):
            self.assertNotEqual(app._quiet_run(["schtasks"]).returncode, 0)

    def test_neither_runs_outside_windows(self):
        with mock.patch.object(app.subprocess, "run") as run, \
                mock.patch.object(app.sys, "platform", "darwin"):
            with self.assertRaises(app.BackgroundError):
                app._console_run(["schtasks"])
            with self.assertRaises(app.BackgroundError):
                app._quiet_run(["schtasks"])
        run.assert_not_called()


class JobCase(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.d = d.name
        p = mock.patch.object(app, "JOBS_DIR", os.path.join(d.name, "jobs"))
        p.start()
        self.addCleanup(p.stop)
        e = mock.patch.dict(os.environ, {"USERNAME": "me", "USERDOMAIN": "DOM"})
        e.start()
        self.addCleanup(e.stop)
        self.cmds = []

    def run_ok(self, cmd, **kw):
        self.cmds.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    def start(self, report="r.html", args=("--from", "2024-01-01")):
        self.cmds = []
        return app.start_background_scan("\\\\srv\\s", list(args),
                                         os.path.join(self.d, report), runner=self.run_ok)

    def write_status(self, job, **fields):
        data = {"state": "running", "percent": "5%", "counts": "c", "times": "t",
                "updated": time.time(), "report": None, "error": ""}
        data.update(fields)
        with open(job["status_file"], "w", encoding="utf-8") as f:
            json.dump(data, f)


class Jobs(JobCase):
    def test_password_is_prompted_by_windows_and_task_started(self):
        job = self.start()
        create = self.cmds[0]
        self.assertEqual(create[create.index("/RP") + 1], "*")
        self.assertIn("/XML", create)
        self.assertIn("/Run", self.cmds[1])
        self.assertEqual(app.load_jobs()[0]["task"], job["task"])

    def test_no_password_in_job_record(self):
        self.start()
        names = os.listdir(app.JOBS_DIR)
        for n in names:
            if n.endswith(".json"):
                with open(os.path.join(app.JOBS_DIR, n), encoding="utf-8") as f:
                    self.assertNotIn("password", f.read().lower())

    def test_create_failure_raises_with_windows_message(self):
        def fail(cmd, **kw):
            return subprocess.CompletedProcess(cmd, 1, b"", b"Access is denied.")
        with self.assertRaises(app.BackgroundError) as c:
            app.start_background_scan("\\\\srv\\s", [], os.path.join(self.d, "r.html"), runner=fail)
        self.assertIn("could not be created", str(c.exception))
        self.assertEqual(app.load_jobs(), [])

    def test_states(self):
        job = self.start()
        self.assertEqual(app.job_state(job)[0], "starting")
        self.write_status(job)
        self.assertEqual(app.job_state(job)[0], "running")
        self.write_status(job, updated=time.time() - 3600)
        self.assertEqual(app.job_state(job)[0], "stalled")
        self.write_status(job, state="finished", report="r", percent="")
        self.assertEqual(app.job_state(job)[0], "finished")

    def test_remove_deletes_task_and_record(self):
        job = self.start()
        self.cmds = []
        app.remove_job(job, runner=self.run_ok)
        self.assertIn("/Delete", self.cmds[0])
        self.assertEqual(app.load_jobs(), [])

    # ---- the password

    def test_create_has_the_prompt_and_never_a_password_anywhere(self):
        with mock.patch.dict(os.environ, {"TREEROT_SECRET_PROBE": "x"}):
            self.start()
        create = self.cmds[0]
        self.assertEqual(sum(a == "/RP" for a in create), 1)
        self.assertEqual(create[create.index("/RU") + 1], "DOM\\me")
        self.assertEqual(create[create.index("/TN") + 1], app.load_jobs()[0]["task"])
        self.assertNotIn("/F", create)         # a name collision may never overwrite a task

    def test_runner_gets_no_input_or_pipes(self):
        seen = []

        def runner(cmd, **kw):
            seen.append(kw)
            return subprocess.CompletedProcess(cmd, 0, b"", b"")
        app.start_background_scan("\\\\srv\\s", [], os.path.join(self.d, "r.html"), runner=runner)
        self.assertEqual(seen[0], {})

    def test_task_xml_is_passed_by_file_and_then_removed(self):
        seen = {}

        def runner(cmd, **kw):
            if "/XML" in cmd:
                with open(cmd[cmd.index("/XML") + 1], "rb") as f:
                    seen["xml"] = f.read()
            return subprocess.CompletedProcess(cmd, 0, b"", b"")
        job = app.start_background_scan("\\\\srv\\s", [], os.path.join(self.d, "r.html"), runner=runner)
        root = ET.fromstring(seen["xml"])
        argv = windows_argv(root.find("t:Actions/t:Exec/t:Arguments", NS).text)
        self.assertIn("\\\\srv\\s", argv)
        self.assertEqual(argv[argv.index("--status-file") + 1], job["status_file"])
        self.assertEqual(argv[argv.index("--report") + 1], job["report"])
        self.assertEqual([n for n in os.listdir(app.JOBS_DIR) if not n.endswith(".json")], [])

    def test_no_user_name_is_refused_before_any_prompt(self):
        with mock.patch.dict(os.environ, {"USERNAME": ""}), self.assertRaises(app.BackgroundError):
            self.start()
        self.assertEqual(self.cmds, [])

    def test_local_account_without_a_domain(self):
        env = {k: v for k, v in os.environ.items() if k != "USERDOMAIN"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.start()
        create = self.cmds[0]
        self.assertEqual(create[create.index("/RU") + 1], "me")

    # ---- paths

    def test_mapped_drives_are_refused_for_folder_and_report(self):
        def is_mapped(path, drive_type=None):
            return path.startswith("Z:")
        with mock.patch.object(app, "is_mapped_drive", is_mapped):
            for root, report in (("Z:\\data", os.path.join(self.d, "r.html")),
                                 ("\\\\srv\\s", "Z:\\out\\r.html")):
                with self.subTest(root=root, report=report), \
                        self.assertRaises(app.BackgroundError) as c:
                    app.start_background_scan(root, [], report, runner=self.run_ok)
                self.assertIn("\\\\server\\share", str(c.exception))
        self.assertEqual(self.cmds, [])
        self.assertEqual(app.load_jobs(), [])

    def test_relative_paths_become_full_ones(self):
        cwd = os.getcwd()
        os.chdir(self.d)
        self.addCleanup(os.chdir, cwd)
        job = app.start_background_scan("data", [], "r.html", runner=self.run_ok)
        self.assertTrue(os.path.isabs(job["root"]))
        self.assertTrue(os.path.isabs(job["report"]))
        self.assertTrue(os.path.isabs(job["status_file"]))

    def test_report_folder_that_does_not_exist_is_refused(self):
        with self.assertRaises(app.BackgroundError):
            app.start_background_scan("\\\\srv\\s", [], os.path.join(self.d, "no", "r.html"),
                                      runner=self.run_ok)
        self.assertEqual(self.cmds, [])

    def test_tasks_sit_in_the_root_of_task_scheduler(self):
        # A standard user may not be allowed to create a task folder.
        job = self.start()
        self.assertEqual(job["task"], "TreeRot-" + job["id"])
        self.assertNotIn("\\", job["task"])

    def test_two_jobs_in_the_same_second_get_their_own_task(self):
        a, b = self.start("a.html"), self.start("b.html")
        self.assertNotEqual(a["task"], b["task"])
        self.assertEqual(len(app.load_jobs()), 2)

    # ---- an old status file must not pass for this run's result

    def test_old_status_is_removed_before_the_task_is_created(self):
        status = os.path.join(self.d, "r.html.status.json")
        with open(status, "w", encoding="utf-8") as f:
            json.dump({"state": "finished", "updated": 1, "report": "old", "error": ""}, f)
        present = []

        def runner(cmd, **kw):
            present.append(os.path.exists(status))
            return subprocess.CompletedProcess(cmd, 0, b"", b"")
        job = app.start_background_scan("\\\\srv\\s", [], os.path.join(self.d, "r.html"), runner=runner)
        self.assertEqual(present, [False, False])
        self.assertEqual(app.job_state(job)[0], "starting")

    def test_an_old_status_that_cannot_be_removed_stops_everything(self):
        status = os.path.join(self.d, "r.html.status.json")
        open(status, "w").close()
        with mock.patch.object(app.os, "remove", side_effect=PermissionError("in use")), \
                self.assertRaises(app.BackgroundError) as c:
            self.start()
        self.assertIn(status, str(c.exception))
        self.assertIn("in use", str(c.exception))
        self.assertEqual(self.cmds, [])
        self.assertEqual(app.load_jobs(), [])

    def test_a_live_scan_with_the_same_report_is_not_disturbed(self):
        first = self.start()
        self.write_status(first)
        with self.assertRaises(app.BackgroundError):
            self.start()
        self.assertEqual(self.cmds, [])
        self.assertEqual(app.read_status(first["status_file"])["state"], "running")

    def test_a_new_scan_replaces_an_earlier_finished_one_with_the_same_report(self):
        first = self.start()
        self.write_status(first, state="finished", report=first["report"])
        second = self.start()
        self.assertEqual([j["id"] for j in app.load_jobs()], [second["id"]])
        self.assertEqual(self.cmds[0][:4], [app.schtasks_exe(), "/Delete", "/TN", first["task"]])

    # ---- when the steps fail

    def test_run_failure_removes_task_and_record(self):
        cmds = []

        def runner(cmd, **kw):
            cmds.append(cmd)
            return subprocess.CompletedProcess(cmd, 1 if "/Run" in cmd else 0, b"", b"")
        with self.assertRaises(app.BackgroundError):
            app.start_background_scan("\\\\srv\\s", [], os.path.join(self.d, "r.html"), runner=runner)
        self.assertIn("/Delete", cmds[-1])
        self.assertEqual(app.load_jobs(), [])
        self.assertEqual(os.listdir(app.JOBS_DIR), [])

    def test_run_failure_keeps_the_record_if_the_task_could_not_be_removed(self):
        def runner(cmd, **kw):
            ok = "/Create" in cmd or "/Query" in cmd
            return subprocess.CompletedProcess(cmd, 0 if ok else 1, b"", b"Access is denied.")
        with self.assertRaises(app.BackgroundError) as c:
            app.start_background_scan("\\\\srv\\s", [], os.path.join(self.d, "r.html"), runner=runner)
        self.assertIn("Background scans", str(c.exception))
        self.assertEqual(len(app.load_jobs()), 1)

    def test_missing_schtasks_leaves_no_record(self):
        def runner(cmd, **kw):
            raise FileNotFoundError("schtasks")
        with self.assertRaises(OSError):
            app.start_background_scan("\\\\srv\\s", [], os.path.join(self.d, "r.html"), runner=runner)
        self.assertEqual(app.load_jobs(), [])

    def test_record_that_cannot_be_written_stops_before_the_prompt(self):
        with mock.patch.object(app, "_save_job", side_effect=OSError("disk full")), \
                self.assertRaises(OSError):
            self.start()
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

    def test_ended_scan_is_not_shown_as_stopped_by_itself(self):
        job = self.start()
        self.write_status(job, updated=time.time() - 3600)
        app.end_job(job, runner=self.run_ok)
        self.assertEqual(app.job_state(app.load_jobs()[0])[0], "ended")


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

    def test_finished_with_no_report_is_not_replaced_by_an_old_file(self):
        job = self.start()
        self.make_report(job)
        self.write_status(job, state="finished", report=None)
        self.assertIsNone(app.job_report(job))

    def test_a_status_file_cannot_point_somewhere_else(self):
        # The status file sits next to the report, often on a share others can write to.
        job = self.start()
        other = os.path.join(self.d, "other.exe")
        open(other, "w").close()
        self.write_status(job, state="finished", report=other)
        self.assertIsNone(app.job_report(job))


class OnlyOurTasks(JobCase):
    def schtasks_calls(self, fn, job):
        self.cmds = []
        with self.assertRaises(app.BackgroundError):
            fn(job, runner=self.run_ok)
        self.assertEqual(self.cmds, [])

    def test_a_task_name_outside_our_own_is_never_touched(self):
        job = self.start()
        for name in ("\\Microsoft\\Windows\\Defrag\\ScheduledDefrag", "TreeRot-other", "*",
                     "TreeRot-" + job["id"] + "x", "treerot-" + job["id"], "",
                     "\\TreeRot-" + job["id"], "TreeRot\\scan-" + job["id"]):
            bad = dict(job, task=name)
            for fn in (app.remove_job, app.end_job):
                with self.subTest(name=name, fn=fn.__name__):
                    self.schtasks_calls(fn, bad)
        self.assertEqual(len(app.load_jobs()), 1)

    def test_a_well_formed_name_with_no_record_of_ours_is_never_touched(self):
        job = self.start()
        other = dict(job, id="20200101-000000-abcd", task="TreeRot-20200101-000000-abcd")
        self.schtasks_calls(app.remove_job, other)
        self.schtasks_calls(app.end_job, other)

    def test_the_record_on_disk_decides_not_the_copy_in_memory(self):
        job = self.start()
        path = os.path.join(app.JOBS_DIR, job["id"] + ".json")
        with open(path, encoding="utf-8") as f:
            record = json.load(f)
        record["task"] = "TreeRot-20200101-000000-abcd"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(record, f)
        self.schtasks_calls(app.remove_job, job)

    def test_ids_cannot_reach_outside_the_jobs_folder(self):
        job = self.start()
        outside = os.path.join(self.d, "keep.json")
        open(outside, "w").close()
        bad = dict(job, id=os.path.join("..", "keep"), task="TreeRot-../keep")
        self.schtasks_calls(app.remove_job, bad)
        self.assertTrue(os.path.exists(outside))

    def test_load_jobs_skips_anything_that_is_not_our_record(self):
        job = self.start()
        os.makedirs(app.JOBS_DIR, exist_ok=True)
        for name, text in (("a.json", "{half"), ("b.json", "[1]"),
                           ("c.json", json.dumps(dict(job, task="\\Microsoft\\x"))),
                           ("d.json", json.dumps(job)),        # the name does not match its id
                           ("e.json", json.dumps({"id": "e", "task": "TreeRot-e"}))):
            with open(os.path.join(app.JOBS_DIR, name), "w", encoding="utf-8") as f:
                f.write(text)
        self.assertEqual([j["id"] for j in app.load_jobs()], [job["id"]])

    def test_end_asks_for_exactly_this_task_and_records_it(self):
        job = self.start()
        self.cmds = []
        app.end_job(job, runner=self.run_ok)
        self.assertEqual(self.cmds, [[app.schtasks_exe(), "/End", "/TN", job["task"]]])
        self.assertTrue(app.load_jobs()[0]["ended"])

    def test_end_failure_is_reported_and_not_recorded(self):
        job = self.start()

        def fail(cmd, **kw):
            return subprocess.CompletedProcess(cmd, 1, b"", b"Access is denied.")
        with self.assertRaises(app.BackgroundError) as c:
            app.end_job(job, runner=fail)
        self.assertIn("Access is denied.", str(c.exception))
        self.assertFalse(app.load_jobs()[0].get("ended"))

    def test_remove_keeps_the_record_while_the_task_still_exists(self):
        job = self.start()

        def fail(cmd, **kw):
            return subprocess.CompletedProcess(cmd, 0 if "/Query" in cmd else 1, b"", b"Access is denied.")
        with self.assertRaises(app.BackgroundError) as c:
            app.remove_job(job, runner=fail)
        self.assertIn("Access is denied.", str(c.exception))
        self.assertEqual(len(app.load_jobs()), 1)

    def test_remove_forgets_a_task_someone_already_deleted(self):
        job = self.start()

        def gone(cmd, **kw):
            return subprocess.CompletedProcess(cmd, 1, b"", b"not found")
        app.remove_job(job, runner=gone)
        self.assertEqual(app.load_jobs(), [])

    def test_remove_leaves_report_and_status(self):
        job = self.start()
        self.write_status(job, state="finished", report=job["report"])
        with open(job["report"], "w") as f:
            f.write("x")
        app.remove_job(job, runner=self.run_ok)
        self.assertTrue(os.path.exists(job["report"]))
        self.assertTrue(os.path.exists(job["status_file"]))


class Cleanup(JobCase):
    def test_final_tasks_are_deleted_and_the_record_stays(self):
        done, bad, live = self.start("a.html"), self.start("b.html"), self.start("c.html")
        self.write_status(done, state="finished", report=done["report"])
        self.write_status(bad, state="failed", error="x")
        self.write_status(live)
        self.cmds = []
        app.clean_finished_jobs(runner=self.run_ok)
        self.assertEqual(sorted(c[3] for c in self.cmds), sorted([done["task"], bad["task"]]))
        self.assertTrue(all(c[1] == "/Delete" for c in self.cmds))
        jobs = {j["id"]: j for j in app.load_jobs()}
        self.assertEqual(len(jobs), 3)
        self.assertTrue(jobs[done["id"]]["task_removed"])
        self.assertFalse(jobs[live["id"]].get("task_removed"))
        self.cmds = []
        app.clean_finished_jobs(runner=self.run_ok)      # the next launch has nothing to do
        self.assertEqual(self.cmds, [])
        app.remove_job(jobs[done["id"]], runner=self.run_ok)
        self.assertEqual(self.cmds, [])                  # nor does Remove
        self.assertEqual(len(app.load_jobs()), 2)

    def test_a_task_that_could_not_be_deleted_is_tried_again(self):
        job = self.start()
        self.write_status(job, state="finished", report=job["report"])

        def fail(cmd, **kw):
            return subprocess.CompletedProcess(cmd, 0 if "/Query" in cmd else 1, b"", b"denied")
        app.clean_finished_jobs(runner=fail)
        self.assertFalse(app.load_jobs()[0].get("task_removed"))

    def test_record_files_are_replaced_whole(self):
        job = self.start()
        real = app.os.replace
        with mock.patch.object(app.os, "replace", side_effect=real) as rep:
            app._save_job(job)
        rep.assert_called_once()
        self.assertEqual(rep.call_args[0][1], os.path.join(app.JOBS_DIR, job["id"] + ".json"))
        self.assertEqual(sorted(os.listdir(app.JOBS_DIR)), [job["id"] + ".json"])


class WholeCommand(JobCase):
    def test_the_real_command_scans_and_finishes(self):
        """Everything but Task Scheduler: this runs the exact program and arguments the task
        would run, parsed the way Windows would, on a folder with spaces and non-English
        letters, and follows the result the way the panel does."""
        root = os.path.join(self.d, "שיתוף עם רווח & <co>" if sys.platform != "win32"
                            else "שיתוף עם רווח & co")
        os.makedirs(os.path.join(root, "keep"))
        os.makedirs(os.path.join(root, "-skip me"))
        with open(os.path.join(root, "-skip me", "f.txt"), "w") as f:
            f.write("x")
        out = os.path.join(self.d, "דוח & co")
        os.makedirs(out)
        seen = {}

        def runner(cmd, **kw):
            if "/XML" in cmd:
                with open(cmd[cmd.index("/XML") + 1], "rb") as f:
                    seen["xml"] = ET.fromstring(f.read())
            return subprocess.CompletedProcess(cmd, 0, b"", b"")
        csv_out = os.path.join(out, "rows.csv")
        args = app.background_args("2024-01-01", "", ["-skip me"], created=False,
                                   follow_symlinks=False, precount=False) + ["-o", csv_out]
        job = app.start_background_scan(root, args, os.path.join(out, "r.html"), runner=runner)
        exe = seen["xml"].find("t:Actions/t:Exec/t:Command", NS).text
        line = seen["xml"].find("t:Actions/t:Exec/t:Arguments", NS).text
        env = dict(os.environ, HOME=self.d, USERPROFILE=self.d)   # no real settings file is touched
        res = subprocess.run([exe] + windows_argv(line), env=env, capture_output=True, timeout=120)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(app.job_state(job)[0], "finished")
        self.assertEqual(app.job_report(job), job["report"])
        with open(csv_out, encoding="utf-8-sig") as f:
            rows = f.read()
        self.assertIn("1 folder(s) excluded", rows)


if __name__ == "__main__":
    unittest.main()
