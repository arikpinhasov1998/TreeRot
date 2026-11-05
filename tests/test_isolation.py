import os
import unittest

from tests.helpers import app


class SettingsIsolation(unittest.TestCase):
    def test_settings_files_are_not_the_real_ones(self):
        home = os.path.expanduser("~")
        real = {os.path.normcase(os.path.realpath(os.path.join(home, n)))
                for n in (".treerot.json", ".folder_activity_scanner.json")}
        for p in (app.SETTINGS_FILE, app.OLD_SETTINGS_FILE):
            self.assertNotIn(os.path.normcase(os.path.realpath(p)), real, p)

    def test_background_jobs_are_not_the_real_ones(self):
        real = os.path.join(os.path.expanduser("~"), ".treerot")
        self.assertFalse(os.path.normcase(os.path.realpath(app.JOBS_DIR)).startswith(
            os.path.normcase(os.path.realpath(real)) + os.sep), app.JOBS_DIR)
