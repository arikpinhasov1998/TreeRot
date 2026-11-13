import os
import tempfile
import unittest
from datetime import datetime
from unittest import mock

from tests.helpers import OLD, app, make_tree, scan_rows

FROM = datetime(2024, 11, 4)


def mountinfo_line(mount_point, fstype):
    return f"25 1 0:5 / {mount_point} rw,relatime shared:2 - {fstype} {fstype} rw\n"


class VirtualMountTable(unittest.TestCase):
    def read(self, text):
        with tempfile.NamedTemporaryFile("w", suffix=".mountinfo", delete=False) as f:
            f.write(text)
        self.addCleanup(os.remove, f.name)
        return app.virtual_mounts(f.name)

    def test_picks_only_virtual_filesystems(self):
        got = self.read(mountinfo_line("/proc", "proc") + mountinfo_line("/sys", "sysfs")
                        + mountinfo_line("/home", "ext4") + mountinfo_line("/tmp", "tmpfs"))
        self.assertEqual(got, {"/proc", "/sys"})

    def test_decodes_escaped_spaces(self):
        got = self.read(mountinfo_line("/mnt/my\\040proc", "proc"))
        self.assertEqual(got, {"/mnt/my proc"})

    def test_missing_table_means_nothing_to_skip(self):
        self.assertEqual(app.virtual_mounts("/nonexistent/mountinfo"), set())


class SkipsVirtualFolders(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.root = d.name
        make_tree(self.root, {"real/f.txt": OLD, "fakeproc/kcore": OLD})
        self.fake = os.path.join(self.root, "fakeproc")
        patch = mock.patch.object(app, "virtual_mounts", return_value={self.fake})
        patch.start()
        self.addCleanup(patch.stop)

    def test_virtual_mount_below_root_is_skipped_with_its_size(self):
        rows = scan_rows(self.root, FROM)
        self.assertNotIn("fakeproc", rows)
        self.assertIn("real", rows)
        self.assertEqual(rows["."]["info"].total_size, 100)

    def test_count_pass_skips_it_too(self):
        self.assertEqual(app.count_tree(self.root), (2, 1))

    def test_scanning_inside_a_virtual_mount_still_works(self):
        rows = scan_rows(self.fake, FROM)
        self.assertEqual(rows["."]["info"].total_files, 1)


@unittest.skipUnless(os.path.isfile("/proc/kcore"), "needs Linux /proc")
class RealProc(unittest.TestCase):
    def test_root_scan_would_skip_proc(self):
        self.assertTrue(app.make_excluder("/", [])("/proc", "proc"))

    def test_real_folders_are_not_skipped(self):
        self.assertFalse(app.make_excluder("/", [])("/home", "home"))
