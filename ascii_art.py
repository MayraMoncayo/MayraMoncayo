#!/usr/bin/env python3
"""Photo -> ASCII art with per-character colour, sized for the profile card.

    python ascii_art.py photo.jpg                      # writes ascii.json (+ ascii.txt preview)
    python ascii_art.py photo.jpg --cols 46 --rows 26 --cut-dark 40 --colors 24

Tips for a good result:
  * A plain background and good contrast on the face work best. Crop roughly square.
  * --cut-dark N   turns pixels darker than N (0-255) into spaces -> removes a dark background.
  * --cut-light N  turns pixels brighter than 255-N into spaces -> removes a white background.
  * --gamma < 1 brightens midtones, > 1 darkens them. Try 0.8 if the face looks muddy.
  * --colors N     size of the colour palette (fewer colours = smaller SVG). --mono for grey.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageOps

RAMPS = {  # densest glyph first, blank last
    "long": "$@B%8&WM#*oahkbdpqwmZO0QLCJUYXzcvunxrjft/\\|()1{}[]?-_+~<>i!lI;:,\"^`'. ",
    "short": "@%#*+=-:. ",
}
CELL_ASPECT = 7.8 / 17  # CHAR_W / LINE_H in build_svg.py


def fit(w, h, cols, max_rows):
    rows = round(cols * (h / w) * CELL_ASPECT)
    if rows > max_rows:  # too tall for the card: give up columns instead of rows
        cols, rows = round(max_rows * (w / h) / CELL_ASPECT), max_rows
    return cols, rows


def stretch(gray, cut_dark, cut_light, floor=0):
    """Autocontrast computed on the subject only, so a blanked background does not flatten the face.

    `floor` is the darkest level a subject pixel can end up at: with a floor, dark hair on a dark
    card still gets a sparse glyph instead of vanishing into the background.
    """
    px = sorted(v for v in gray.get_flattened_data() if cut_dark <= v <= 255 - cut_light)
    if len(px) < 10:
        return gray
    lo, hi = px[int(len(px) * 0.02)], px[int(len(px) * 0.98) - 1]
    if hi <= lo:
        return gray
    background = lambda v: v < cut_dark or v > 255 - cut_light
    return gray.point(lambda v: v if background(v)
                      else int(min(255, max(floor, floor + (v - lo) * (255 - floor) / (hi - lo)))))


def convert(img, cols, max_rows, ramp, gamma, cut_dark, cut_light, colors, invert=False, floor=0):
    img = ImageOps.exif_transpose(img).convert("RGB")
    cols, rows = fit(*img.size, cols, max_rows)
    small = img.resize((cols, rows), Image.LANCZOS)
    gray = stretch(small.convert("L"), cut_dark, cut_light, floor)
    palette = small.quantize(colors=colors, method=Image.Quantize.MEDIANCUT).convert("RGB") if colors else None
    top = len(ramp) - 1
    cells = []
    for y in range(rows):
        row = []
        for x in range(cols):
            lum = gray.getpixel((x, y))
            if lum < cut_dark or lum > 255 - cut_light:
                row.append(None)
                continue
            v = (lum / 255) ** gamma
            rgb = palette.getpixel((x, y)) if palette else None
            photo, sketch = ramp[round((1 - v) * top)], ramp[round(v * top)]
            row.append((sketch, photo, rgb) if invert else (photo, sketch, rgb))
        cells.append(row)
    # trim blank rows and the common left margin so the art sits flush in the card
    while cells and not any(cells[0]):
        cells.pop(0)
    while cells and not any(cells[-1]):
        cells.pop()
    margin = min((next(i for i, c in enumerate(r) if c) for r in cells if any(r)), default=0)
    return [r[margin:] for r in cells]


def tone(rgb, theme):
    """Keep colours readable on each card: lift dark tones on the dark card, darken light tones on the
    light one, always preserving the hue. A touch more saturation on the dark card so the skin and
    clothes read as colour, not grey."""
    import colorsys
    r, g, b = (c / 255 for c in rgb)
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    if theme == "dark":
        # in deep shadows the hue is mostly noise: keep lifted shadows neutral instead of tinting them
        s = s * 0.3 if l < 0.2 else min(1.0, s * 1.3 + 0.05)
        l = max(l, 0.42)
    else:
        l, s = min(l, 0.45), min(1.0, s * 1.15)
    r, g, b = colorsys.hls_to_rgb(h, l, s)
    return "#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255))


def runs(row, which, theme):
    """Merge neighbouring cells with the same colour: [[text, colour], ...] (colour None = default)."""
    out = []
    for cell in row:
        ch, colour = (" ", None) if cell is None else (cell[which], tone(cell[2], theme) if cell[2] else None)
        if out and (colour is None or out[-1][1] == colour):
            out[-1][0] += ch
        elif out and cell is None:
            out[-1][0] += ch
        else:
            out.append([ch, colour])
    if out:
        out[-1][0] = out[-1][0].rstrip()
    return [r for r in out if r[0]]


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("image")
    p.add_argument("--cols", type=int, default=46, help="max columns (default 46)")
    p.add_argument("--rows", type=int, default=26, help="max rows (default 26)")
    p.add_argument("--ramp", choices=RAMPS, default="short")
    p.add_argument("--gamma", type=float, default=1.0)
    p.add_argument("--cut-dark", type=int, default=0)
    p.add_argument("--cut-light", type=int, default=0)
    p.add_argument("--colors", type=int, default=64, help="palette size (default 64)")
    p.add_argument("--floor", type=int, default=50,
                   help="darkest level for subject pixels, 0-255 (default 50: dark hair stays visible)")
    p.add_argument("--mono", action="store_true", help="no colour, single tone")
    p.add_argument("--sketch", action="store_true",
                   help="dark pixels get the dense glyphs (pencil-sketch look) instead of bright ones")
    p.add_argument("--sketch-light", action="store_true",
                   help="use the sketch mapping for the light card only (default: same mapping as dark)")
    p.add_argument("--out", default="ascii.json")
    a = p.parse_args()

    cells = convert(Image.open(a.image), a.cols, a.rows, RAMPS[a.ramp], a.gamma,
                    a.cut_dark, a.cut_light, 0 if a.mono else a.colors, a.sketch, a.floor)
    data = {
        "cols": max((len(r) for r in cells), default=0),
        "dark": [runs(r, 0, "dark") for r in cells],
        "light": [runs(r, 1 if a.sketch_light else 0, "light") for r in cells],
    }
    Path(a.out).write_text(json.dumps(data, ensure_ascii=False) + "\n", encoding="utf-8")
    preview = "\n".join("".join(t for t, _ in row) for row in data["dark"])
    Path("ascii.txt").write_text(preview + "\n", encoding="utf-8")
    print(preview)
    print(f"\n-> {a.out} ({data['cols']}x{len(cells)}), preview in ascii.txt")


if __name__ == "__main__":
    main()
