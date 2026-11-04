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
