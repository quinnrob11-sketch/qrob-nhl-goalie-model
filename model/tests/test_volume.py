"""Shot and save volume, kept current (2026-11-16): a player with no NHL history starts from what debuts actually
play at his position, learned walk-forward (sog.State.debut_toi); the saves game script uses the value fitted for
the mode the shots-against model runs in (saves_dist.for_mode)."""
import os
import unittest

import pandas as pd

import saves_dist
import sog

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output")


def game(day, season, pid, pos, toi, shots=1, team="TOR", opp="FLA"):
    return {"game_id": int(day.replace("-", "")), "game_date": day, "season": season, "game_type": "R", "player_id": pid,
            "player_name": f"P{pid}", "team_abbrev": team, "opp": opp, "home_away": "home", "pos": pos,
            "shots_on_goal": shots, "points": 0, "toi_min": toi, "has_pbp": False, "icf": 0}


class DebutIceTime(unittest.TestCase):
    P = sog.SogParams.load(os.path.join(OUT, "sog_params.json"))

    def test_a_new_player_starts_from_what_debuts_play(self):
        st = sog.State(self.P)
        st.new_season(2026)
        self.assertAlmostEqual(st.exp_toi(1, "F"), 11.0)                 # the prior before any debut is seen
        self.assertGreater(st.pos_toi["F"].s / st.pos_toi["F"].w, 15)    # far above it: the average forward's minutes
        self.assertAlmostEqual(st.exp_toi(1, "D"), st.pos_toi["D"].s / st.pos_toi["D"].w)   # defence: the position average

    def test_learned_walk_forward_and_never_from_the_first_season(self):
        rows = [game("2024-10-10", 2025, 1, "F", 18.0)]                      # first season of the data: everyone is new
        rows += [game(f"2025-10-{d:02d}", 2026, 100 + d, "F", 9.0) for d in range(10, 30)]   # 20 real debuts at 9 min
        rows += [game("2025-11-02", 2026, 1, "F", 18.0)]
        sk = pd.DataFrame(rows)
        _, st = sog.run(sk, self.P)
        t = st.exp_toi(999, "F")                                             # a player never seen
        self.assertLess(t, 10.0)
        self.assertGreater(t, 9.0)
        _, st0 = sog.run(sk[sk.season == 2025], self.P)
        self.assertAlmostEqual(st0.exp_toi(999, "F"), 11.0)                 # the first season's games taught it nothing
        sk_d = pd.DataFrame([game(f"2025-10-{d:02d}", 2026, 300 + d, "D", 9.0) for d in range(10, 30)])
        _, std = sog.run(pd.concat([sk[sk.season == 2025], sk_d]), self.P)
        self.assertAlmostEqual(std.debut_toi["D"].s / std.debut_toi["D"].w, 15.0)   # defence debuts are not learned

    def test_a_player_with_history_is_unchanged(self):
        sk = pd.DataFrame([game("2025-10-10", 2026, 7, "F", 19.0), game("2025-10-12", 2026, 7, "F", 19.0)])
        _, st = sog.run(sk, self.P)
        self.assertAlmostEqual(st.exp_toi(7, "F"), 19.0, places=6)          # k_toi = 0: his own minutes only

    def test_the_debut_is_projected_on_debut_minutes(self):
        rows = [game(f"2025-10-{d:02d}", 2026, 100 + d, "F", 10.0) for d in range(10, 30)]
        rows.append(game("2025-11-05", 2026, 500, "F", 11.0))
        rows_out, st = sog.run(pd.DataFrame(rows), self.P)
        r = rows_out[rows_out.player_id == 500].iloc[0]
        # raw = rate per minute x expected minutes x opponent and venue factors: the minutes are the debut minutes
        self.assertLess(r.raw, 1.4)


class GameScriptByMode(unittest.TestCase):
    def test_the_value_for_the_running_mode(self):
        d = {"nb_k": 30.0, "gs": 0.025, "gs_cap": 0.12, "sd_floor": 5.5, "gs_mp": 0.005}
        self.assertEqual((saves_dist.for_mode(d, "mp")["gs"], saves_dist.for_mode(d, "mp")["gs_mode"]), (0.005, "mp"))
        self.assertEqual((saves_dist.for_mode(d, "corsi")["gs"], saves_dist.for_mode(d, "corsi")["gs_mode"]), (0.025, "corsi"))
        self.assertEqual(saves_dist.for_mode({**d, "gs_mp": None}, "mp")["gs"], 0.025)   # not fitted: the Corsi value
        self.assertEqual(saves_dist.for_mode({k: v for k, v in d.items() if k != "gs_mp"}, "mp")["gs"], 0.025)
        self.assertEqual(d["gs"], 0.025)                                                 # the input is not changed

    def test_the_shipped_settings(self):
        d = saves_dist.load(os.path.join(OUT, "saves_dist.json"))
        self.assertIn("gs_mp", d)
        self.assertLess(d["gs_mp"], d["gs"])            # MoneyPuck's attempt terms already carry most of the strength gap
        lo = saves_dist.project(30.0, 0.97, 0.9, 0.3, saves_dist.for_mode(d, "mp"))["proj"]
        hi = saves_dist.project(30.0, 0.97, 0.9, 0.3, saves_dist.for_mode(d, "corsi"))["proj"]
        self.assertLess(lo, hi)                         # an underdog's goalie: a smaller bump in MoneyPuck mode


if __name__ == "__main__":
    unittest.main()
