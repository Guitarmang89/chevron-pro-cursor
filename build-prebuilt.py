#!/usr/bin/env python3
"""Build the prebuilt chevron themes into ./themes and the preview grid."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import chevron_core as core
from PIL import Image, ImageDraw, ImageFont
GLOWS = [("", 0), ("-Glow-Low", 25), ("-Glow-Med", 50), ("-Glow-High", 85)]
HERE = os.path.dirname(os.path.abspath(__file__))
out = os.path.join(HERE, "themes")
os.makedirs(out, exist_ok=True)
# One prebuilt theme per built-in preset (the app can make any other combination).
for pname, p in core.BUILTIN_PRESETS.items():
    name = "ChevronPro-" + "".join(w.capitalize() for w in pname.replace("/", " ").split())
    core.build_theme(out, name, p)
    print("built", name)

# preview grid: colors x glow levels, light and dark backgrounds, at 96px
size = 96
crop = (0, int(size * 0.14), size, int(size * 0.74))
cw, ch = size + 24, crop[3] - crop[1] + 24
lw, top = 120, 60
W, H = lw + cw * 8 + 20, top + ch * (len(core.PRESETS) + 1) + 10
img = Image.new("RGB", (W, H), (128, 128, 128)); d = ImageDraw.Draw(img)
try:
    f = ImageFont.truetype("DejaVuSans.ttf", 14); fb = ImageFont.truetype("DejaVuSans-Bold.ttf", 17)
except OSError:
    f = fb = ImageFont.load_default()
LIGHT, DARK = (236, 236, 236), (22, 22, 26)
d.rectangle([lw, 0, lw + cw * 4, H], fill=LIGHT); d.rectangle([lw + cw * 4 + 20, 0, W, H], fill=DARK)
d.text((lw + 8, 6), "Light background", font=fb, fill=(0, 0, 0)); d.text((lw + cw * 4 + 28, 6), "Dark background", font=fb, fill=(255, 255, 255))
labels = ["No glow", "Glow-Low", "Glow-Med", "Glow-High"]
for side in range(2):
    for i, l in enumerate(labels):
        d.text((lw + side * (cw * 4 + 20) + i * cw + 10, 34), l, font=f, fill=(0, 0, 0) if side == 0 else (255, 255, 255))
for r, (cname, hx) in enumerate(core.PRESETS.items()):
    y = top + r * ch
    d.text((8, y + ch // 2 - 9), cname, font=fb, fill=(255, 255, 255))
    for i, (_, g) in enumerate(GLOWS):
        cur = core.render(size, {"color": hx, "glow": g}).crop(crop)
        for side in range(2):
            x = lw + side * (cw * 4 + 20) + i * cw + 12
            img.paste(cur, (x, y + 12), cur)
y = top + len(core.PRESETS) * ch
d.text((8, y + ch // 2 - 9), "HighCon-\ntrast", font=fb, fill=(255, 255, 255))
cur = core.render(size, core.HIGH_CONTRAST).crop(crop)
for side in range(2):
    img.paste(cur, (lw + side * (cw * 4 + 20) + 12, y + 12), cur)
p = os.path.join(HERE, "preview.png"); img.save(p); print("wrote", p)
