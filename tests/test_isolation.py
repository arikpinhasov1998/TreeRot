import os
import unittest

from tests.helpers import app


class SettingsIsolation(unittest.TestCase):
    def test_settings_files_are_not_in_the_home_folder(self):
        home = os.path.realpath(os.path.expanduser("~"))
        for p in (app.SETTINGS_FILE, app.OLD_SETTINGS_FILE):
            self.assertFalse(os.path.realpath(p).startswith(home + os.sep), p)
