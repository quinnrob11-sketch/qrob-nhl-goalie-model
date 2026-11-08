"""NHL stat corrections: graded lines are re-graded when the box score changes (tracker._regrade)."""
import unittest

import pandas as pd

import tracker


def box(rows):
    return pd.DataFrame(rows, columns=["game_date", "team_abbrev", "player_name", "shots_on_goal", "points", "saves", "starter"])


class Regrade(unittest.TestCase):
    def test_corrected_stat_flips_the_result_and_keeps_a_note(self):
        log = [{"date": "2026-10-06", "market": "sog", "player": "N. Ehlers", "team": "CAR", "side": "OVER", "line": "2.5",
                "actual": "3", "result": "HIT", "note": ""},
               {"date": "2026-10-06", "market": "sog", "player": "S. Aho", "team": "CAR", "side": "UNDER", "line": "2.5",
                "actual": "2", "result": "HIT", "note": ""},
               {"date": "2026-10-06", "market": "sog", "player": "No Box", "team": "CAR", "side": "UNDER", "line": "2.5",
                "actual": "1", "result": "HIT", "note": ""},
               {"date": "2026-10-06", "market": "sog", "player": "Waiting", "team": "CAR", "side": "UNDER", "line": "2.5",
                "actual": "", "result": "", "note": ""}]
        sb = box([["2026-10-06", "CAR", "N. Ehlers", 2, 0, None, None], ["2026-10-06", "CAR", "S. Aho", 2, 1, None, None],
                  ["2026-10-06", "CAR", "Waiting", 4, 0, None, None]])
        gb = box([]).astype({"starter": bool})
        self.assertEqual(tracker._regrade(log, gb, sb), 1)
        self.assertEqual((log[0]["actual"], log[0]["result"]), (2, "MISS"))
        self.assertIn("stat corrected 3→2", log[0]["note"])
        self.assertEqual((log[1]["actual"], log[1]["result"]), ("2", "HIT"))      # unchanged rows are left alone
        self.assertEqual(log[2]["result"], "HIT")                                 # no box row: left alone
        self.assertEqual(log[3]["result"], "")                                    # ungraded rows are not touched here


class RegradeLegs(unittest.TestCase):
    def test_graded_leg_follows_a_corrected_box_score(self):
        import os, tempfile
        old = tracker.LEGS
        tracker.LEGS = os.path.join(tempfile.mkdtemp(), "legs.csv")
        try:
            leg = {k: "" for k in tracker.LEG_FIELDS}
            leg.update(date="2026-11-03", game=2026020100, built="x", player_id=8475000, name="A. Player", team="CAR", opp="FLA",
                       market="sog", line=2.5, source="Pick6", mo=1, mu=1, side="OVER", mult=1, p=0.6, verdict="TAKE MORE",
                       result="HIT", actual=3)
            tracker._write_legs([leg])
            sb = pd.DataFrame({"game_id": [2026020100], "player_id": [8475000], "shots_on_goal": [2], "points": [0],
                               "game_date": ["2026-11-03"]})
            gb = pd.DataFrame({"game_id": [], "player_id": [], "saves": [], "toi": []})
            out = tracker.grade_legs(sb, gb)
            self.assertEqual((int(out[0]["actual"]), out[0]["result"]), (2, "MISS"))
            back = tracker._read_legs()
            self.assertEqual((str(back[0]["actual"]), back[0]["result"]), ("2", "MISS"))
        finally:
            tracker.LEGS = old


class Nicknames(unittest.TestCase):
    def test_evgeni_evgeny_yevgeni_and_yegor(self):
        import players
        for a, b in (("evgeni", "Evgeny"), ("evgeny", "Evgeni"), ("yevgeni", "Evgeny"), ("evgenii", "Evgeni"), ("yevgeny", "Evgeni"), ("yegor", "Egor")):
            self.assertTrue(players.first_ok(a, b), (a, b))


if __name__ == "__main__":
    unittest.main()
