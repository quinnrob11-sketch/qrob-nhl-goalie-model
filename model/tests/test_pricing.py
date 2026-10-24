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


class OneSidedAlarm(unittest.TestCase):
    def test_alarm_keeps_top_ten_percent(self):
        ds = [{"side": "UNDER", "ev": e, "play": True} for e in (.10, .09, .05, .04, .03, .03, .02, .02, .025, .06, .02)]
        ds.append({"side": "OVER", "ev": .03, "play": True})
        a = pricing.night_alarm(ds)
        self.assertTrue(a["alarm"]); self.assertEqual(a["kept"], 2); self.assertEqual((a["over"], a["under"]), (1, 11))
        for d in ds:
            pricing.apply_alarm(d, a)
        self.assertEqual(sorted(d["ev"] for d in ds if d["play"]), [.09, .10])
        self.assertTrue(all(d["tier"] == "PASS" for d in ds if not d["play"]))

    def test_balanced_board_untouched(self):
        ds = [{"side": s, "ev": .04, "play": True} for s in ("OVER", "UNDER", "OVER", "UNDER")]
        a = pricing.night_alarm(ds)
        self.assertFalse(a["alarm"])
        self.assertTrue(all(pricing.apply_alarm(d, a)["play"] for d in ds))

    def test_tracker_freezes_started_games(self):
        import tracker
        mk = lambda side, ev: {"side": side, "ev": ev, "play": True, "tier": "LOW"}
        day = {"games": {"1": {"saves": [mk("UNDER", .09), mk("UNDER", .03)], "sog": []},
                         "2": {"saves": [mk("UNDER", .04), mk("UNDER", .05)], "sog": []}}}
        a = tracker.night_board(day, fresh={"2"})
        self.assertTrue(a["saves"]["alarm"])
        self.assertTrue(day["games"]["1"]["saves"][1]["play"])           # started game: frozen
        self.assertFalse(any(r["play"] for r in day["games"]["2"]["saves"]))  # below the night's top 10% EV


if __name__ == "__main__":
    unittest.main()
