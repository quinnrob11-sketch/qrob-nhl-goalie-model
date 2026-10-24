"""Decision rule: calibration can't tilt a 50% line, small samples shrink to identity, market blend."""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import calibrate  # noqa: E402
import pricing    # noqa: E402


class Calibration(unittest.TestCase):
    def test_no_intercept(self):
        rng = np.random.default_rng(0)
        p = rng.uniform(.3, .7, 2000)
        y = rng.uniform(size=2000) < .5 + .5 * (p - .5)          # overconfident model, no side bias
        cal = calibrate.side_fit(p, y)
        self.assertEqual(cal["a"], 0.0)
        self.assertAlmostEqual(pricing.platt(0.5, cal), 0.5, places=6)
        self.assertLess(cal["b"], 1); self.assertLess(cal["b_under"], 1)
        # symmetric slopes -> symmetric calibrated probabilities
        self.assertAlmostEqual(pricing.platt(.6, {"a": 0, "b": .7, "b_under": .7}), 1 - pricing.platt(.4, {"a": 0, "b": .7, "b_under": .7}))

    def test_small_sample_shrinks(self):
        rng = np.random.default_rng(1)
        p = rng.uniform(.3, .7, 250); y = rng.uniform(size=250) < .5
        cal = calibrate.side_fit(p, y)
        self.assertAlmostEqual(cal["shrink"], 250 / pricing.MIN_CAL_N, places=3)
        self.assertAlmostEqual(cal["b"], 1 + cal["shrink"] * (cal["b_fit"] - 1), places=3)

    def test_blend(self):
        pm = pricing.platt(.62, None)
        mk = pricing.novig(-130, 110)
        p, a, b = pricing.final_p_over(.62, None, -130, 110)
        self.assertAlmostEqual(p, pricing.BLEND_W * pm + (1 - pricing.BLEND_W) * mk)
        self.assertEqual(pricing.final_p_over(.62, None, None, 110)[0], .62)   # one price only: no blend
        d = pricing.decide(.62, None, -130, 110)
        self.assertAlmostEqual(d["p"], p if d["side"] == "OVER" else 1 - p)


class SogRule(unittest.TestCase):
    def test_gap_required_for_small_ev(self):
        # proj at the line: count model leans under, but no projection disagreement -> not a play
        d = pricing.decide(0.40, None, 120, -105, market="sog", proj=1.5, line=1.5)
        if d["side"] == "UNDER" and d["ev"] < pricing.SOG_GAP_EV:
            self.assertFalse(d["play"])
        d2 = pricing.decide(0.40, None, 120, -105, market="sog", proj=1.30, line=1.5)
        self.assertEqual(d2["side"], "UNDER")
        self.assertEqual(d2["play"], d2["p"] > d2["be"] + pricing.MARGIN_SOG and d2["ev"] >= pricing.MARGIN_SOG)

    def test_big_ev_skips_gap(self):
        d = pricing.decide(0.25, None, 150, 100, market="sog", proj=1.5, line=1.5)
        self.assertGreaterEqual(d["ev"], pricing.SOG_GAP_EV)
        self.assertTrue(d["play"])

    def test_sog_margin(self):
        self.assertGreater(pricing.MARGIN_SOG, pricing.MARGIN)


if __name__ == "__main__":
    unittest.main()
