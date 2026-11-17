"""Animated 'reload' busy cursor: an original, simplified line-art carbine side profile
(generic M4-style shape drawn from basic strokes) that swaps its curved magazine,
pulls the charging handle and settles, then rests for about a second.

Strokes use the same unit coordinates as chevron_core.shape_strokes (-1..1, y down).
Each stroke is (points, alpha) so the old and new magazines can fade at the canvas edge."""
import math

RELOAD_STEP = 42           # ms per motion frame
RELOAD_HOLD = 1000         # ms on the rest frame (frame 0)
EMPTY_HOLD = 500           # ms with the rifle empty (no magazine)
DROP = range(1, 8)         # old mag falls out through the bottom edge
EMPTY = 8                  # empty rifle, held EMPTY_HOLD ms
RISE = range(9, 16)        # new mag slides up and seats (15 = seated)
RACK = range(16, 22)       # charging handle back (16-18), held, snaps forward (20), jolt (21)
SETTLE = range(22, 26)     # damped rock back to rest
RELOAD_FRAMES = 26
RELOAD_MOTION = RELOAD_FRAMES - 1
WSCALE = 0.50              # stroke width relative to the main chevron line
OUT = 2.8                  # mag offset that puts it fully below the canvas

Y0 = -0.19                 # vertical offset that centres the silhouette


def frame_delays():
    return [RELOAD_HOLD if f == 0 else EMPTY_HOLD if f == EMPTY else RELOAD_STEP for f in range(RELOAD_FRAMES)]


def _ease_in_out(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def _ease_in(t):
    t = max(0.0, min(1.0, t))
    return t * t * t


def _ease_out_back(t, s=1.4):
    t = max(0.0, min(1.0, t)) - 1
    return 1 + t * t * ((s + 1) * t + s)


def _seg(f, a, b):
    """progress 0..1 of frame f through motion frames a..b"""
    return max(0.0, min(1.0, (f - a) / float(b - a)))


def _curve(p0, p1, p2, n=10):
    return [((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0],
             (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1]) for t in [i / n for i in range(n + 1)]]


def _magazine():
    """Curved 30-round box magazine, open at the top (it sits in the mag well)."""
    front = _curve((0.12, 0.04), (0.14, 0.46), (0.36, 0.78), 10)
    back = _curve((-0.12, 0.04), (-0.08, 0.52), (0.12, 0.86), 10)
    return back + front[::-1]


def _rifle(handle):
    """Carbine body facing right. handle: charging-handle travel 0..1 (1 = pulled back)."""
    top, bot = -0.26, 0.04
    st = [
        [(-0.58, top), (-0.97, -0.21), (-0.97, 0.26), (-0.58, bot)],   # collapsible stock
        [(-0.58, top), (0.56, top), (0.56, bot), (0.14, bot)],         # receiver top, handguard
        [(-0.58, bot), (-0.14, bot)],                                  # receiver bottom
        [(0.56, -0.11), (0.95, -0.11)],                                # barrel
        [(0.95, -0.17), (0.95, -0.05)],                                # muzzle device
        [(0.42, top), (0.45, -0.44)],                                  # front sight post
        [(-0.38, top), (-0.34, -0.42), (-0.12, -0.42), (-0.08, top)],  # optic / carry handle
        [(-0.34, bot), (-0.50, 0.50)],                                 # pistol grip
    ]
    # charging handle: T-tab at the rear of the top rail; pulling it slides the tab out the back
    bx = -0.60 - 0.42 * handle
    st.append([(-0.48, top - 0.10), (bx, top - 0.10), (bx, top - 0.01)])
    return st


def _xf(strokes, tilt, dx, dy, pivot=(-0.30, 0.0)):
    c, s = math.cos(math.radians(tilt)), math.sin(math.radians(tilt))
    px, py = pivot
    out = []
    for st in strokes:
        out.append([(px + (x - px) * c - (y - py) * s + dx, py + (x - px) * s + (y - py) * c + dy) for x, y in st])
    return out


def reload_strokes(frame):
    """Return [(points, alpha)] for frame 0..RELOAD_FRAMES-1 (frame 0 = rest)."""
    f = frame
    handle, tilt, bob, dx = 0.0, 0.0, 0.0, 0.0
    mag_dy, mag_rot, mag = 0.0, 0.0, True
    T = -7.0                                   # reload pose: muzzle tipped up a little
    if f in DROP:                              # falls with gravity, right out of the frame
        t = _seg(f, 0, DROP[-1])
        mag_dy = OUT * t * t
        mag_rot = 14 * t * t
        tilt = T * _ease_in_out(_seg(f, 0, 4))
    elif f == EMPTY:
        mag, tilt = False, T
    elif f in RISE:                            # comes up from below and seats with a small click
        t = _seg(f, EMPTY, RISE[-1])
        mag_dy = OUT * (1 - _ease_out_back(t, 1.1))
        tilt = T
        if f == RISE[-1]:
            bob = -0.03
    elif f in RACK:
        tilt = T * (1 - _ease_in_out(_seg(f, RACK[0] - 1, RACK[-1])))
        if f <= 18:                            # pull fully back
            handle = _ease_in_out(_seg(f, 15, 18))
            dx = -0.03 * handle                # rifle pulled back with it
        elif f == 19:
            handle, dx = 1.0, -0.03            # brief hold at full travel
        elif f == 20:
            handle, dx = 0.0, 0.04             # snap forward
        else:
            dx, bob = 0.015, -0.01             # jolt
    elif f in SETTLE:
        t = _seg(f, SETTLE[0] - 1, SETTLE[-1])
        tilt = 2.0 * math.sin(t * math.pi * 2) * (1 - t)
    body = _xf(_rifle(handle), tilt, dx, Y0 + bob)
    out = [(s, 1.0) for s in body]
    if mag:
        m = _xf(_xf([_magazine()], mag_rot, 0, mag_dy, pivot=(0.0, 0.04)), tilt, dx, Y0 + bob)
        out.append((m[0], 1.0))
    return out
