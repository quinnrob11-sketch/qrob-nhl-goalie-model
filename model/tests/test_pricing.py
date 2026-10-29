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
    """The one-sided warning is display only: same plays with it on or off."""

    def setUp(self):
        self.share = pricing.ALARM_SHARE

    def tearDown(self):
        pricing.ALARM_SHARE = self.share

    def test_alarm_reports_split(self):
        ds = [{"side": "UNDER", "ev": .05, "play": True}] * 11 + [{"side": "OVER", "ev": .03, "play": True}]
        a = pricing.night_alarm(ds)
        self.assertTrue(a["alarm"]); self.assertEqual((a["over"], a["under"]), (1, 11)); self.assertEqual(a["side"], "UNDER")
        self.assertFalse(pricing.night_alarm([{"side": s, "play": True} for s in ("OVER", "UNDER")])["alarm"])

    def test_tracker_play_set_identical_alarm_on_or_off(self):
        import copy
        import tracker
        mk = lambda side, ev, play=True: {"side": side, "ev": ev, "play": play, "tier": "LOW" if play else "PASS"}
        day = {"games": {"1": {"saves": [mk("UNDER", .09), mk("UNDER", .03), mk("OVER", .01, False)], "sog": [mk("UNDER", .04)]},
                         "2": {"saves": [mk("UNDER", .04), mk("UNDER", .05)], "sog": [mk("UNDER", .06), mk("UNDER", .02)]}}}
        plays = lambda d: [(g, m, i, r["play"], r["tier"]) for g, x in d["games"].items() for m in ("saves", "sog") for i, r in enumerate(x[m])]
        on, off = copy.deepcopy(day), copy.deepcopy(day)
        pricing.ALARM_SHARE = 0.0           # fires on every night
        self.assertTrue(tracker.night_board(on, {"1", "2"})["saves"]["alarm"])
        pricing.ALARM_SHARE = 1.01          # never fires
        self.assertFalse(tracker.night_board(off, {"1", "2"})["saves"]["alarm"])
        self.assertEqual(plays(on), plays(off))
        self.assertEqual(plays(on), plays(day))

    def test_replay_play_set_identical_alarm_on_or_off(self):
        import pandas as pd
        rng = np.random.default_rng(3)
        n = 300
        x = pd.DataFrame({"date": [f"2026-10-{1 + i % 28:02d}" for i in range(n)], "p_over": rng.uniform(.3, .7, n),
                          "line": 25.5, "model_proj": rng.normal(25, 2, n), "over": -115.0, "under": -105.0})
        x["went_over"] = rng.uniform(size=n) < x.p_over
        x["push"] = False
        x["wk"] = pd.to_datetime(x.date).dt.isocalendar().week.astype(int)
        pricing.ALARM_SHARE = 0.0
        on = calibrate.replay(x, "saves")
        pricing.ALARM_SHARE = 1.01
        off = calibrate.replay(x, "saves")
        self.assertTrue(on.alarm.any()); self.assertFalse(off.alarm.any())
        self.assertEqual(list(on.play), list(off.play))
        self.assertEqual(list(on.tier), list(off.tier))


class DfsBlend(unittest.TestCase):
    def test_dfs_leg_blends_with_dk_same_line(self):
        d = pricing.decide(0.65, None, mult_over=1, mult_under=1, market_p=0.5)
        self.assertAlmostEqual(d["p"], pricing.BLEND_W * 0.65 + (1 - pricing.BLEND_W) * 0.5)
        self.assertEqual(d["kind"] if "kind" in d else "dfs", "dfs")
        # a line with its own two prices ignores market_p
        a = pricing.decide(0.65, None, -110, -110, market_p=0.9)
        self.assertAlmostEqual(a["p"], pricing.BLEND_W * 0.65 + (1 - pricing.BLEND_W) * 0.5)


class SavesCap(unittest.TestCase):
    def test_cap_is_display_only(self):
        d = pricing.decide(0.80, None, 105, -125, market="saves")
        self.assertTrue(d["capped"]); self.assertEqual(d["p_show"], pricing.SAVES_CAP_TO)
        keep = pricing.SAVES_CAP_AT
        try:
            pricing.SAVES_CAP_AT = 2.0
            raw = pricing.decide(0.80, None, 105, -125, market="saves")
        finally:
            pricing.SAVES_CAP_AT = keep
        for k in ("side", "p", "ev", "play", "tier"):
            self.assertEqual(d[k], raw[k])
        self.assertFalse(raw["capped"]); self.assertEqual(raw["p_show"], raw["p"])

    def test_only_saves_and_only_65_plus(self):
        self.assertFalse(pricing.decide(0.80, None, 105, -125, market="sog")["capped"])
        d = pricing.decide(0.62, None, 105, -125, market="saves")
        self.assertLess(d["p"], pricing.SAVES_CAP_AT); self.assertFalse(d["capped"])


if __name__ == "__main__":
    unittest.main()
