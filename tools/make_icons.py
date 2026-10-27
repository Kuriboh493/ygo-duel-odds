"""Draw the extension's toolbar icons (a face-down card with an eye) as PNGs, with no image libraries.

Usage: python3 tools/make_icons.py
"""
import math, os, struct, zlib

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "extension", "icons")
INK, GOLD, GOLD2, CARD = (23, 32, 44), (217, 166, 64), (154, 106, 12), (36, 48, 64)

def rrect(x, y, x0, y0, x1, y1, r):
    cx, cy = min(max(x, x0 + r), x1 - r), min(max(y, y0 + r), y1 - r)
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r and x0 <= x <= x1 and y0 <= y <= y1

def shade(u, v):
    """Colour at a point in the unit square, or None for transparent."""
    if not rrect(u, v, 0, 0, 1, 1, 0.22): return None
    # The card, slightly tilted, with a gold border.
    a = math.radians(-8); cu, cv = u - 0.5, v - 0.5
    x, y = cu * math.cos(a) - cv * math.sin(a) + 0.5, cu * math.sin(a) + cv * math.cos(a) + 0.5
    if rrect(x, y, 0.24, 0.14, 0.76, 0.86, 0.07):
        if not rrect(x, y, 0.29, 0.19, 0.71, 0.81, 0.04): return GOLD
        # Eye: an almond of two arcs with a gold pupil.
        ex, ey = (x - 0.5) / 0.17, (y - 0.5) / 0.17
        if abs(ex) < 1 and abs(ey) < 0.62 * (1 - ex * ex):
            return GOLD if ex * ex + ey * ey < 0.16 else (240, 226, 196)
        t = (y - 0.19) / 0.62
        return tuple(int(CARD[i] + (GOLD2[i] - CARD[i]) * 0.25 * t) for i in range(3))
    return INK

def png(size):
    rows, ss = [], 4
    for py in range(size):
        row = bytearray([0])
        for px in range(size):
            acc, n = [0, 0, 0], 0
            for sy in range(ss):
                for sx in range(ss):
                    c = shade((px + (sx + .5) / ss) / size, (py + (sy + .5) / ss) / size)
                    if c: n += 1; acc = [acc[i] + c[i] for i in range(3)]
            row += bytes([acc[0] // n, acc[1] // n, acc[2] // n, 255 * n // (ss * ss)] if n else [0, 0, 0, 0])
        rows.append(bytes(row))
    def chunk(t, d): return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b"")

if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    for s in (16, 32, 48, 128):
        with open(os.path.join(OUT, f"icon-{s}.png"), "wb") as f: f.write(png(s))
    print("icons written to", OUT)
