import os
import struct
import sys
import unittest

from tests.helpers import ROOT

sys.path.insert(0, os.path.join(ROOT, "tools"))
import make_icons  # noqa: E402


class Icons(unittest.TestCase):
    def test_png_has_requested_size(self):
        b = make_icons.png_bytes(32)
        self.assertEqual(b[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(struct.unpack(">II", b[16:24]), (32, 32))

    def test_left_is_green_right_is_red_corner_transparent(self):
        px = make_icons.render(64)
        r, g, b, a = px[32 * 64 + 20]
        self.assertGreater(g, r)
        r, g, b, a = px[20 * 64 + 38]
        self.assertGreater(r, g)
        self.assertEqual(px[0][3], 0)

    def test_ico_and_icns_headers(self):
        self.assertEqual(make_icons.ico_bytes()[:4], b"\x00\x00\x01\x00")
        self.assertEqual(make_icons.icns_bytes()[:4], b"icns")


class AppIconInEveryPlace(unittest.TestCase):
    """Where TreeRot shows its logo outside its own window."""

    def setUp(self):
        import base64
        import tempfile
        from unittest import mock
        from tests import helpers
        self.app, self.helpers = helpers.app, helpers
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        for name, value in (("JOBS_DIR", os.path.join(d.name, "jobs")),
                            ("AUTOSTART_DIR", os.path.join(d.name, "autostart"))):
            patch = mock.patch.object(self.app, name, value)
            patch.start()
            self.addCleanup(patch.stop)
        self.png = base64.b64decode(self.app.ICON_LARGE_PNG_B64)
        self.mock = mock

    def test_icon_file_is_written_once_next_to_the_records(self):
        path = self.app.icon_file()
        self.assertEqual(os.path.dirname(path), os.path.dirname(self.app.JOBS_DIR))
        with open(path, "rb") as f:
            self.assertEqual(f.read(), self.png)
        before = os.stat(path).st_mtime_ns
        self.assertEqual(self.app.icon_file(), path)
        self.assertEqual(os.stat(path).st_mtime_ns, before)

    def test_a_damaged_icon_file_is_repaired(self):
        path = self.app.icon_file()
        with open(path, "wb") as f:
            f.write(b"broken")
        self.app.icon_file()
        with open(path, "rb") as f:
            self.assertEqual(f.read(), self.png)

    def test_report_has_a_browser_tab_icon(self):
        import tempfile
        from datetime import datetime
        from tests.helpers import OLD, make_tree, scan_rows
        from tests.test_report import meta_for
        with tempfile.TemporaryDirectory() as d:
            make_tree(d, {"a/f.txt": OLD})
            rows = list(scan_rows(d, datetime(2024, 1, 1)).values())
            out = os.path.join(d, "r.html")
            self.app.write_html_report(out, rows, meta_for(d))
            with open(out, encoding="utf-8") as f:
                text = f.read()
        self.assertIn('<link rel="icon" type="image/png" href="data:image/png;base64,'
                      + self.app.ICON_PNG_B64 + '">', text)
        self.assertNotIn("__ICON__", text)

    def test_linux_notification_and_login_item_show_the_icon(self):
        import subprocess
        cmds = []

        def run(cmd, env=None, **kw):
            cmds.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, b"2" if cmd[0] == "loginctl" else b"", b"")
        with self.mock.patch.object(self.app.shutil, "which", lambda n: "/usr/bin/" + n):
            self.assertTrue(self.helpers.REAL_NOTIFY("t", "b", platform="linux", run=run))
        cmd = cmds[-1]
        self.assertEqual(cmd[cmd.index("--icon") + 1], self.app.icon_file())
        self.assertEqual(cmd[-2:], ["t", "b"])
        self.app.install_login_check(platform="linux")
        with open(os.path.join(self.app.AUTOSTART_DIR, "treerot-login-check.desktop"),
                  encoding="utf-8") as f:
            self.assertIn(f"Icon={self.app.icon_file()}\n", f.read())

    def test_windows_notification_uses_treerots_own_name_and_icon(self):
        import subprocess
        envs = []

        def run(cmd, env=None, **kw):
            envs.append(env)
            return subprocess.CompletedProcess(cmd, 0, b"", b"")
        self.helpers.WINDOWS_APP_ID_VALUES.clear()
        icon = "C:\\Users\\a\\.treerot\\treerot.png"
        with self.mock.patch.object(self.app, "icon_file", lambda: icon):
            self.helpers.REAL_NOTIFY("t", "b", platform="win32", run=run)
        env = envs[-1]
        self.assertEqual(env["TREEROT_APP_ID"], self.app.APP_ID)
        self.assertEqual(env["TREEROT_ICON"], "file:///C:/Users/a/.treerot/treerot.png")
        self.assertEqual(self.helpers.WINDOWS_APP_ID_VALUES,
                         {"DisplayName": "TreeRot", "IconUri": icon})

    def test_windows_falls_back_to_powershell_when_it_cannot_register(self):
        def refuse(values):
            raise OSError("no")
        with self.mock.patch.object(self.app, "_set_windows_app_id", refuse):
            self.assertEqual(self.app.windows_app_id("x.png"), self.app.POWERSHELL_APP_ID)
        self.assertEqual(self.app.windows_app_id(None), self.app.POWERSHELL_APP_ID)

    def test_icon_address_survives_spaces_and_hebrew(self):
        uri = self.app.ntpath_uri("C:\\Users\\A B\\.treerot\\\u05e2\u05e5.png")
        self.assertTrue(uri.startswith("file:///C:/Users/A%20B/"))
        self.assertNotIn(" ", uri)
        self.assertEqual(self.app.ntpath_uri("relative.png"), "")


class SharpLogo(unittest.TestCase):
    def test_large_logo_is_the_256_pixel_drawing(self):
        import base64
        from tests.helpers import app
        data = base64.b64decode(app.ICON_LARGE_PNG_B64)
        self.assertEqual(data, make_icons.png_bytes(256))
        self.assertEqual(struct.unpack(">II", data[16:24]), (256, 256))


class LinuxDockIcon(unittest.TestCase):
    def setUp(self):
        import tempfile
        from unittest import mock
        from tests.helpers import app
        self.app = app
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        for name, value in (("APPLICATIONS_DIR", os.path.join(d.name, "applications")),
                            ("JOBS_DIR", os.path.join(d.name, "t", "jobs"))):
            patch = mock.patch.object(app, name, value)
            patch.start()
            self.addCleanup(patch.stop)

    def test_entry_matches_the_window_and_stays_out_of_the_menu(self):
        text = self.app.linux_desktop_entry(["/opt/tree rot/treerot"], "/x/treerot.png")
        self.assertIn("StartupWMClass=Treerot\n", text)
        self.assertIn("Icon=/x/treerot.png\n", text)
        self.assertIn("NoDisplay=true\n", text)
        self.assertIn('Exec="/opt/tree rot/treerot"\n', text)
        self.assertTrue(text.startswith("[Desktop Entry]\n"))

    def test_entry_is_written_once_and_rewritten_when_the_program_moves(self):
        from unittest import mock
        path = os.path.join(self.app.APPLICATIONS_DIR, "treerot.desktop")
        self.assertTrue(self.app.install_linux_desktop_entry())
        before = os.stat(path).st_mtime_ns
        self.assertFalse(self.app.install_linux_desktop_entry())     # unchanged: not rewritten
        self.assertEqual(os.stat(path).st_mtime_ns, before)
        with mock.patch.object(self.app, "self_command", lambda: ["/new/place/treerot"]):
            self.assertTrue(self.app.install_linux_desktop_entry())
        with open(path, encoding="utf-8") as f:
            self.assertIn("Exec=\"/new/place/treerot\"\n", f.read())

    def test_the_entry_from_the_earlier_name_is_removed(self):
        os.makedirs(self.app.APPLICATIONS_DIR)
        old = os.path.join(self.app.APPLICATIONS_DIR, "io.github.arikpinhasov1998.TreeRot.desktop")
        open(old, "w").close()
        self.app.install_linux_desktop_entry()
        self.assertFalse(os.path.exists(old))

    def test_entry_file_is_named_after_the_window_class(self):
        self.assertEqual(self.app.LINUX_DESKTOP_FILE, self.app.LINUX_WM_CLASS.lower() + ".desktop")

    @unittest.skipUnless(sys.platform.startswith("linux"), "Tk window class on X11")
    def test_window_class_is_the_one_the_entry_names(self):
        from tests.test_gui import tk_ok
        if not tk_ok():
            self.skipTest("no display")
        seen = {}

        def ready(w):
            seen["class"] = w.winfo_class()
            w.destroy()
        self.app.run_gui(on_ready=ready)
        self.assertEqual(seen["class"], self.app.LINUX_WM_CLASS)
