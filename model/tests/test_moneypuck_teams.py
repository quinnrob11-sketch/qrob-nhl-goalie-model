"""MoneyPuck team logs (moneypuck_teams.refresh): each team's log is pulled about once a day, judged by the time of
its last good pull kept in the committed status file (never by file ages: a fresh checkout has none), and only the
four numbers the model needs from this season's games are kept (attempts_recent.csv)."""
import datetime as dt
import io
import json
import os
import shutil
import tempfile
import unittest

import pandas as pd

import moneypuck_teams as mt

NOW = dt.datetime(2026, 11, 16, 12, 0, tzinfo=dt.timezone.utc)
HEAD = ["team", "season", "name", "gameId", "playerTeam", "opposingTeam", "situation", mt.FF, mt.FA]


def log(team, games, bump=0.0):
    """A team's game log as MoneyPuck serves it: one row per situation per game. games: [(game id, for, against)]."""
    rows = []
    for gid, ff, fa in games:
        for sit, k in (("other", 0.1), ("all", 1.0), ("5on5", 0.8)):
            rows.append([team, gid // 1_000_000, team, gid, team, "XXX", sit, round((ff + bump) * k, 3), round(fa * k, 3)])
    buf = io.StringIO()
    pd.DataFrame(rows, columns=HEAD).to_csv(buf, index=False)
    return buf.getvalue().encode()


class Refresh(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.keep = mt.DIR, mt.TEAMS, mt._get, mt.GENTLE_S
        mt.DIR, mt.TEAMS, mt.GENTLE_S = self.d, ["TOR", "T.B", "FLA"], 0.0
        self.asked, self.bump, self.down = [], 0.0, set()

        def get(url, timeout=20):
            team = url.rsplit("/", 1)[1].replace(".csv", "")
            self.asked.append(team)
            if team in self.down:
                raise OSError("HTTP 503")
            return log(team, [(2025020900, 40.0, 38.0), (2026020001, 41.5, 36.25), (2026020300, 44.0, 39.5)], self.bump)
        mt._get = get

    def tearDown(self):
        mt.DIR, mt.TEAMS, mt._get, mt.GENTLE_S = self.keep
        shutil.rmtree(self.d)

    def run_(self, now=NOW, **kw):
        self.asked.clear()
        import contextlib
        with contextlib.redirect_stdout(io.StringIO()):
            return mt.refresh(now=now, **kw)

    def test_parse_log_keeps_this_seasons_all_situations_rows(self):
        x = mt.parse_log(log("T.B", [(2025020900, 40.0, 38.0), (2026020001, 41.5, 36.25)]), 2026)
        self.assertEqual(x.to_dict("records"), [{"game_id": 2026020001, "team_abbrev": "TBL", "mp_ff": 41.5, "mp_fa": 36.25}])
        with self.assertRaises(Exception):
            mt.parse_log(b"<html>blocked</html>", 2026)

    def test_first_run_pulls_every_team_and_keeps_the_four_numbers(self):
        st = self.run_()
        self.assertEqual(sorted(self.asked), ["FLA", "T.B", "TOR"])
        rec = mt.read_recent()
        self.assertEqual(len(rec), 6)                                        # two games this season for each of three teams
        self.assertEqual(sorted(rec.team_abbrev.unique()), ["FLA", "TBL", "TOR"])            # MoneyPuck's old dotted code is mapped
        self.assertEqual(list(rec.columns), mt.COLS)
        self.assertTrue(all(str(v).startswith("ok") for v in st.values()))
        with open(mt.status_path()) as f:
            js = json.load(f)
        self.assertEqual((sorted(js["teams_at"]), js["recent_rows"]), (["FLA", "T.B", "TOR"], 6))
        self.assertEqual(os.listdir(self.d).count("attempts_recent.csv"), 1)
        self.assertFalse([f for f in os.listdir(self.d) if f.endswith(".gz") or f.endswith(".tmp")])   # no big logs are written

    def test_a_team_is_pulled_at_most_once_in_twenty_hours(self):
        self.run_()
        # a fresh checkout: every file is "new" by its age; the committed pull times still say it is too early
        for f in os.listdir(self.d):
            os.utime(os.path.join(self.d, f), (0, 0))
        st = self.run_(NOW + dt.timedelta(hours=mt.MAX_AGE_H - 1))
        self.assertEqual((self.asked, set(st.values())), ([], {"fresh"}))
        self.bump = 1.0                                                      # MoneyPuck revised its numbers overnight
        self.run_(NOW + dt.timedelta(hours=mt.MAX_AGE_H + 1))
        self.assertEqual(len(self.asked), 3)
        rec = mt.read_recent()
        self.assertEqual(len(rec), 6)                                        # replaced, never doubled
        self.assertEqual(float(rec[(rec.team_abbrev == "TOR") & (rec.game_id == 2026020001)].mp_ff.iloc[0]), 42.5)

    def test_a_failed_team_keeps_its_rows_and_stays_due(self):
        self.run_()
        self.down = {"FLA"}
        later = NOW + dt.timedelta(hours=mt.MAX_AGE_H + 1)
        st = self.run_(later)
        self.assertTrue(st["team_games_FLA"].startswith("failed"))
        self.assertEqual(len(mt.read_recent()), 6)                           # its earlier rows are still there
        with open(mt.status_path()) as f:
            at = json.load(f)["teams_at"]
        self.assertEqual((at["FLA"], at["TOR"]), (NOW.isoformat(timespec="seconds"), later.isoformat(timespec="seconds")))
        self.down = set()
        self.run_(later + dt.timedelta(minutes=15))                          # the next build retries only that team
        self.assertEqual(self.asked, ["FLA"])

    def test_a_dead_source_is_given_up_on(self):
        mt.TEAMS = [f"T{i:02d}" for i in range(12)]
        self.down = set(mt.TEAMS)
        st = self.run_()
        self.assertLessEqual(len(self.asked), mt.MAX_FAILS + 4)              # a few in flight, then it stops asking
        self.assertTrue(any(v.startswith("skipped") for v in st.values()))
        self.assertIsNone(mt.read_recent())

    def test_force_and_unreadable_state(self):
        self.run_()
        self.run_(NOW + dt.timedelta(minutes=5), force=True)
        self.assertEqual(len(self.asked), 3)
        with open(mt.status_path(), "w") as f:
            f.write("not json")
        self.run_(NOW + dt.timedelta(minutes=10))                            # no readable pull times: everything is due
        self.assertEqual(len(self.asked), 3)
        self.assertTrue(mt.due({}, "TOR", NOW)); self.assertTrue(mt.due({"TOR": "yesterday"}, "TOR", NOW))
        self.assertFalse(mt.due({"TOR": NOW.isoformat()}, "TOR", NOW + dt.timedelta(hours=1)))

    def test_attempts_joins_the_snapshot_and_the_recent_file(self):
        self.assertIsNone(mt.attempts())                                     # neither piece: the model uses its own counts
        import gzip
        with gzip.open(mt.path("team_games_TOR"), "wb") as f:               # the committed snapshot: one old and one early game
            f.write(log("TOR", [(2025020900, 40.0, 38.0), (2026020001, 41.0, 36.0)]))
        a = mt.attempts()
        self.assertEqual(sorted(a.game_id), [2025020900, 2026020001])
        self.run_()                                                          # the recent file now has 2026020001 (revised) and a new game
        a = mt.attempts().set_index(["game_id", "team_abbrev"])
        self.assertEqual(float(a.loc[(2026020001, "TOR")].mp_ff), 41.5)      # the recent number wins
        self.assertEqual(float(a.loc[(2025020900, "TOR")].mp_ff), 40.0)      # history comes from the snapshot
        self.assertIn((2026020300, "TOR"), a.index)
        self.assertEqual(len(a), 3 + 4)                                      # TOR's three games, two each for the others
        tg = pd.DataFrame({"game_id": [2026020300, 2026020999], "team_abbrev": ["TOR", "TOR"], "mp_ff": [1.0, 1.0]})
        out = mt.with_attempts(tg)
        self.assertEqual(float(out.mp_ff.iloc[0]), 44.0)
        self.assertTrue(pd.isna(out.mp_ff.iloc[1]))                          # a game MoneyPuck has not posted yet


if __name__ == "__main__":
    unittest.main()
