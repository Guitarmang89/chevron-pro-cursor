"""v3.1.1: the reload busy cursor is 25 % bigger (own canvas); everything else unchanged."""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import chevron_core as core  # noqa: E402


class ReloadSize(unittest.TestCase):
    def test_canvas_and_hotspot(self):
        for s in core.SIZES:
            c = core.shape_canvas(s, "wait")
            self.assertEqual(c, int(2 * round(s * 1.25 / 2)))
            self.assertEqual(core.render(s, None, "wait", 0).size, (c, c))
            self.assertEqual(core.shape_hotspot(s, None, "wait"), (c // 2, c // 2))
            for sh in ("default", "pointer", "progress", "text"):
                self.assertEqual(core.render(s, None, sh).size, (s, s))

    def test_timing_unchanged(self):
        self.assertEqual(len(core.anim_delays("wait")), 26)
        self.assertEqual(sum(core.anim_delays("wait")), 2508)


if __name__ == "__main__":
    unittest.main()
