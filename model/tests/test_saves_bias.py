"""Saves projections must not lean: mean (projected saves - actual) on 2026-27 graded starts within +/-0.5.

    python -m unittest discover -s model/tests -t model
"""
import csv
import json
import os
import sys
import unittest

import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import data       # noqa: E402
import engine     # noqa: E402
import fit_sa     # noqa: E402
import prizepicks  # noqa: E402
import saves_dist  # noqa: E402

OUT = os.path.join(HERE, "output")


class SavesBias(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tg, st = data.load_all([2025, 2026, 2027])
        P = engine.Params(**json.load(open(os.path.join(OUT, "params.json"))))
        df, _ = engine.run(tg, st, P, record_from_season=2027)
        cls.df = fit_sa.with_pwin(df)
        cls.dist = json.load(open(os.path.join(OUT, "saves_dist.json")))
        cls.df["proj_now"] = [saves_dist.project(r.exp_sa, r.share, r.sv, r.p_win, cls.dist)["proj"]
                              for r in cls.df.itertuples()]
        log = list(csv.DictReader(open(os.path.join(HERE, "data", "real_line_log.csv"))))
        cls.graded = {(r["date"], prizepicks.name_key(r["player"]), r["team"]) for r in log
                      if r["market"] == "saves" and r.get("result") in ("HIT", "MISS", "PUSH")}

    def test_graded_starts_unbiased(self):
        d = self.df
        key = [(str(x)[:10], prizepicks.name_key(g), t) for x, g, t in zip(d.date, d.goalie, d.team)]
        m = np.array([k in self.graded for k in key])
        self.assertGreater(m.sum(), 50, "too few graded 2026-27 starts matched")
        bias = float((d.proj_now - d.saves)[m].mean())
        print(f"\n  graded 2026-27 starts: {m.sum()}, mean proj - actual {bias:+.3f}")
        self.assertLessEqual(abs(bias), 0.5)

    def test_all_starts_shots_unbiased(self):
        d = self.df
        exp = [saves_dist.game_script(a, p, self.dist["gs"], self.dist.get("gs_cap", 0.12)) for a, p in zip(d.exp_sa, d.p_win)]
        bias = float((d.actual_team_sa - np.array(exp)).mean())
        self.assertLessEqual(abs(bias), 0.5)

    def test_game_script_cap_and_sign(self):
        self.assertGreaterEqual(self.dist["gs"], 0)
        for p in (0.01, 0.2, 0.5, 0.8, 0.99):
            x = saves_dist.game_script(30.0, p, self.dist["gs"], self.dist.get("gs_cap", 0.12))
            self.assertLessEqual(abs(x / 30.0 - 1), 0.12 + 1e-9)
        self.assertGreater(saves_dist.game_script(30.0, 0.3, 0.05), saves_dist.game_script(30.0, 0.7, 0.05))
        self.assertAlmostEqual(saves_dist.game_script(30.0, 0.001, 1.0), 30.0 * 1.12)


if __name__ == "__main__":
    unittest.main()
