#!/usr/bin/env python3
"""Check every theme's cursors with the real libXcursor: sizes, hotspots per shape, animation,
no clipping at the canvas edge, and that every standard cursor name resolves.
Usage: ./verify.py [themes_dir ...] [--extremes]   (--extremes: also build + check 60/150 deg max-everything themes)"""
import ctypes, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import chevron_core as core

class XcursorImage(ctypes.Structure):
    _fields_ = [("version", ctypes.c_uint), ("size", ctypes.c_uint), ("width", ctypes.c_uint), ("height", ctypes.c_uint),
                ("xhot", ctypes.c_uint), ("yhot", ctypes.c_uint), ("delay", ctypes.c_uint), ("pixels", ctypes.POINTER(ctypes.c_uint32))]
class XcursorImages(ctypes.Structure):
    _fields_ = [("nimage", ctypes.c_int), ("images", ctypes.POINTER(ctypes.POINTER(XcursorImage))), ("name", ctypes.c_char_p)]
lib = ctypes.CDLL("libXcursor.so.1")
lib.XcursorFilenameLoadAllImages.restype = ctypes.POINTER(XcursorImages)
lib.XcursorFilenameLoadAllImages.argtypes = [ctypes.c_char_p]
lib.XcursorImagesDestroy.argtypes = [ctypes.POINTER(XcursorImages)]

# names Hyprland / Wayland clients request (cursor-shape-v1 + Hyprland's own border resize names)
REQUIRED = ("default context-menu help pointer progress wait cell crosshair text vertical-text alias copy move no-drop "
            "not-allowed grab grabbing e-resize n-resize ne-resize nw-resize s-resize se-resize sw-resize w-resize "
            "ew-resize ns-resize nesw-resize nwse-resize col-resize row-resize all-scroll zoom-in zoom-out "
            "left_ptr left_side right_side top_side bottom_side top_left_corner top_right_corner bottom_left_corner "
            "bottom_right_corner xterm hand2 watch left_ptr_watch fleur crossed_circle sb_h_double_arrow sb_v_double_arrow").split()
SYMMETRIC = {"ew", "ns", "nwse", "nesw", "move", "crosshair", "cell", "not-allowed", "text", "vtext"}
MAIN_TO_SHAPE = {(core.MAIN if sh == "default" else names[0]): sh for sh, names in core.NAME_MAP.items()}

args = sys.argv[1:]
EXTREMES = "--extremes" in args
args = [a for a in args if a != "--extremes"]
roots = args or ([] if EXTREMES else [os.path.join(os.path.dirname(os.path.abspath(__file__)), "themes")])
if EXTREMES:
    # Build the most demanding looks into a temp dir and check them too: narrowest (60 deg) and widest
    # (150 deg) opening, max thickness + glow + outline, heartbeat at 100 % (the pulse widens the glow).
    import tempfile
    tmp = tempfile.mkdtemp(prefix="chevron-extremes-")
    mx = dict(thickness=100, glow=100, outline_opacity=100, outline_width=100, heartbeat=True, heartbeat_intensity=100, heartbeat_bpm=120)
    looks = {"Extreme-060-Max": dict(core.DEFAULTS, angle=core.ANGLE_MIN, **mx),
             "Extreme-150-Max": dict(core.DEFAULTS, angle=core.ANGLE_MAX, heartbeat_color_custom=True, heartbeat_color="#FF2A6A", **mx),
             "Extreme-060-Thin": dict(core.DEFAULTS, angle=core.ANGLE_MIN, thickness=0, glow=0, outline_opacity=0),
             # (glow in its own color: a max glow in the line color would hide where the line starts from the tip check)
             "Extreme-060-GlowOnly": dict(core.DEFAULTS, angle=core.ANGLE_MIN, thickness=100, glow=100, outline_opacity=0, glow_color="#00F0FF",
                                         heartbeat=True, heartbeat_intensity=100)}
    for name, o in looks.items():
        core.build_theme(tmp, name, o)
    print(f"built {len(looks)} extreme themes in {tmp} (opening {2 * core.ANGLE_MIN}-{2 * core.ANGLE_MAX} deg)")
    roots.append(tmp)
bad = total = themes = 0
for root in roots:
    hb_themes = globals().setdefault("hb_themes", [])
    for theme in sorted(t for t in os.listdir(root) if os.path.isdir(os.path.join(root, t, "cursors"))):
        themes += 1
        cdir = os.path.join(root, theme, "cursors")
        problems = []
        for n in REQUIRED:
            if not os.path.exists(os.path.join(cdir, n)):
                problems.append(f"missing name {n}")
        for main, shape in MAIN_TO_SHAPE.items():
            p = lib.XcursorFilenameLoadAllImages(os.path.join(cdir, main).encode())
            if not p:
                problems.append(f"{main}: failed to load"); continue
            per_size = {}
            for i in range(p.contents.nimage):
                im = p.contents.images[i].contents
                total += 1
                W, H = im.width, im.height
                a = lambda x, y: im.pixels[y * W + x] >> 24
                per_size.setdefault(im.size, []).append(im.delay)
                hx, hy = im.xhot, im.yhot
                if not (W == H == core.shape_canvas(im.size, shape) and hx < W and hy < H):
                    problems.append(f"{shape} {im.size}px: bad dims/hotspot"); continue
                border = max([a(x, 0) for x in range(W)] + [a(x, H - 1) for x in range(W)] + [a(0, y) for y in range(H)] + [a(W - 1, y) for y in range(H)])
                fi = len(per_size[im.size]) - 1
                if shape == "wait" and (fi in core.reload_anim.DROP or fi in core.reload_anim.RISE):
                    # the magazine leaves / enters through the bottom edge on purpose; other edges must be clear
                    border = max([a(x, 0) for x in range(W)] + [a(0, y) for y in range(H)] + [a(W - 1, y) for y in range(H)])
                if border >= 10:
                    problems.append(f"{shape} {im.size}px: clipped at edge (alpha {border})")
                if core.SHAPE_KIND.get(shape) == "tip":
                    near = max(a(x, y) for x in range(max(0, hx - 1), min(W, hx + 2)) for y in range(max(0, hy - 1), min(H, hy + 2)))
                    if near < 150:   # hotspot must sit on the drawn tip (within 1px)
                        problems.append(f"{shape} {im.size}px: hotspot ({hx},{hy}) not on the tip (alpha {near})")
                if shape == "default" and fi == 0:
                    # (heartbeat themes: frame 0 is the steady glow; pulsed frames share its hotspot)
                    # topmost pixel drawn in the *line* colour in the hotspot column must be the hotspot (+-1px);
                    # the outline may sit above it by design.
                    px = lambda x, y: im.pixels[y * W + x]
                    def rgb(v):
                        al = max(1, v >> 24); return tuple(min(255, ((v >> s_) & 255) * 255 // al) for s_ in (16, 8, 0))
                    ref = max((px(hx, y) for y in range(hy, min(H, hy + 4))), key=lambda v: v >> 24)
                    same = lambda v: (v >> 24) >= 200 and max(abs(p_ - q) for p_, q in zip(rgb(v), rgb(ref))) <= 40
                    top = next((y for y in range(H) if same(px(hx, y))), None)
                    if top is None or abs(top - hy) > 1:
                        problems.append(f"default {im.size}px: tip at y={top}, hotspot y={hy}")
                if shape == "wait" and (hx != W // 2 or hy != H // 2):
                    problems.append(f"wait {im.size}px: hotspot ({hx},{hy}) not at centre")
                if shape in SYMMETRIC:
                    xs = [x for y in range(H) for x in range(W) if a(x, y) >= 200]
                    ys = [y for y in range(H) for x in range(W) if a(x, y) >= 200]
                    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
                    if hx != im.size // 2 or hy != im.size // 2 or abs(cx - hx) > 1.0 or abs(cy - hy) > 1.0:
                        problems.append(f"{shape} {im.size}px: hotspot ({hx},{hy}) not at centre ({cx:.1f},{cy:.1f})")
            lib.XcursorImagesDestroy(p)
            if shape == "default" and any(len(d) > 1 for d in per_size.values()):
                txt = open(os.path.join(root, theme, "index.theme")).read()
                want = int(txt.split("X-ChevronPro-Heartbeat-Loop-ms=")[1].split()[0]) if "Heartbeat-Loop-ms=" in txt else None
                for sz, delays in per_size.items():
                    if want is None or sum(delays) != want or min(delays) <= 0:
                        problems.append(f"heartbeat {sz}px: delays sum {sum(delays)} ms, expected {want}")
                hb_themes.append((theme, len(per_size[32]), sum(per_size[32])))
            for sz, delays in per_size.items():
                if shape in core.ANIMATED and delays != core.anim_delays(shape):
                    problems.append(f"{shape} {sz}px: {len(delays)} frames, delays {set(delays)}")
            if set(per_size) != set(core.SIZES):
                problems.append(f"{shape}: sizes {sorted(per_size)}")
        bad += len(problems)
        print(f"{theme:34s} " + ("OK (%d shapes, all names resolve)" % len(MAIN_TO_SHAPE) if not problems else "; ".join(problems[:6])))
for t, n, ms in globals().get("hb_themes", []):
    print(f"heartbeat: {t}: {n} frames, loop {ms} ms")
print("animated: wait = %d frames %s ms; progress = %d frames x %d ms" % (len(core.anim_delays("wait")), sorted(set(core.anim_delays("wait"))), core.SPIN_FRAMES, core.SPIN_DELAY))
print(f"{themes} themes, {total} images checked: " + ("ALL OK" if not bad else f"{bad} problems"))
sys.exit(bool(bad))
