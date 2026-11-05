import unittest

from tests.helpers import app


class FileManagerCommand(unittest.TestCase):
    def test_files_are_shown_never_run(self):
        f = "/data/share/report.exe"
        self.assertEqual(app.file_manager_command(f, True, "win32"),
                         'explorer /select,"' + f + '"')
        self.assertEqual(app.file_manager_command(f, True, "darwin"), ["open", "-R", f])
        self.assertEqual(app.file_manager_command(f, True, "linux"),
                         ["xdg-open", "/data/share"])

    def test_folders_open_as_before(self):
        d = "/data/share"
        self.assertIsNone(app.file_manager_command(d, False, "win32"))
        self.assertEqual(app.file_manager_command(d, False, "darwin"), ["open", d])
        self.assertEqual(app.file_manager_command(d, False, "linux"), ["xdg-open", d])

    def test_windows_file_parent_logic_does_not_depend_on_host_os(self):
        self.assertEqual(app.file_manager_command("C:\\a\\b.txt", True, "win32"),
                         'explorer /select,"C:\\a\\b.txt"')

    def test_windows_path_with_spaces_is_one_quoted_string(self):
        # a list would quote the whole /select switch and Explorer would ignore it
        cmd = app.file_manager_command("C:\\My Folder\\a b.txt", True, "win32")
        self.assertIsInstance(cmd, str)
        self.assertEqual(cmd, 'explorer /select,"C:\\My Folder\\a b.txt"')

    def test_an_application_bundle_folder_is_revealed_not_launched_on_macos(self):
        for a in ("/Applications/Evil.app", "/data/Evil.APP", "/data/Evil.app/"):
            self.assertEqual(app.file_manager_command(a, False, "darwin"), ["open", "-R", a])

    def test_a_bundle_name_means_nothing_elsewhere(self):
        self.assertIsNone(app.file_manager_command("C:\\x.app", False, "win32"))
        self.assertEqual(app.file_manager_command("/d/x.app", False, "linux"), ["xdg-open", "/d/x.app"])

    def test_a_folder_merely_named_like_one_still_opens(self):
        self.assertEqual(app.file_manager_command("/d/app", False, "darwin"), ["open", "/d/app"])
