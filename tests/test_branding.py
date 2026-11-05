import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from tests.helpers import ROOT, app


class Branding(unittest.TestCase):
    def test_version_shows_name_and_credit(self):
        out = subprocess.run([sys.executable, os.path.join(ROOT, "treerot.py"), "--version"],
                             capture_output=True, text=True).stdout
        self.assertIn("TreeRot 1.2.0", out)
        self.assertIn("Created by Arik Pinhasov", out)
        self.assertIn("github.com/arikpinhasov1998", out)

    def test_license_is_all_rights_reserved(self):
        with open(os.path.join(ROOT, "LICENSE"), encoding="utf-8") as f:
            text = f.read()
        self.assertIn("All rights reserved", text)
        self.assertIn("Arik Pinhasov", text)

    def test_report_data_carries_logo(self):
        self.assertTrue(app.ICON_PNG_B64.startswith("iVBOR"))


class Readme(unittest.TestCase):
    SECTION = "Set up a background scan by hand"

    def _readme(self):
        with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as f:
            return f.read()

    def test_the_section_the_window_points_at_exists(self):
        import re
        self.assertRegex(self._readme(), r"(?m)^#{2,3} " + re.escape(self.SECTION) + r"$")

    def test_the_failure_messages_name_that_section(self):
        with self.assertRaises(app.BackgroundError) as c:
            app.task_create_command("T", "x.xml", "a&b", platform="win32", environ={})
        self.assertIn(self.SECTION, str(c.exception))

    def test_no_personal_or_temporary_path_in_the_readme(self):
        text = self._readme()
        for bad in ("/Users/", "/home/", "C:\\Users", "/tmp/", "/private/"):
            self.assertNotIn(bad, text)


    def test_the_manual_route_does_not_call_expanding_names_fine(self):
        text = self._readme()
        self.assertNotIn("are fine here", text)
        self.assertIn("Avoid `%NAME%` and `$(...)` in paths here as well", text)

    def test_the_readme_does_not_say_ci_has_run(self):
        text = " ".join(self._readme().split())
        for bad in ("build runs the same tests", "GitHub runs it on", "have never been tried",
                    "Actions runs the tests"):
            self.assertNotIn(bad, text)

    def test_the_no_browser_message_lists_every_browser_tried(self):
        for name in ("Edge", "Chrome", "Chromium", "Brave"):
            self.assertIn(name, app.NO_BROWSER_MSG)


class Release(unittest.TestCase):
    def test_the_tag_check_runs_after_python_is_set_up(self):
        with open(os.path.join(ROOT, ".github", "workflows", "release.yml"), encoding="utf-8") as f:
            text = f.read()
        build = text.index("Check that the tag matches __version__")
        self.assertLess(text.rindex("actions/setup-python", 0, build), build)
        self.assertLess(text.rindex("actions/checkout", 0, build),
                        text.rindex("actions/setup-python", 0, build))


class Migration(unittest.TestCase):
    def test_old_settings_read_once_and_old_file_kept(self):
        with tempfile.TemporaryDirectory() as d:
            new, old = os.path.join(d, ".treerot.json"), os.path.join(d, ".old.json")
            with open(old, "w", encoding="utf-8") as f:
                json.dump({"path": "/srv"}, f)
            with mock.patch.object(app, "SETTINGS_FILE", new), \
                    mock.patch.object(app, "OLD_SETTINGS_FILE", old):
                self.assertEqual(app.load_settings()["path"], "/srv")
                self.assertTrue(os.path.exists(old))
                self.assertTrue(os.path.exists(new))
                app.save_settings({"path": "/new"})
                self.assertEqual(app.load_settings()["path"], "/new")
