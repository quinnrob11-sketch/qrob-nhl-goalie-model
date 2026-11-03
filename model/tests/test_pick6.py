"""Item 10: Pick6 page -> board rows with every required field; drops counted; 0 rows is a failure."""
import datetime as dt
import json
import os
import unittest

import pick6
import players
from tests.fixtures import make_pick6_fixture as fx
from tests.test_players import ROSTERS as BASE

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
R = players.Rosters({**BASE.teams, "TOR": BASE.teams["TOR"] + players.parse_roster(
    {"goalies": [{"id": 8479361, "firstName": {"default": "Joseph"}, "lastName": {"default": "Woll"}}]})})
SLATE = [{"id": 2026020101, "date": "2026-11-03", "start": "2026-11-04T00:00:00Z", "home": "FLA", "away": "TOR", "state": "FUT"},
         {"id": 2026020102, "date": "2026-11-03", "start": "2026-11-04T01:30:00Z", "home": "LAK", "away": "UTA", "state": "FUT"}]
NOW = dt.datetime(2026, 11, 3, 20, 0, tzinfo=dt.timezone.utc)


class TurboStream(unittest.TestCase):
    def test_round_trip(self):
        data = {"a": [1, 2.5, "x", None, {"b": True}], "c": {"d": "x"}}
        self.assertEqual(pick6.turbo_decode(fx.flatten(data)), data)

    def test_types_and_constants(self):
        vals = [{"_1": 2, "_3": -5, "_4": 5}, "when", ["D", 1700000000000], "gone", "set", ["S", 6], 7]
        self.assertEqual(pick6.turbo_decode(json.dumps(vals)), {"when": 1700000000000, "gone": None, "set": [7]})


class Board(unittest.TestCase):
    def setUp(self):
        self.page = fx.page()          # always the fixture the generator writes, so they can't drift
        with open(os.path.join(FIX, "pick6_synthetic.html")) as f:
            self.assertEqual(f.read(), self.page, "re-run make_pick6_fixture.py")

    def test_saved_snapshot_row_count(self):
        rows, st = pick6.build_rows(self.page, SLATE, R, "2026-11-03T20:00:00+00:00", NOW)
        self.assertEqual(st["raw"], 13)
        self.assertEqual(st["kept"], 10)
        self.assertEqual(st["dropped"], {"unmatched player": 1, "missing game": 1, "missing mo, mu": 1})
        self.assertEqual(len(rows), 10)
        for r in rows:
            for f in pick6.REQUIRED:
                self.assertNotIn(r[f], (None, ""), f)
        by = {(r["player_id"], r["market"], r["line"]): r for r in rows}
        self.assertIn((8478483, "sog", 3.5), by)                       # Marner's alt line is kept
        self.assertEqual(by[(8478483, "sog", 3.5)]["mo"], 1.25)
        self.assertEqual(by[(8475314, "sog", 1.5)]["team"], "UTA")      # Anders Lee
        self.assertEqual(by[(8481732, "sog", 1.5)]["team"], "LAK")      # Andre Lee, separately
        self.assertEqual(by[(8480801, "sog", 2.5)]["mu"], 1.1)          # Brady Tkachuk
        self.assertIn((8479361, "saves", 26.5), by)
        self.assertIn((8480801, "blocks", 0.5), by)
        self.assertEqual({r["game"] for r in rows}, {2026020101, 2026020102})

    def test_started_games_removed(self):
        late = dt.datetime(2026, 11, 4, 0, 30, tzinfo=dt.timezone.utc)
        slate = [dict(SLATE[0], state="LIVE"), SLATE[1]]
        rows, st = pick6.build_rows(self.page, slate, R, "x", late)
        self.assertTrue(all(r["game"] == 2026020102 for r in rows))
        self.assertEqual(st["dropped"]["game started"], 8)

    def test_empty_page_is_a_failure_not_an_empty_board(self):
        rows, st = pick6.build_rows("<html><body>Access Denied</body></html>", SLATE, R, "x", NOW)
        self.assertEqual((rows, st["raw"]), ([], 0))

    def test_remix_context_json(self):
        ctx = {"state": {"loaderData": fx.DATA["root"]["loaderData"]}}
        page = f"<script>window.__remixContext = {json.dumps(ctx)};</script>"
        rows, st = pick6.build_rows(page, SLATE, R, "x", NOW)
        self.assertEqual(st["kept"], 10)

    @unittest.skipUnless(os.path.exists(os.path.join(FIX, "pick6.html")), "no real Pick6 page saved yet")
    def test_real_saved_page(self):
        page = open(os.path.join(FIX, "pick6.html"), encoding="utf-8", errors="replace").read()
        self.assertGreater(len(pick6.extract(page)), 0, "parser found no props in the saved Pick6 page")


if __name__ == "__main__":
    unittest.main()
