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
        self.assertIn("TreeRot 1.3.0", out)
        self.assertIn("Created by Arik Pinhasov", out)
        self.assertIn("github.com/arikpinhasov1998", out)

    def test_license_is_mit(self):
        with open(os.path.join(ROOT, "LICENSE"), encoding="utf-8") as f:
            text = f.read()
        self.assertTrue(text.startswith("MIT License"))
        self.assertIn("Copyright (c) 2026 Arik Pinhasov", text)
        self.assertIn("Permission is hereby granted, free of charge", text)
        self.assertNotIn("All rights reserved", text)

    def test_readme_names_the_mit_license(self):
        with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as f:
            text = " ".join(f.read().split())
        self.assertIn("MIT License", text)
        self.assertNotIn("All rights reserved", text)

    def test_report_data_carries_logo(self):
        self.assertTrue(app.ICON_PNG_B64.startswith("iVBOR"))


class Readme(unittest.TestCase):
    SECTION = "Run in background"

    def _readme(self):
        with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as f:
            return f.read()

    def _section(self):
        import re
        return re.search(r"(?ms)^### Run in background\n.*?(?=^### )", self._readme()).group(0)

    def test_the_background_section_exists(self):
        import re
        self.assertRegex(self._readme(), r"(?m)^#{2,3} " + re.escape(self.SECTION) + r"$")

    def test_no_personal_or_temporary_path_in_the_readme(self):
        text = self._readme()
        for bad in ("/Users/", "/home/", "C:\\Users", "/tmp/", "/private/"):
            self.assertNotIn(bad, text)

    def test_background_scans_ask_for_no_password_or_administrator(self):
        text = " ".join(self._section().split())
        self.assertIn("No administrator rights, no password and no installation", text)
        self.assertNotIn("Type it there", text)
        self.assertNotIn("console window", text)

    def test_the_login_items_named_match_the_program(self):
        text = self._section()
        self.assertIn(app.LOGIN_CHECK_NAME, text)
        self.assertIn(app.LOGIN_CHECK_LABEL + ".plist", text)
        self.assertIn("treerot-login-check.desktop", text)
        self.assertIn(app.WINDOWS_RUN_KEY, text.replace("\\\\", "\\"))

    def test_each_system_says_what_logging_off_does(self):
        text = self._section()
        for line in ("| Logging off, **Windows** | Stops | Stops |",
                     "| Logging out, **macOS** | Stops | Stops |",
                     "| Logging out, **Linux** | Stops | Keeps running"):
            self.assertIn(line, text)

    def test_the_checklist_covers_a_report_on_a_network_path_and_logging_off(self):
        import re
        text = self._readme()
        item = re.search(r"(?ms)^8\. .*?(?=^9\. )", text).group(0)
        self.assertIn("network path", item)
        self.assertIn("log off", re.search(r"(?ms)^10\. .*?(?=^11\. )", text).group(0))

    def test_the_readme_does_not_say_ci_has_run(self):
        text = " ".join(self._readme().split())
        for bad in ("build runs the same tests", "GitHub runs it on", "have never been tried",
                    "Actions runs the tests"):
            self.assertNotIn(bad, text)

    def test_the_report_option_names_every_browser_tried(self):
        out = subprocess.run([sys.executable, os.path.join(ROOT, "treerot.py"), "--help"],
                             stdout=subprocess.PIPE, universal_newlines=True).stdout
        self.assertIn("Edge/Chrome/Chromium/Brave", "".join(out.split()))

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
