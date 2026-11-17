"""v3.1: heartbeat 25 % stronger, own color, no clipping."""
import os, sys, unittest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import chevron_core as core  # noqa: E402


def stats(img):
    red = cyan = 0; asum = 0
    for r, g, b, a in img.getdata():
        if a < 20:
            continue
        asum += a
        if r > 150 and g < 120 and b < 150 and r > b:
            red += 1
        elif g > 150 and b > 150 and r < 120:
            cyan += 1
    return red, cyan, asum


class Heartbeat(unittest.TestCase):
    base = dict(core.DEFAULTS, color="#FFFFFF", glow_color="#00FFFF", glow=60, heartbeat=True, heartbeat_intensity=100)

    def test_gain(self):
        self.assertAlmostEqual(core.HB_GAIN, 1.25)
        a0 = stats(core.render(48, self.base, pulse=0.0))[2]
        a1 = stats(core.render(48, self.base, pulse=1.0))[2]
        self.assertGreater(a1, a0 * 1.1)

    def test_default_uses_glow_color(self):
        self.assertEqual(core.heartbeat_rgb(core.opts_of(self.base)), core.glow_rgb(core.opts_of(self.base)))
        o = dict(self.base, heartbeat_color="#FF2A2A")          # set but switch off -> glow color
        self.assertEqual(core.heartbeat_rgb(core.opts_of(o)), core.glow_rgb(core.opts_of(o)))

    def test_custom_color_pulse(self):
        o = dict(self.base, heartbeat_color_custom=True, heartbeat_color="#FF2A2A")
        red0, cyan0, _ = stats(core.render(48, o, pulse=0.0))
        red1, cyan1, _ = stats(core.render(48, o, pulse=1.0))
        self.assertLess(red0, 5)                 # at rest: just the steady cyan glow
        self.assertGreater(cyan0, 50)
        self.assertGreater(red1, 100)            # at the beat the boost is red

    def test_no_clipping_at_extremes(self):
        for glow in (0, 100):
            for thick in (0, 100):
                o = dict(self.base, glow=glow, thickness=thick, heartbeat_color_custom=True, heartbeat_color="#FF00FF")
                for size in (24, 64):
                    im = core.render(size, o, pulse=1.0)
                    self.assertEqual(im.size, (size, size))
                    w = size
                    px = im.load()
                    edge = [px[x, y][3] for x in range(w) for y in (0, w - 1)] + [px[x, y][3] for y in range(w) for x in (0, w - 1)]
                    self.assertLess(max(edge), 40, (glow, thick, size))   # the glow fades out inside the canvas
                    for r, g, b, a in im.getdata():
                        assert 0 <= a <= 255 and max(r, g, b) <= 255


if __name__ == "__main__":
    unittest.main()
