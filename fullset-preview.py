#!/usr/bin/env python3
"""Grid of every cursor shape in two presets, on light and dark backgrounds."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import chevron_core as core
from PIL import Image, ImageDraw, ImageFont
presets = sys.argv[2:] or ["Default", "White / Cyan Glow"]
size = 64
try:
    f = ImageFont.truetype("DejaVuSans.ttf", 11); fb = ImageFont.truetype("DejaVuSans-Bold.ttf", 15)
except OSError:
    f = fb = ImageFont.load_default()
shapes = core.SHAPES
cols = 12
cw, ch = size + 20, size + 26
rows_per = (len(shapes) + cols - 1) // cols
block_h = rows_per * ch + 28
W = cols * cw * 2 + 30
H = block_h * len(presets) + 10
img = Image.new("RGB", (W, H), (128, 128, 128)); d = ImageDraw.Draw(img)
for pi, pname in enumerate(presets):
    o = core.find_preset(pname)[1]
    y0 = pi * block_h
    for side, bg in enumerate(((236, 236, 236), (22, 22, 26))):
        x0 = 10 + side * (cols * cw + 10)
        d.rectangle([x0, y0 + 4, x0 + cols * cw - 1, y0 + block_h - 2], fill=bg)
        fg = (0, 0, 0) if side == 0 else (255, 255, 255)
        d.text((x0 + 6, y0 + 8), f"{pname} - {'light' if side == 0 else 'dark'}", font=fb, fill=fg)
        for i, sh in enumerate(shapes):
            cx = x0 + (i % cols) * cw + 10; cy = y0 + 28 + (i // cols) * ch
            cur = core.render(size, o, sh, 1 if sh in core.ANIMATED else 0)
            off = (cur.width - size) // 2            # the reload cursor's canvas is 25 % bigger: centre it
            cx -= off; cy -= off
            img.paste(cur, (cx, cy), cur)
            hx, hy = core.shape_hotspot(size, o, sh)
            d.point([(cx + hx, cy + hy)], fill=(255, 0, 255))   # magenta pixel = hotspot
            d.text((cx, cy + size + 2), sh, font=f, fill=fg)
out = sys.argv[1] if len(sys.argv) > 1 else "fullset-preview.png"
img.save(out); print("wrote", out, img.size)
