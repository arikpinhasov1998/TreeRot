#!/usr/bin/env python3
"""Draws the TreeRot logo with the standard library and writes every icon format."""
import base64
import os
import struct
import zlib

CREAM, GREEN, RED, RIB = (244, 241, 232), (47, 158, 85), (214, 66, 58), (58, 42, 28)
HOLES = [(64, 38, 5), (62, 58, 3.5), (72, 52, 2.5)]
SAMPLES = 3


def _bezier(p0, p1, p2, p3, steps=48):
    out = []
    for n in range(steps + 1):
        t = n / steps
        u = 1 - t
        out.append((u**3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t**3 * p3[0],
                    u**3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t**3 * p3[1]))
    return out


LEFT = _bezier((50, 10), (20, 28), (16, 62), (50, 88))
RIGHT = _bezier((50, 10), (80, 28), (84, 62), (50, 88))


def _inside(poly, x, y):
    hit = False
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            hit = not hit
    return hit


def _in_tile(x, y, r=20):
    if not (0 <= x <= 100 and 0 <= y <= 100):
        return False
    dx, dy = max(r - x, x - (100 - r), 0), max(r - y, y - (100 - r), 0)
    return dx * dx + dy * dy <= r * r


def _in_rib(x, y):
    dy = max(10 - y, y - 94, 0)
    return (x - 50) ** 2 + dy * dy <= 4


def _sample(x, y):
    if not _in_tile(x, y):
        return None
    if _in_rib(x, y):
        return RIB
    if any((x - a) ** 2 + (y - b) ** 2 <= r * r for a, b, r in HOLES):
        return CREAM
    if x <= 50 and _inside(LEFT, x, y):
        return GREEN
    if x >= 50 and _inside(RIGHT, x, y):
        return RED
    return CREAM


def render(size):
    """Returns size*size (r, g, b, a) tuples."""
    px = []
    for row in range(size):
        for col in range(size):
            tot, r, g, b = 0, 0, 0, 0
            for sy in range(SAMPLES):
                for sx in range(SAMPLES):
                    c = _sample((col + (sx + .5) / SAMPLES) * 100 / size,
                                (row + (sy + .5) / SAMPLES) * 100 / size)
                    if c:
                        tot += 1
                        r, g, b = r + c[0], g + c[1], b + c[2]
            n = SAMPLES * SAMPLES
            px.append((r // tot, g // tot, b // tot, 255 * tot // n) if tot else (0, 0, 0, 0))
    return px


def png_bytes(size):
    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff))
    px = render(size)
    raw = bytearray()
    for row in range(size):
        raw.append(0)
        for p in px[row * size:(row + 1) * size]:
            raw.extend(p)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b""))


def ico_bytes(sizes=(16, 32, 48, 256)):
    head = struct.pack("<HHH", 0, 1, len(sizes))
    offset = 6 + 16 * len(sizes)
    table, blob = b"", b""
    for s in sizes:
        d = png_bytes(s)
        table += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(d), offset)
        offset += len(d)
        blob += d
    return head + table + blob


def icns_bytes():
    body = b""
    for tag, s in ((b"ic07", 128), (b"ic08", 256), (b"ic09", 512)):
        d = png_bytes(s)
        body += tag + struct.pack(">I", len(d) + 8) + d
    return b"icns" + struct.pack(">I", len(body) + 8) + body


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    outputs = {os.path.join("assets", "treerot-256.png"): png_bytes(256),
               "app.ico": ico_bytes(), "app.icns": icns_bytes()}
    for rel, data in outputs.items():
        with open(os.path.join(root, rel), "wb") as f:
            f.write(data)
    print("ICON_PNG_B64 =", repr(base64.b64encode(png_bytes(64)).decode()))


if __name__ == "__main__":
    main()
