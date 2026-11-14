import json
import os
import plistlib
import tempfile
import unittest
from unittest import mock

from tests import helpers
from tests.helpers import OLD, app, make_tree
from tests.test_gui import GuiCase


class Dirs(unittest.TestCase):
    """Every file this module writes goes to a temporary folder."""

    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.dir = d.name
        for name, sub in (("AUTOSTART_DIR", "autostart"), ("LAUNCH_AGENTS_DIR", "agents"),
                          ("JOBS_DIR", os.path.join("t", "jobs"))):
            patch = mock.patch.object(app, name, os.path.join(d.name, sub))
            patch.start()
            self.addCleanup(patch.stop)
        patch = mock.patch.object(app, "self_command", lambda: ["/opt/tree rot/treerot"])
        patch.start()
        self.addCleanup(patch.stop)
        helpers.WINDOWS_RUN_VALUES.clear()


class StartWithMyComputer(Dirs):
    def test_linux_autostart_entry_opens_hidden_in_the_tray(self):
        self.assertFalse(app.startup_enabled("linux"))
        app.set_startup(True, "linux")
        self.assertTrue(app.startup_enabled("linux"))
        with open(os.path.join(app.AUTOSTART_DIR, "treerot-startup.desktop"),
                  encoding="utf-8") as f:
            text = f.read()
        self.assertIn('Exec="/opt/tree rot/treerot" "--tray"\n', text)
        self.assertNotIn("NoDisplay", text)
        app.set_startup(False, "linux")
        self.assertFalse(app.startup_enabled("linux"))
        app.set_startup(False, "linux")              # turning it off twice is fine

    def test_macos_launch_agent(self):
        app.set_startup(True, "darwin")
        with open(os.path.join(app.LAUNCH_AGENTS_DIR, app.STARTUP_LABEL + ".plist"), "rb") as f:
            plist = plistlib.load(f)
        self.assertEqual(plist["ProgramArguments"], ["/opt/tree rot/treerot", "--tray"])
        self.assertTrue(plist["RunAtLoad"])
        self.assertTrue(app.startup_enabled("darwin"))
        app.set_startup(False, "darwin")
        self.assertFalse(app.startup_enabled("darwin"))

    def test_windows_run_value(self):
        app.set_startup(True, "win32")
        self.assertEqual(helpers.WINDOWS_RUN_VALUES["TreeRot"], '"/opt/tree rot/treerot" --tray')
        self.assertTrue(app.startup_enabled("win32"))
        app.set_startup(False, "win32")
        self.assertNotIn("TreeRot", helpers.WINDOWS_RUN_VALUES)
        self.assertFalse(app.startup_enabled("win32"))

    def test_it_is_not_the_login_check(self):
        self.assertNotEqual(app.STARTUP_DESKTOP, "treerot-login-check.desktop")
        self.assertNotEqual(app.STARTUP_NAME, app.LOGIN_CHECK_NAME)
        self.assertNotEqual(app.STARTUP_LABEL, app.LOGIN_CHECK_LABEL)


class OneAtATime(Dirs):
    def serve(self):
        got = []
        server = app.InstanceServer(got.append)
        self.assertTrue(server.start())
        self.addCleanup(server.close)
        return server, got

    def wait_for(self, got, n=1):
        import time
        for _ in range(100):
            if len(got) >= n:
                return
            time.sleep(0.02)

    def test_a_second_start_asks_the_first_to_show(self):
        server, got = self.serve()
        self.assertTrue(app.ask_running_instance("show"))
        self.wait_for(got)
        self.assertEqual(got, ["show"])

    def test_nothing_running_means_start_normally(self):
        self.assertFalse(app.ask_running_instance())
        os.makedirs(os.path.dirname(app.instance_file()), exist_ok=True)
        with open(app.instance_file(), "w", encoding="utf-8") as f:
            json.dump({"port": 1, "token": "x"}, f)      # left over from a crash
        self.assertFalse(app.ask_running_instance())

    def test_a_wrong_secret_is_refused(self):
        server, got = self.serve()
        with open(app.instance_file(), encoding="utf-8") as f:
            info = json.load(f)
        info["token"] = "not-the-secret"
        with open(app.instance_file(), "w", encoding="utf-8") as f:
            json.dump(info, f)
        self.assertFalse(app.ask_running_instance())
        self.assertEqual(got, [])

    def test_it_listens_on_this_computer_only(self):
        server, _ = self.serve()
        self.assertEqual(server.sock.getsockname()[0], "127.0.0.1")

    def test_closing_removes_only_its_own_file(self):
        server, _ = self.serve()
        server.close()
        self.assertFalse(os.path.exists(app.instance_file()))
        other, _ = self.serve()
        server.close()                                   # again: the newer file stays
        self.assertTrue(os.path.exists(app.instance_file()))


class TrayChoice(unittest.TestCase):
    def test_no_tray_when_turned_off(self):
        self.assertIsNone(app.make_tray(None, "#000", None, None, platform="win32"))

    def test_linux_without_a_tray_keeps_the_plain_window(self):
        with mock.patch.object(app, "TRAY_ALLOWED", True), \
                mock.patch.object(app.X11Tray, "available", staticmethod(lambda p=None: False)):
            self.assertIsNone(app.make_tray(None, "#000", None, None, platform="linux"))

    def test_a_tray_that_fails_to_start_keeps_the_plain_window(self):
        def broken(*a, **k):
            raise OSError("no")
        with mock.patch.object(app, "TRAY_ALLOWED", True), \
                mock.patch.object(app, "WindowsTray", broken):
            self.assertIsNone(app.make_tray(None, "#000", None, None, platform="win32"))

    def test_x11_tray_needs_linux_and_a_display(self):
        self.assertFalse(app.X11Tray.available("win32"))
        with mock.patch.dict(os.environ, {"DISPLAY": ""}):
            self.assertFalse(app.X11Tray.available("linux"))

    def test_start_hidden_option(self):
        with mock.patch.object(app, "run_gui") as run:
            app.main(["--tray"])
        self.assertTrue(run.call_args.kwargs["hidden"])
        with mock.patch.object(app, "run_gui") as run:
            app.main([])
        self.assertFalse(run.call_args.kwargs["hidden"])


class FakeTray:
    def __init__(self, *a, **k):
        self.closed = False
        self.backgrounds = []

    def set_background(self, color):
        self.backgrounds.append(color)

    def close(self):
        self.closed = True


class Window(GuiCase):
    def setUp(self):
        self.trays = []

        def make(*a, **k):
            self.trays.append(FakeTray())
            return self.trays[-1]
        patch = mock.patch.object(app, "make_tray", make)
        patch.start()
        self.addCleanup(patch.stop)
        patch = mock.patch.object(app, "notify", lambda *a, **k: False)
        patch.start()
        self.addCleanup(patch.stop)

    def test_closing_hides_in_the_tray_and_the_icon_opens_it_again(self):
        with tempfile.TemporaryDirectory() as d:
            make_tree(d, {"f.txt": OLD})

            def check(w):
                w._close_window()
                w.update()
                self.assertEqual(w.state(), "withdrawn")
                self.assertTrue(w.winfo_exists())
                self.assertTrue(w.settings.get("tray_hint_shown"))
                w._handle_msg(("instance", "show"))       # TreeRot started a second time
                w.update()
                self.assertEqual(w.state(), "normal")
                w._close_window()
                w._show()
                w.update()
                self.assertEqual(w.state(), "normal")
            self.drive(d, check)
        self.assertTrue(self.trays[0].closed)          # the icon went with the program

    def test_the_menu_offers_open_scans_startup_and_quit(self):
        with tempfile.TemporaryDirectory() as d:
            make_tree(d, {"f.txt": OLD})

            def check(w):
                labels = [w.tray_menu.entrycget(i, "label")
                          for i in range(w.tray_menu.index("end") + 1)
                          if w.tray_menu.type(i) != "separator"]
                self.assertEqual(labels[0], "Open TreeRot")
                self.assertIn("Start with my computer", labels)
                self.assertEqual(labels[-1], "Quit TreeRot")
            self.drive(d, check)

    def test_start_with_my_computer_switch(self):
        with tempfile.TemporaryDirectory() as d:
            make_tree(d, {"f.txt": OLD})
            calls = []

            def check(w):
                with mock.patch.object(app, "set_startup", lambda on: calls.append(on)):
                    w.startup_var.set(True)
                    w._toggle_startup()
                    w.startup_var.set(False)
                    w._toggle_startup()
                self.assertEqual(calls, [True, False])
            self.drive(d, check)

    def test_icon_background_follows_the_appearance(self):
        with tempfile.TemporaryDirectory() as d:
            make_tree(d, {"f.txt": OLD})

            def check(w):
                with mock.patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": "KDE"}):
                    w._set_theme("Dark")
                    self.assertEqual(self.trays[0].backgrounds[-1],
                                     app.PALETTES["dark"]["bg"])
                with mock.patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": "ubuntu:GNOME"}):
                    w._set_theme("Light")
                    self.assertEqual(self.trays[0].backgrounds[-1], "#000000")
                w._set_theme("System")
            self.drive(d, check)

    def test_started_with_the_computer_waits_hidden(self):
        seen = {}

        def ready(w):
            seen["state"] = w.state()
            w.destroy()
        app.run_gui(on_ready=ready, hidden=True)
        self.assertEqual(seen["state"], "withdrawn")
