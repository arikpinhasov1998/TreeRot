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
