"""MoneyPuck loader, the NHL cross-check, and starter / bias agreement with the page."""
import os
import sys
import unittest

import pandas as pd

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import moneypuck  # noqa: E402
import tracker  # noqa: E402


def _nhl_row(game_id, player_id, sa, saves, toi, team="TOR", date="2026-11-01", season=2027):
    return {"game_id": game_id, "player_id": player_id, "shots_against": sa, "saves": saves,
            "toi_min": toi, "team_abbrev": team, "game_date": date, "season": season}


def _mp_row(game_id, player_id, ongoal, goals, toi_min, team="TOR"):
    return {"gameId": game_id, "playerId": player_id, "ongoal": ongoal, "goals": goals,
            "saves": ongoal - goals, "toi_min": toi_min, "team": team, "date": pd.Timestamp("2026-11-01")}


class GameId(unittest.TestCase):
    def test_shot_file_id_is_the_nhl_id_without_the_season(self):
        self.assertEqual(moneypuck.nhl_game_id(2026, 20001), 2026020001)
        self.assertEqual(moneypuck.nhl_game_id(2026, 20231), 2026020231)


class CrossCheck(unittest.TestCase):
    def test_matching_box_scores_pass(self):
        nhl = pd.DataFrame([_nhl_row(2026020001, 10, 30, 27, 60.0)])
        mp = pd.DataFrame([_mp_row(2026020001, 10, 30, 3, 60.0)])
        rep = moneypuck.cross_check(nhl, mp)
        self.assertTrue(rep["ok"])
        self.assertEqual(rep["sa_mae"], 0.0)
        self.assertEqual(rep["matched"], 1)

    def test_arizona_label_is_not_a_mismatch(self):
        nhl = pd.DataFrame([_nhl_row(2023020001, 10, 28, 25, 59.0, team="ARI", date="2024-01-01", season=2024)])
        mp = pd.DataFrame([_mp_row(2023020001, 10, 28, 3, 59.0, team="UTA")])
        mp["date"] = pd.Timestamp("2024-01-01")
        rep = moneypuck.cross_check(nhl, mp)
        self.assertEqual(rep["team_mismatches"], 0)
        self.assertTrue(rep["ok"])

    def test_real_disagreement_raises_from_verify_path(self):
        nhl = pd.DataFrame([_nhl_row(2026020001, 10, 30, 27, 60.0)])
        mp = pd.DataFrame([_mp_row(2026020001, 10, 30, 3, 60.0)])
        mp["ongoal"] = 40  # 10 shots off the NHL box score
        mp["saves"] = 37
        rep = moneypuck.cross_check(nhl, mp)
        self.assertFalse(rep["ok"])
        self.assertTrue(any("shots against" in p for p in rep["problems"]))

    def test_zero_join_raises(self):
        nhl = pd.DataFrame([_nhl_row(2026020001, 10, 30, 27, 60.0)])
        mp = pd.DataFrame([_mp_row(2026020099, 99, 30, 3, 60.0)])
        with self.assertRaises(moneypuck.MoneyPuckError):
            moneypuck.cross_check(nhl, mp)

    def test_snapshot_covers_recent_seasons_and_checks_out(self):
        """The committed fallback parses, and it agrees with itself as a box score."""
        self.assertTrue(os.path.exists(moneypuck.SNAPSHOT), "committed MoneyPuck snapshot is missing")
        df, info = moneypuck.load_goalie_games([2025, 2026], refresh=False)
        self.assertFalse(df.empty)
        self.assertIn(2026, set(df.season))
        # a download may have filled the cache already; either source is fine as long as rows exist
        self.assertTrue(set(info["seasons"].values()) <= {"download", "cache", "snapshot"})
        one = df.iloc[0]
        nhl = pd.DataFrame([_nhl_row(int(one.gameId), int(one.playerId), float(one.ongoal), float(one.saves),
                                     float(one.toi_min), team=one.team, date=str(one.date.date()), season=int(one.season) + 1)])
        rep = moneypuck.cross_check(nhl, df)
        self.assertTrue(rep["ok"])
        self.assertGreaterEqual(rep["matched"], 1)


def _payload(**kw):
    base = {
        "starters": [], "dk": [], "pp": [],
        "depth": {"TOR": [1, 2]},
        "last_played": {}, "last_starter": {},
    }
    base.update(kw)
    return base


class Starters(unittest.TestCase):
    def test_confirmed_beats_a_line_and_likely_is_not_a_play(self):
        p = _payload(starters=[{"date": "2026-11-03", "team": "TOR", "goalie_id": 5, "status": "Confirmed"}],
                     dk=[{"date": "2026-11-03", "team": "TOR", "goalie_id": 1, "line": 25.5}])
        gid, src, line, _ = tracker.starter(p, "TOR", "2026-11-03")
        self.assertEqual((gid, src), (5, "df"))
        likely = _payload(starters=[{"date": "2026-11-03", "team": "TOR", "goalie_id": 5, "status": "Likely"}])
        gid, src, _, _ = tracker.starter(likely, "TOR", "2026-11-03")
        self.assertEqual(gid, 5)
        self.assertEqual(src, "df-likely")
        self.assertNotIn(src, ("dk", "pp", "manual", "df"))

    def test_likely_beats_the_back_to_back_backup(self):
        p = _payload(starters=[{"date": "2026-11-03", "team": "TOR", "goalie_id": 5, "status": "Likely"}],
                     last_played={"TOR": "2026-11-02"}, last_starter={"TOR": 1})
        gid, src, _, _ = tracker.starter(p, "TOR", "2026-11-03")
        self.assertEqual((gid, src), (5, "df-likely"))
        # no projection posted: the goalie who started last night sits
        bare = _payload(last_played={"TOR": "2026-11-02"}, last_starter={"TOR": 1})
        gid, src, _, _ = tracker.starter(bare, "TOR", "2026-11-03")
        self.assertEqual((gid, src), (2, "b2b"))

    def test_frozen_call_includes_the_rolling_bias(self):
        payload = {
            "params": {"a": 0.85, "b": 0.9, "home": 1.0, "playoff": 1.0, "b2b": 1.0, "opp_b2b": 1.0},
            "league": 28.0, "lg_share": 1.0, "saves_bias": 1.25,
            "teams": {"TOR": {"rate_def": 28, "rate_off": 28, "gf": 3, "ga": 3, "xgf": 3, "xga": 3},
                      "BOS": {"rate_def": 28, "rate_off": 28, "gf": 3, "ga": 3, "xgf": 3, "xga": 3}},
            "goalies": [{"id": 1, "name": "A Starter", "sv": 0.9, "share": 1.0}],
            "dist": {"nb_k": 30, "gs": 0, "gs_cap": 0.12, "sd_floor": 5.5},
            "win": {"params": {"w": 0.2, "home": 1.0, "ot_home": 0.5, "x": 0}, "lg_goals": 3.0},
            "starters": [], "pp": [], "ml": [], "calib": {}, "sog": {"players": {}}, "points": {},
            "dk": [{"date": "2026-11-03", "team": "TOR", "goalie_id": 1, "line": 25.5, "name": "A Starter"}],
            "depth": {"TOR": [1], "BOS": [2]}, "last_played": {}, "last_starter": {},
        }
        g = {"id": 1, "date": "2026-11-03", "home": "TOR", "away": "BOS", "type": "R"}
        call = tracker.calls_for_game(payload, g)
        row = next(r for r in call["saves"] if r["team"] == "TOR")
        self.assertAlmostEqual(row["proj"], 28 * 0.9 + 1.25, places=2)
        self.assertTrue(row["confirmed"])
        self.assertEqual(row["src"], "dk")


if __name__ == "__main__":
    unittest.main()
