#!/usr/bin/env python3
"""Offline preview of the cursor trail (motion blur of the cursor image) on dark and light backgrounds.
Usage: ./trail-preview.py [out.png] [theme_dir]   (renders a fast circle with the trail's real code)"""
import importlib.machinery, importlib.util, math, os, sys
import cairo
from PIL import Image, ImageDraw
HERE = os.path.dirname(os.path.abspath(__file__))
ld = importlib.machinery.SourceFileLoader("trail", os.path.join(HERE, "chevron-pro-trail"))
spec = importlib.util.spec_from_loader("trail", ld); T = importlib.util.module_from_spec(spec); ld.exec_module(T)

out = sys.argv[1] if len(sys.argv) > 1 else "trail-preview.png"
theme = sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, "themes", "ChevronPro-WhiteCyanGlow")
cfg = dict(T.TRAIL_DEFAULTS, trail_enabled=True, trail_length=300, color="#FFFFFF")
tr = T.Tracker(); t = 0.0
while t < 1.0:
    x, y = T.fake_path(t, "circle"); tr.feed(t, x, y, cfg); t += 1 / 240.0
h, copies, bb = T.plan_copies(tr.snapshot(), t, cfg, 32.0)
ds = 1.0
spr = T.Sprites(cairo, cfg, ds, 32.0, path=os.path.join(theme, "cursors", "left_ptr"))
W, H = 1280, 800
surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H); ctx = cairo.Context(surf)
T.render_copies(ctx, spr, h, copies, (0, 0), cairo, build_budget=10 ** 6)
surf.flush()
trail = Image.frombuffer("RGBA", (W, H), bytes(surf.get_data()), "raw", "BGRa", surf.get_stride(), 1)
x1, y1 = copies[0][0], copies[0][1]
cur = T.read_xcursor(os.path.join(theme, "cursors", "left_ptr"), 32)
panels = []
for bg in ((22, 22, 26), (236, 236, 236)):
    im = Image.new("RGBA", (W, H), bg + (255,))
    im.alpha_composite(trail)
    if cur:
        w, hh, xh, yh, px, _n = cur
        ci = Image.frombuffer("RGBA", (w, hh), bytes(px), "raw", "BGRa", w * 4, 1)
        hx, hy = tr.snapshot()[-1][1:3]
        im.alpha_composite(ci, (int(hx - xh), int(hy - yh)))
    bbx = trail.getbbox() or (0, 0, W, H)
    panels.append(im.crop((bbx[0] - 30, bbx[1] - 30, bbx[2] + 30, bbx[3] + 30)).convert("RGB"))
pw, ph = panels[0].size
o = Image.new("RGB", (2 * pw + 10, ph), (0, 0, 0))
o.paste(panels[0], (0, 0)); o.paste(panels[1], (pw + 10, 0))
o.save(out); print(out)
