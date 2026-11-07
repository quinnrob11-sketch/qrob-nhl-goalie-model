"""PrizePicks /projections -> board: shots and points lines matched within the team, standard lines only,
labelled with the real fetch time; a failed pull falls back to the last good board, labelled."""
import datetime as dt
import json
import os
import shutil
import tempfile
import unittest

import prizepicks as pp
import sources
from tests.test_pick6 import NOW, R, SLATE


def proj(pid, player, stat, line, **a):
    return {"id": str(pid), "type": "projection",
            "attributes": {"stat_type": stat, "line_score": line, "odds_type": a.pop("odds_type", "standard"),
                           "start_time": "2026-11-03T19:00:00-05:00", **a},
            "relationships": {"new_player": {"data": {"id": player, "type": "new_player"}}}}


JS = {"data": [proj(1, "p1", "Shots On Goal", 3.5), proj(2, "p1", "Points", 0.5), proj(3, "p2", "Shots On Goal", 1.5),
               proj(4, "p1", "Shots On Goal", 2.5, odds_type="goblin"), proj(5, "p1", "Shots On Goal", 4.5, is_promo=True),
               proj(6, "p3", "Shots On Goal", 2.5), proj(7, "p4", "Goalie Saves", 26.5), proj(8, "p1", "Hits", 1.5)],
      "included": [{"id": "p1", "type": "new_player", "attributes": {"name": "Mitch Marner", "team": "TOR"}},
                   {"id": "p2", "type": "new_player", "attributes": {"name": "Anders Lee", "team": "UTAH"}},
                   {"id": "p3", "type": "new_player", "attributes": {"name": "Nobody Atall", "team": "TOR"}},
                   {"id": "p4", "type": "new_player", "attributes": {"name": "Joseph Woll", "team": "TOR"}}]}


class Props(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.c, pp.CACHE = pp.CACHE, os.path.join(self.d, "pp.json")
        self.js = pp.last_js

    def tearDown(self):
        pp.CACHE, pp.last_js = self.c, self.js
        shutil.rmtree(self.d)

    def test_parse_props(self):
        rows, drops = pp.parse_props(JS, SLATE, R, "2026-11-03T20:00:00+00:00", NOW)
        got = sorted((r["player_id"], r["market"], r["line"], r["team"]) for r in rows)
        self.assertEqual(got, [(8475314, "sog", 1.5, "UTA"), (8478483, "points", 0.5, "TOR"), (8478483, "sog", 3.5, "TOR")])
        self.assertTrue(all(r["source"] == "PrizePicks" and (r["mo"], r["mu"]) == (1.0, 1.0) for r in rows))
        self.assertTrue(all(r["fetched_at"] == "2026-11-03T20:00:00+00:00" for r in rows))
        self.assertEqual(drops, {"unmatched player": 1})                     # goblin, promo, saves, hits never enter
        self.assertEqual([r["name"] for r in pp.props_review], ["Nobody Atall"])

    def test_fresh_then_fallback_then_error(self):
        pp.last_js, pp.last_error = JS, None
        rows = pp.props(SLATE, R, NOW)
        self.assertEqual((pp.props_status, pp.props_fetched_at, len(rows)), ("fresh", NOW.isoformat(timespec="seconds"), 3))
        later = NOW + dt.timedelta(minutes=40)
        pp.last_js, pp.last_error = None, "HTTP 403: PrizePicks blocks requests from cloud servers"
        rows = pp.props(SLATE, R, later)
        self.assertEqual((pp.props_status, pp.props_fetched_at), ("fallback", NOW.isoformat(timespec="seconds")))
        self.assertEqual({r["fetched_at"] for r in rows}, {NOW.isoformat(timespec="seconds")})   # never the later build's time
        self.assertTrue(sources.info(pp.props_status, pp.props_fetched_at, later, pp.last_error)["stale"])
        os.remove(pp.CACHE)
        self.assertEqual((pp.props(SLATE, R, later), pp.props_status), ([], "error"))

    def test_saves_path_unchanged(self):
        self.assertEqual([(r["name"], r["line"], r["team"]) for r in pp.parse(JS)], [("Joseph Woll", 26.5, "TOR")])


class OnTheBoard(unittest.TestCase):
    def test_prizepicks_rows_are_scored_and_labelled(self):
        import props_board as pb
        from tests.test_board import PLAYERS, p6, payload
        at = dt.datetime(2026, 11, 3, 20, 0, tzinfo=dt.timezone.utc)
        pl = payload(PLAYERS); pl["sources_at"] = at.isoformat()
        pl["sources"] = {"pp": {"status": "fallback"}}
        row = {**p6(10, "Mitch Marner", "TOR", 2.5), "source": "PrizePicks", "fetched_at": (at - dt.timedelta(minutes=45)).isoformat()}
        b = pb.build(pl, [row, p6(20, "Sam Reinhart", "FLA", 1.5)], at - dt.timedelta(hours=2))
        r = next(x for x in b["rows"] if x["source"] == "PrizePicks")
        self.assertIsNotNone(r["p"]); self.assertIn(r["verdict"], ("TAKE MORE", "TAKE LESS", "PASS"))
        self.assertEqual((r["stale"], r["fallback"], r["age_min"]), (True, True, 45.0))
        self.assertFalse(next(x for x in b["rows"] if x["source"] == "Pick6")["fallback"])


if __name__ == "__main__":
    unittest.main()
