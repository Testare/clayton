"""make_icon.py — generate every Clayton app icon, in every platform's format.

Hand-drawn approximation of a Safari Ball, NOT a rip of the game's own sprite — the real asset
is Nintendo's, so this draws one in the same style instead: a 32x32 pixel grid with the olive
camouflage top, off-white bottom, black band and centre button. Swap in a real sprite by
replacing app/resources/clayton.png; nothing reads the art except through these files.

Pure stdlib — zlib + struct write the PNG, ICO and ICNS containers directly — so it needs no
image library, matching claytonlib's own no-dependency character. Regenerate everything with:

    python one-offs/make_icon.py

Outputs:
  app/resources/clayton.png              256x256, the runtime window icon (webview.start(icon=))
  packaging/icons/<N>x<N>/clayton.png    the Linux hicolor theme sizes
  packaging/clayton.ico                  Windows, multi-resolution
  packaging/clayton.icns                 macOS, multi-resolution

One 32x32 source grid feeds all of them, resampled by exact area coverage: for an integer
upscale that degenerates to nearest-neighbour (so the pixel art stays crisp), and for the
non-integer sizes the platforms ask for (16, 24, 48) it averages instead of dropping pixels.
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

SIZE = 32          # pixel-art grid
ROOT = Path(__file__).resolve().parent.parent
RUNTIME_PNG = ROOT / "app" / "resources" / "clayton.png"
PACKAGING = ROOT / "packaging"

# Freedesktop icon theme sizes; 256 doubles as the runtime window icon.
HICOLOR_SIZES = (16, 24, 32, 48, 64, 128, 256, 512)
# Windows shell asks for these; 256 is what modern Explorer actually shows.
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)
# (icns type, PIXEL size). The 2x types are named for their POINT size, so ic11 ("32x32@2x")
# is 64 pixels and ic12 ("64x64@2x") is 128 -- getting that wrong yields a file that validates
# but renders blurry on a retina display, which is exactly the case it exists to serve.
ICNS_ENTRIES = (("icp4", 16),    # 16x16
                ("icp5", 32),    # 32x32
                ("ic11", 64),    # 32x32@2x
                ("ic12", 128),   # 64x64@2x
                ("ic07", 128),   # 128x128
                ("ic08", 256),   # 256x256
                ("ic13", 512),   # 256x256@2x
                ("ic09", 512))   # 512x512

TRANSPARENT = (0, 0, 0, 0)
OUTLINE     = (24, 34, 20, 255)     # near-black green, the sprite's usual outline
TOP_BASE    = (150, 162, 100, 255)  # khaki/olive
TOP_LIGHT   = (183, 193, 133, 255)
TOP_DARK    = (104, 118, 66, 255)   # camo blotches
BAND        = (32, 34, 30, 255)
BOTTOM      = (238, 238, 222, 255)
BOTTOM_SHADE = (190, 192, 172, 255)
BUTTON      = (245, 245, 238, 255)
BUTTON_RING = (60, 62, 56, 255)
SHINE       = (226, 232, 196, 255)

# Camo blotches on the top half. Each is a CLUSTER of overlapping circles rather than one
# circle: a lone small circle on a 32-grid rasterises to a square, which reads as a checker
# pattern instead of camouflage. Placed by hand so they stay legible at icon size.
BLOTCHES = [
    [(10.5, 7.5, 2.4), (12.5, 9.0, 1.9), (9.0, 9.5, 1.6)],
    [(20.5, 6.8, 2.0), (22.2, 8.2, 1.6)],
    [(23.5, 11.5, 1.8), (21.8, 12.4, 1.4)],
    [(8.5, 12.5, 1.7), (10.2, 12.8, 1.3)],
    [(16.5, 10.8, 1.5), (15.0, 11.6, 1.2)],
]


def _blank():
    return [[TRANSPARENT for _ in range(SIZE)] for _ in range(SIZE)]


def _dist(x, y, cx, cy):
    return ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5


def draw() -> list[list[tuple]]:
    px = _blank()
    cx = cy = (SIZE - 1) / 2.0
    radius = 14.6
    band_top, band_bottom = 14, 17          # rows of the black band, inclusive

    for y in range(SIZE):
        for x in range(SIZE):
            d = _dist(x, y, cx, cy)
            if d > radius:
                continue
            if d > radius - 1.25:            # outline ring
                px[y][x] = OUTLINE
                continue
            if band_top <= y <= band_bottom:
                px[y][x] = BAND
            elif y < band_top:
                px[y][x] = TOP_BASE
            else:
                # The lower rim sits in shadow, as the sprites do — following the ball's
                # curve rather than a flat cut, which would read as a stripe.
                px[y][x] = BOTTOM_SHADE if d > radius - 3.4 and y > 21 else BOTTOM

    # Camo blotches, clipped to the top half only.
    for cluster in BLOTCHES:
        for y in range(SIZE):
            for x in range(SIZE):
                if y >= band_top or px[y][x] != TOP_BASE:
                    continue
                if any(_dist(x, y, bx, by) <= br for bx, by, br in cluster):
                    px[y][x] = TOP_DARK

    # Specular highlight, upper-left. Drawn AFTER the blotches so it reads as light falling
    # across them rather than being eaten by one.
    for y in range(SIZE):
        for x in range(SIZE):
            if y >= band_top or px[y][x] not in (TOP_BASE, TOP_DARK):
                continue
            d = _dist(x, y, 11.0, 6.0)
            if d <= 1.5:
                px[y][x] = SHINE
            elif d <= 2.6:
                px[y][x] = TOP_LIGHT

    # Centre button: a ring with a lighter core, straddling the band.
    for y in range(SIZE):
        for x in range(SIZE):
            d = _dist(x, y, cx, cy)
            if d <= 4.1:
                px[y][x] = BUTTON_RING
            if d <= 2.7:
                px[y][x] = BUTTON
    return px


def resample(px: list[list[tuple]], size: int) -> list[list[tuple]]:
    """The 32x32 grid rendered at `size`, by exact area coverage.

    For an integer upscale every target pixel falls wholly inside one source pixel, so this
    degenerates to nearest-neighbour and the pixel art stays crisp. For the non-integer sizes
    the platforms ask for (16, 24, 48) it averages the covered source pixels instead of
    dropping every other one, which is what keeps the ball readable when it is tiny.

    Alpha is premultiplied before averaging and divided back out afterwards; averaging raw
    RGBA would bleed the (arbitrary) colour of fully transparent pixels into the edge.
    """
    out = []
    ratio = SIZE / size
    for ty in range(size):
        row = []
        y0, y1 = ty * ratio, (ty + 1) * ratio
        for tx in range(size):
            x0, x1 = tx * ratio, (tx + 1) * ratio
            r = g = b = a = area = 0.0
            for sy in range(int(y0), min(SIZE, int(y1 - 1e-9) + 1)):
                cover_y = min(y1, sy + 1) - max(y0, sy)
                if cover_y <= 0:
                    continue
                for sx in range(int(x0), min(SIZE, int(x1 - 1e-9) + 1)):
                    cover_x = min(x1, sx + 1) - max(x0, sx)
                    if cover_x <= 0:
                        continue
                    w = cover_x * cover_y
                    sr, sg, sb, sa = px[sy][sx]
                    af = sa / 255.0
                    r += sr * af * w
                    g += sg * af * w
                    b += sb * af * w
                    a += sa * w
                    area += w
            if area <= 0 or a <= 0:
                row.append(TRANSPARENT)
                continue
            alpha = a / area
            scale_back = area * (alpha / 255.0)
            row.append((min(255, round(r / scale_back)), min(255, round(g / scale_back)),
                        min(255, round(b / scale_back)), min(255, round(alpha))))
        out.append(row)
    return out


def _chunk(tag: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


def png_bytes(grid: list[list[tuple]]) -> bytes:
    """An 8-bit RGBA PNG of `grid` (which is square)."""
    size = len(grid)
    raw = bytearray()
    for row in grid:
        raw += b"\x00"                       # filter byte 0 (None) per scanline
        for pixel in row:
            raw += bytes(pixel)
    return (b"\x89PNG\r\n\x1a\n"
            + _chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + _chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + _chunk(b"IEND", b""))


def _bmp_entry(grid: list[list[tuple]]) -> bytes:
    """One ICO image in BMP form: a 32bpp bottom-up DIB plus its AND mask.

    Used for the small sizes because PNG-compressed ICO entries are only understood from
    Vista onward, while BMP entries work everywhere. The header's height is DOUBLED (colour
    rows + mask rows) as the ICO format requires, and the mask is all-zero since the alpha
    channel carries transparency for 32bpp icons.
    """
    size = len(grid)
    pixels = bytearray()
    for row in reversed(grid):               # bottom-up
        for r, g, b, a in row:
            pixels += bytes((b, g, r, a))    # BGRA
    mask_stride = ((size + 31) // 32) * 4    # 1bpp, rows padded to 4 bytes
    mask = bytes(mask_stride * size)
    header = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0,
                         len(pixels) + len(mask), 0, 0, 0, 0)
    return header + bytes(pixels) + mask


def write_ico(px: list[list[tuple]], path: Path, sizes) -> None:
    """A multi-resolution Windows .ico. 256 is stored as PNG (the format's own convention for
    that size, and what keeps the file small); everything below it as BMP for compatibility."""
    images = []
    for size in sizes:
        grid = resample(px, size)
        images.append((size, png_bytes(grid) if size >= 256 else _bmp_entry(grid)))
    offset = 6 + 16 * len(images)
    directory, blobs = bytearray(), bytearray()
    for size, data in images:
        dim = 0 if size >= 256 else size     # 0 means 256 in the ICO directory
        directory += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
        blobs += data
        offset += len(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack("<HHH", 0, 1, len(images)) + bytes(directory) + bytes(blobs))


def write_icns(px: list[list[tuple]], path: Path, entries) -> None:
    """A macOS .icns: the 'icns' magic, the total length, then length-prefixed typed entries.
    Every type used here takes a PNG payload."""
    body = bytearray()
    for icns_type, size in entries:
        data = png_bytes(resample(px, size))
        body += icns_type.encode("ascii") + struct.pack(">I", len(data) + 8) + data
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"icns" + struct.pack(">I", len(body) + 8) + bytes(body))


def main() -> None:
    px = draw()
    written = []

    RUNTIME_PNG.parent.mkdir(parents=True, exist_ok=True)
    RUNTIME_PNG.write_bytes(png_bytes(resample(px, 256)))
    written.append((RUNTIME_PNG, "256x256 runtime window icon"))

    for size in HICOLOR_SIZES:
        out = PACKAGING / "icons" / f"{size}x{size}" / "clayton.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(png_bytes(resample(px, size)))
        written.append((out, f"{size}x{size} hicolor"))

    ico = PACKAGING / "clayton.ico"
    write_ico(px, ico, ICO_SIZES)
    written.append((ico, f"Windows ico, {len(ICO_SIZES)} sizes"))

    icns = PACKAGING / "clayton.icns"
    write_icns(px, icns, ICNS_ENTRIES)
    written.append((icns, f"macOS icns, {len(ICNS_ENTRIES)} entries"))

    for path, what in written:
        print(f"  {path.relative_to(ROOT)!s:<44} {path.stat().st_size:>7,} B  {what}")


if __name__ == "__main__":
    main()
