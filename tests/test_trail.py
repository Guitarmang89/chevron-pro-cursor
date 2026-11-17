"""Unit tests for the trail speed gate (python3 -m unittest discover tests)."""
import importlib.machinery, importlib.util, json, math, os, random, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))


def load_trail():
    p = os.path.join(HERE, "..", "chevron-pro-trail")
    l = importlib.machinery.SourceFileLoader("chevron_pro_trail", p)
    s = importlib.util.spec_from_loader("chevron_pro_trail", l)
    m = importlib.util.module_from_spec(s); l.exec_module(m); return m


T = load_trail()


def cfg(sens):
    c = dict(T.TRAIL_DEFAULTS); c["trail_sensitivity"] = sens
    return c


def simulate(speed, sens, seconds=0.6, rate=240, batch=0.008, noise=0.3, seed=1):
    """Straight-line motion at `speed` px/s. Hyprland updates the position in ~8 ms batches and
    we poll at `rate` Hz with timing jitter plus sub-pixel noise. Returns (triggered, max env)."""
    rng = random.Random(seed)
    tr = T.Tracker(); c = cfg(sens)
    t, trig, peak = 0.0, False, 0.0
    while t < seconds:
        tb = math.floor(t / batch) * batch            # position as of the last batch
        x = 100 + speed * tb + rng.uniform(-noise, noise)
        y = 300 + rng.uniform(-noise, noise)
        tr.feed(t, x, y, c)
        trig |= tr.active; peak = max(peak, tr.env)
        t += (1.0 / rate) * (1 + 0.3 * (rng.random() - 0.5))
    return trig, peak


SLOW, MEDIUM, FAST = 250.0, 2600.0, 5000.0


class SpeedGate(unittest.TestCase):
    def test_curve(self):
        self.assertAlmostEqual(T.speed_threshold(0), 3800, delta=1)
        self.assertAlmostEqual(T.speed_threshold(100), 0, delta=1e-6)
        prev = None
        for s in range(0, 101, 5):
            v = T.speed_threshold(s)
            if prev is not None:
                self.assertLess(v, prev)              # monotonic: higher sensitivity = lower threshold
            prev = v
        self.assertTrue(1500 <= T.speed_threshold(60) <= 1900)   # default: as before or a bit stricter

    def test_matrix(self):
        expect = {
            0:   {SLOW: False, MEDIUM: False, FAST: True},
            50:  {SLOW: False, MEDIUM: True,  FAST: True},
            100: {SLOW: True,  MEDIUM: True,  FAST: True},
        }
        for sens, row in expect.items():
            for speed, want in row.items():
                got, _ = simulate(speed, sens)
                self.assertEqual(got, want, f"sensitivity {sens}, {speed:.0f} px/s: triggered={got}, expected {want}")

    def test_tremor_never_triggers_at_100(self):
        tr = T.Tracker(); c = cfg(100); rng = random.Random(2)
        for i in range(200):
            tr.feed(i / 240.0, 500 + rng.uniform(-0.2, 0.2), 500 + rng.uniform(-0.2, 0.2), c)
            self.assertFalse(tr.active)

    def test_single_sample_spike_ignored_at_0(self):
        tr = T.Tracker(); c = cfg(0)
        for i in range(120):
            t = i / 240.0
            x = 100 + 200 * t + (12 if i == 60 else 0)  # one glitched sample, 12 px off
            tr.feed(t, x, 300, c)
            self.assertFalse(tr.active, f"spike at sample {i}")

    def test_stall_gap_is_not_a_spike(self):
        tr = T.Tracker(); c = cfg(0)
        t = 0.0
        for i in range(50):
            tr.feed(t, 100 + 200 * t, 300, c); t += 1 / 240.0
        t += 0.25                                        # poll stalled for 250 ms...
        for i in range(50):                              # ...and the cursor "jumped" 50 px meanwhile
            tr.feed(t, 150 + 200 * t, 300, c); t += 1 / 240.0
            self.assertFalse(tr.active)

    def test_hysteresis_and_fade(self):
        c = cfg(50); thr = T.speed_threshold(50)
        tr = T.Tracker(); t = 0.0; x = 0.0
        def run(speed, secs):
            nonlocal t, x
            end = t + secs
            while t < end:
                tr.feed(t, x, 300, c); t += 1 / 240.0; x += speed / 240.0
        run(thr * 1.5, 0.2); self.assertTrue(tr.active)
        run(thr * 0.75, 0.2); self.assertTrue(tr.active, "should keep drawing above 60 % of the threshold")
        run(thr * 0.45, 0.2); self.assertFalse(tr.active)
        run(thr * 1.5, 0.2); env = tr.env
        tr.feed(t, x, 300, c)
        for _ in range(12):                               # mouse stops: envelope fades, no cut-off
            t += 1 / 240.0; tr.feed(t, x, 300, c)
        self.assertFalse(tr.active)
        self.assertGreater(tr.env, 0.2 * env)             # still fading after 50 ms
        for _ in range(240):
            t += 1 / 240.0; tr.feed(t, x, 300, c)
        self.assertLess(tr.env, 0.01)

    def test_settings_live_reload_and_migration(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "chevron-pro-cursor"))
            p = os.path.join(d, "chevron-pro-cursor", "settings.json")
            with open(p, "w") as f:
                json.dump({"trail_sensitivity": 0, "trail_rate": 120}, f)
            old = T.SETTINGS; T.SETTINGS = p
            try:
                c = T.load_cfg()
                self.assertEqual(c["trail_sensitivity"], 0)     # slider position kept, not inverted
                self.assertEqual(c["trail_rate"], 240)          # old 120 Hz setting upgraded
                with open(p, "w") as f:
                    json.dump({"trail_sensitivity": 80, "trail_sens_v": 2}, f)
                self.assertEqual(T.load_cfg()["trail_sensitivity"], 80)
            finally:
                T.SETTINGS = old


def circle_state(c, secs=0.8):
    tr = T.Tracker(); t = 0.0
    while t < secs:
        x, y = T.fake_path(t, "circle"); tr.feed(t, x, y, c); t += 1 / 240.0
    return tr, t


class Drawing(unittest.TestCase):
    def test_copy_budget_and_spacing(self):
        for length in (200, 400, 1000):
            c = cfg(60); c["trail_enabled"] = True; c["trail_length"] = length
            tr, now = circle_state(c, 1.2)
            h, copies, bb = T.plan_copies(tr.snapshot(), now, c)
            self.assertTrue(copies)
            self.assertLessEqual(len(copies), T.MAX_COPIES + 1, f"{len(copies)} copies at {length} ms")
            for a, b in zip(copies, copies[1:]):          # evenly spaced along the curve: chord <= spacing
                self.assertLess(math.hypot(b[0] - a[0], b[1] - a[1]), h * 1.01)
            hx, hy = T.fake_path(now - 1 / 240.0, "circle")
            self.assertLess(math.hypot(copies[0][0] - hx, copies[0][1] - hy), h)   # starts at the cursor
            alphas = [cp[2] for cp in copies]
            self.assertTrue(all(b <= a + 1e-9 for a, b in zip(alphas, alphas[1:])), "brightness must only decay")

    def test_streak_is_continuous(self):
        """Render a fast circle and walk along the streak: no beads, no gaps, no visible copies."""
        import cairo
        c = cfg(60); c.update(trail_enabled=True, trail_softness=0, trail_opacity=100, trail_fade=50)
        tr, now = circle_state(c)
        h, copies, bb = T.plan_copies(tr.snapshot(), now, c)
        spr = T.Sprites(cairo, c, 0.5, 32.0, path="/nonexistent")       # plain built-in chevron sprite
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 700, 520); ctx = cairo.Context(surf)
        T.render_copies(ctx, spr, h, copies, (0, 0), cairo, build_budget=10 ** 6)
        surf.flush(); data = surf.get_data(); stride = surf.get_stride()
        # strongest pixel across the streak, sampled every 1 logical px along the middle of the trail
        vals = []
        for k in range(4, len(copies) - 8):
            for j in range(int(h)):
                f = j / h
                x = copies[k][0] * (1 - f) + copies[k + 1][0] * f
                y = copies[k][1] * (1 - f) + copies[k + 1][1] * f
                best = 0
                for r in range(-12, 13):
                    ang = math.atan2(y - 400, x - 640)
                    px, py = int((x + r * math.cos(ang)) * 0.5), int((y + r * math.sin(ang)) * 0.5)
                    if 0 <= px < 700 and 0 <= py < 520:
                        best = max(best, data[py * stride + px * 4 + 3])
                vals.append(best)
        self.assertGreater(min(vals), 20, "gap in the streak")
        win = int(h)                                        # one copy spacing
        for i in range(0, len(vals) - 2 * win, win // 2):   # only the smooth decay, no ripple: no beads
            seg = vals[i:i + 2 * win]
            n = len(seg); mx = sum(range(n)) / n; my = sum(seg) / n
            k = sum((j - mx) * (v - my) for j, v in enumerate(seg)) / sum((j - mx) ** 2 for j in range(n))
            ripple = max(abs(v - (my + k * (j - mx))) for j, v in enumerate(seg))
            self.assertLess(ripple / my, 0.08, f"beads near {i}: {seg}")
        steps = [abs(b - a) for a, b in zip(vals, vals[1:])]
        self.assertLess(max(steps), 0.06 * max(vals), "a visible step along the streak")

    def test_straight_streak_is_seamless(self):
        """A straight fast stroke at any angle: the brightness along it is a smooth ramp (the
        pre-smeared copies add up exactly), compared with a reference drawn from 2000 copies."""
        import cairo
        for deg in (0, 37, 90):
            ca, sa = math.cos(math.radians(deg)), math.sin(math.radians(deg))
            c = cfg(60); c.update(trail_enabled=True, trail_softness=0, trail_opacity=25, trail_fade=50)
            tr = T.Tracker(); t = 0.0
            while t < 0.3:
                d = 2500 * t; tr.feed(t, 100 + d * ca, 120 + d * sa, c); t += 1 / 240.0
            h, copies, bb = T.plan_copies(tr.snapshot(), t, c)
            spr = T.Sprites(cairo, c, 0.5, 32.0, path="/nonexistent")
            surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 700, 700); ctx = cairo.Context(surf)
            T.render_copies(ctx, spr, h, copies, (0, 0), cairo, build_budget=10 ** 6)
            surf.flush(); dd = surf.get_data(); st = surf.get_stride()
            vals = []
            for k in range(420, 690, 2):
                best = 0
                for r in range(-30, 30):
                    px, py = int((100 + k * ca - r * sa) * 0.5), int((120 + k * sa + r * ca) * 0.5)
                    if 0 <= px < 700 and 0 <= py < 700:
                        best = max(best, dd[py * st + px * 4 + 3])
                vals.append(best)
            self.assertGreater(min(vals), 10)
            steps = [b - a for a, b in zip(vals, vals[1:])]
            # brightness only rises towards the head, in small steps: no periodic ripple from the copies
            # (diagonals are sampled on the pixel grid, hence a little tolerance)
            self.assertGreaterEqual(min(steps), -0.06 * max(vals), f"{deg} deg: dips along the streak {vals}")
            self.assertLessEqual(max(steps), 0.06 * max(vals), f"{deg} deg: jumps along the streak {vals}")

    def test_custom_trail_color_renders(self):
        """Regression (v3.0): 'Custom trail color' made the trail vanish (the tint wrote values > 255 into
        the sprite, the sprite build raised). The streak must be visible and in the chosen color."""
        import cairo
        theme = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "themes", "ChevronPro-WhiteCyanGlow", "cursors", "left_ptr")
        for path in (theme, "/nonexistent"):
            c = cfg(60); c.update(trail_enabled=True, trail_color_custom=True, trail_color="#FF2A2A")
            tr, now = circle_state(c)
            h, copies, bb = T.plan_copies(tr.snapshot(), now, c)
            spr = T.Sprites(cairo, c, 0.5, 32.0, path=path)
            surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 700, 520); ctx = cairo.Context(surf)
            T.render_copies(ctx, spr, h, copies, (0, 0), cairo, build_budget=10 ** 6)
            surf.flush(); d = bytes(surf.get_data())
            red = sum(1 for i in range(0, len(d), 4) if d[i + 3] > 40 and d[i + 2] > 2 * max(d[i], d[i + 1]) + 10)
            other = sum(1 for i in range(0, len(d), 4) if d[i + 3] > 40 and d[i + 2] <= max(d[i], d[i + 1]))
            self.assertGreater(red, 300, f"{path}: no visible red trail")
            self.assertLess(other, red // 20, f"{path}: trail not in the custom color")

    def test_trail_color_setting(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "settings.json")
            old = T.SETTINGS; T.SETTINGS = p
            try:
                with open(p, "w") as f:
                    json.dump({"trail_color": "#FF0000"}, f)       # v3.0 file: no switch yet
                c = T.load_cfg()
                self.assertFalse(c["trail_color_custom"])           # follows the cursor's colors
                self.assertEqual(c["trail_color"], "#FF0000")       # remembered for the switch
                with open(p, "w") as f:
                    json.dump({"trail_color": "#FF0000", "trail_color_custom": True}, f)
                self.assertTrue(T.load_cfg()["trail_color_custom"])
            finally:
                T.SETTINGS = old


if __name__ == "__main__":
    unittest.main()
