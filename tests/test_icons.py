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
