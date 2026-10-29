"""Skater prop engine (shots / points), line combos, DraftKings points parsing."""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import linecombos  # noqa: E402
import odds        # noqa: E402
import sog         # noqa: E402


class Dispersion(unittest.TestCase):
    def test_size_scales_with_mean(self):
        p = sog.SogParams(disp_k=10.0)
        self.assertAlmostEqual(sog.size_for(3.0, p), 30.0)
        self.assertAlmostEqual(sog.size_for(1.0, p), 10.0)
        self.assertEqual(sog.size_for(3.0, sog.SogParams(disp_k=0.0, disp=12.0)), 12.0)

    def test_stars_not_overspread(self):
        # for a 3.5-shot projection the scaled size gives a narrower distribution than the old fixed 12,
        # so P(under 3.5) for a star is lower than before (unders on stars were overrated)
        old = 1 - sog.p_over(3.5, 3.5, 12.0)
        new = 1 - sog.p_over(3.5, 3.5, sog.size_for(3.5, sog.SogParams(disp_k=10.0)))
        self.assertLess(new, old)


class LiveProjection(unittest.TestCase):
    def test_matches_state(self):
        p = sog.SogParams(b2b=0.97, opp_b2b=1.02, cal_a=-0.05, cal_b=1.04, c_team=0.5)
        st = sog.State(p)
        st.shots[1].add(30, 1, 300); st.toi[1].add(18 * 10, 1, 10)
        st.team_sa["BOS"].add(300, 1, 10); st.team_for["TOR"].add(320, 1, 10)
        want = st.project(1, "F", "BOS", True, "TOR", True, False)
        got = sog.live_proj(st.rate60(1, "F"), st.exp_toi(1, "F"), st.opp_factor("BOS"), st.team_factor("TOR"), True, True, False, p)
        self.assertAlmostEqual(want, got, places=9)

    def test_calibration_floor(self):
        self.assertEqual(sog.calibrated(-5.0, sog.SogParams(cal_a=0.0, cal_b=1.0)), 0.02)


class LineCombos(unittest.TestCase):
    PAGE = '<script id="__NEXT_DATA__" type="application/json">' + json.dumps({"props": {"pageProps": {"combinations": {"players": [
        {"name": "Auston Matthews", "groupIdentifier": "f1", "positionIdentifier": "c"},
        {"name": "Auston Matthews", "groupIdentifier": "pp1", "positionIdentifier": "c"},
        {"name": "Max Domi", "groupIdentifier": "f4", "positionIdentifier": "c"},
        {"name": "Morgan Rielly", "groupIdentifier": "d1", "positionIdentifier": "ld"},
        {"name": "Morgan Rielly", "groupIdentifier": "pp2", "positionIdentifier": "ld"}]}}}}) + '</script>'

    def test_parse(self):
        r = linecombos.parse(self.PAGE)
        self.assertEqual(r["Auston Matthews"], {"line": "F1", "pp": "PP1"})
        self.assertEqual(r["Max Domi"], {"line": "F4", "pp": None})
        self.assertEqual(r["Morgan Rielly"], {"line": "D1", "pp": "PP2"})

    def test_role_toi(self):
        slots = {"F1": 19.0, "F4": 10.0}
        self.assertEqual(linecombos.role_toi(17.0, "F1", "F1", slots), (17.0, False))
        toi, changed = linecombos.role_toi(17.0, "F4", "F2", slots)
        self.assertTrue(changed); self.assertAlmostEqual(toi, 13.5)
        self.assertEqual(linecombos.recent_slot(4, "F"), "F2"); self.assertEqual(linecombos.recent_slot(14, "F"), "F4")
        self.assertEqual(linecombos.recent_slot(3, "D"), "D2")


class DraftKingsPoints(unittest.TestCase):
    def test_parse_points_market(self):
        ev = {"home_team": "Toronto Maple Leafs", "away_team": "Boston Bruins", "commence_time": "2026-10-29T23:00:00Z"}
        js = {"bookmakers": [{"key": "draftkings", "markets": [{"key": "player_points", "outcomes": [
            {"name": "Over", "description": "Auston Matthews", "point": 0.5, "price": -180},
            {"name": "Under", "description": "Auston Matthews", "point": 0.5, "price": 140}]}]}]}
        rows = odds.parse_event(ev, js, odds.POINTS_MARKET)
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["line"], rows[0]["over"], rows[0]["under"]), (0.5, -180, 140))
        self.assertEqual(rows[0]["teams"], ["BOS", "TOR"])


if __name__ == "__main__":
    unittest.main()
