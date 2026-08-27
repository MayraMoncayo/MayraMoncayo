#!/usr/bin/env python3
"""Cut the subject out of a photo (GrabCut) so the background does not become a wall of glyphs.

    python cutout.py foto.jpg --crop 230,0,870,720 -o subject.png
    python ascii_art.py subject.png --cut-dark 10 --floor 55

--crop  x0,y0,x1,y1 region to keep (head + shoulders, roughly square). Default: whole image.
--rect  x0,y0,x1,y1 (inside the crop) that surely contains the subject. Default: crop minus a 5% border.
The background is painted black; ascii_art.py --cut-dark then turns it into spaces.
"""
from __future__ import annotations

import argparse

import cv2
import numpy as np


def cutout(src, crop=None, rect=None, iters=6):
    img = cv2.imread(src)
    if img is None:
        raise SystemExit(f"could not read {src}")
    if crop:
        x0, y0, x1, y1 = crop
        img = img[y0:y1, x0:x1]
    h, w = img.shape[:2]
    if rect:
        x0, y0, x1, y1 = rect
        rect = (x0, y0, x1 - x0, y1 - y0)
    else:
        rect = (int(w * 0.05), int(h * 0.02), int(w * 0.9), int(h * 0.96))
    mask = np.zeros((h, w), np.uint8)
    bgd, fgd = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
    cv2.grabCut(img, mask, rect, bgd, fgd, iters, cv2.GC_INIT_WITH_RECT)
    fg = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
    fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(fg)
    if n > 1:  # keep the biggest blob only (the person), drop specks
        fg = np.where(labels == 1 + np.argmax(stats[1:, cv2.CC_STAT_AREA]), 255, 0).astype(np.uint8)
    fg = cv2.GaussianBlur(fg, (7, 7), 0)
    return (img.astype(np.float32) * (fg[..., None] / 255.0)).astype(np.uint8), fg


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("image")
    coords = lambda s: tuple(int(v) for v in s.split(","))
    p.add_argument("--crop", type=coords)
    p.add_argument("--rect", type=coords)
    p.add_argument("--iters", type=int, default=6)
    p.add_argument("-o", "--out", default="subject.png")
    a = p.parse_args()
    img, fg = cutout(a.image, a.crop, a.rect, a.iters)
    cv2.imwrite(a.out, img)
    print(f"-> {a.out} ({img.shape[1]}x{img.shape[0]}, subject covers {fg.mean() / 255:.0%})")


if __name__ == "__main__":
    main()
