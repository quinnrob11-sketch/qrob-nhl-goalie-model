"""The day's Pick6 board (pick6.merge_day). Pick6's page serves one category per request: sometimes a stat's full
list, sometimes only its featured picks. Lines an earlier pull saw are kept with their own fetch time and reused=True
when this pull's page says nothing about them; a reused line is never a play, a near miss or a lean."""
import datetime as dt
import os
import tempfile
import unittest

import pick6
import pricing
import props_board as pb
import sources
from tests.test_board import PLAYERS, p6, payload

NOW = dt.datetime(2026, 11, 10, 18, 25, tzinfo=dt.timezone.utc)
SLATE = [{"id": 1, "date": "2026-11-10", "start": "2026-11-11T00:00:00Z", "home": "FLA", "away": "TOR", "state": "FUT"},
         {"id": 2, "date": "2026-11-10", "start": "2026-11-10T17:00:00Z", "home": "BOS", "away": "NYR", "state": "LIVE"}]
CATS = {"31": ["shots-on-goal", "Shots On Goal", "31"], "16": ["pts", "Points", "16"]}
SOG, FEATURED = {"category": 31, "categories": CATS}, {"category": 1, "categories": CATS}


def line(pid, ln, market="sog", game=1, at="2026-11-10T16:09:00+00:00", **kw):
    return {"name": f"P{pid}", "player_id": pid, "team": "TOR", "game": game, "date": "2026-11-10", "market": market,
            "line": ln, "mo": 1.0, "mu": 1.0, "source": "Pick6", "fetched_at": at, "pos": "F", **kw}


class MergeDay(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "day.json")

    def merge(self, rows, info, now=NOW):
        return pick6.merge_day(rows, info, SLATE, now, self.path)

    def test_featured_pull_keeps_the_players_it_leaves_out(self):
        full = [line(1, 2.5), line(1, 3.5, mu=0.0), line(2, 1.5), line(3, 2.5)]
        rows, st = self.merge(full, SOG, NOW - dt.timedelta(hours=2, minutes=16))
        self.assertEqual((len(rows), st["full"], st["reused"], st["category_name"]), (4, ["sog"], 0, "Shots On Goal"))
        # two hours later the page shows only player 1 (a new line) and a points card for player 2
        now = [line(1, 3.0, at="2026-11-10T18:25:00+00:00"), line(2, 0.5, market="points", at="2026-11-10T18:25:00+00:00")]
        rows, st = self.merge(now, FEATURED)
        self.assertEqual((st["full"], st["reused"], st["category_name"]), ([], 2, None))
        got = {(r["player_id"], r["market"], r["line"]): r.get("reused", False) for r in rows}
        self.assertEqual(got, {(1, "sog", 3.0): False, (2, "points", 0.5): False,    # this pull's own lines
                               (2, "sog", 1.5): True, (3, "sog", 2.5): True})         # kept; player 1's old shots lines are replaced
        kept = next(r for r in rows if r["player_id"] == 3)
        self.assertEqual(kept["fetched_at"], "2026-11-10T16:09:00+00:00")           # its own fetch time, never this build's

    def test_a_stats_full_list_replaces_everything_known_about_it(self):
        self.merge([line(1, 2.5), line(2, 1.5), line(2, 0.5, market="points")], FEATURED, NOW - dt.timedelta(hours=1))
        rows, st = self.merge([line(1, 2.5, at="2026-11-10T18:25:00+00:00")], SOG)
        # player 2 is off the full shots list (pulled by Pick6): his old shots line goes, his points line stays
        self.assertEqual(sorted((r["player_id"], r["market"], r.get("reused", False)) for r in rows), [(1, "sog", False), (2, "points", True)])
        self.assertEqual(st["full"], ["sog"])

    def test_old_started_and_off_slate_lines_are_dropped(self):
        self.merge([line(1, 2.5, at="2026-11-10T05:00:00+00:00"),                   # more than REUSE_MAX_H ago
                    line(2, 1.5, game=2), line(3, 2.5, game=99), line(4, 2.5)], FEATURED, NOW - dt.timedelta(hours=13))
        rows, st = self.merge([line(9, 0.5, market="points", at="2026-11-10T18:25:00+00:00")], FEATURED)
        self.assertEqual([r["player_id"] for r in rows if r.get("reused")], [4])

    def test_reused_lines_carry_on_through_later_pulls(self):
        self.merge([line(1, 2.5)], SOG, NOW - dt.timedelta(hours=2))
        self.merge([line(9, 0.5, market="points", at="2026-11-10T17:25:00+00:00")], FEATURED, NOW - dt.timedelta(hours=1))
        rows, _ = self.merge([line(8, 0.5, market="points", at="2026-11-10T18:25:00+00:00")], FEATURED)
        self.assertEqual(sorted((r["player_id"], r.get("reused", False)) for r in rows), [(1, True), (8, False), (9, True)])

    def test_fallback_pull_adds_the_days_lines(self):
        # the pull fails outright: the last good board plus the day's other lines, all with their own times
        cache, pull = pick6.CACHE, pick6._pull
        pick6.CACHE = os.path.join(os.path.dirname(self.path), "p6.json")
        try:
            pick6._pull = lambda slate, R, timeout=30: ([line(1, 2.5), line(2, 1.5)], {"raw": 2, "kept": 2, "dropped": {}})
            pick6.last_info = SOG
            pick6.fetch(SLATE, None, now=NOW - dt.timedelta(hours=2))
            pick6._pull = lambda slate, R, timeout=30: ([line(1, 3.0, at="2026-11-10T17:25:00+00:00")], {"raw": 1, "kept": 1, "dropped": {}})
            pick6.last_info = FEATURED
            rows, st = pick6.fetch(SLATE, None, now=NOW - dt.timedelta(hours=1))
            self.assertEqual((pick6.fetch_status, st["reused"], len(rows)), ("fresh", 1, 2))
            pick6._pull = lambda slate, R, timeout=30: ([], {"raw": 0, "kept": 0, "dropped": {}})
            rows, st = pick6.fetch(SLATE, None, now=NOW)
            self.assertEqual(pick6.fetch_status, "fallback")
            self.assertEqual(sorted((r["player_id"], r["line"]) for r in rows), [(1, 3.0), (2, 1.5)])
        finally:
            pick6.CACHE, pick6._pull = cache, pull


class ReusedLines(unittest.TestCase):
    """Downstream: a reused line is labelled, is never a play or a lean, and cannot name itself as fresh."""
    DK = [{"name": "M. Marner", "player_id": 10, "teams": ["TOR", "FLA"], "date": "2026-11-03", "line": 2.5, "over": -300, "under": 230}]

    def test_never_a_play(self):
        fresh = pb.build(payload(PLAYERS, self.DK), [p6(10, "Mitch Marner", "TOR", 2.5)])["rows"][0]
        self.assertEqual(fresh["verdict"], "TAKE MORE")
        pl = payload(PLAYERS, self.DK); pl["sources"] = {"pick6": {"status": "fresh"}, "dk": {"status": "fresh"}}
        b = pb.build(pl, [{**p6(10, "Mitch Marner", "TOR", 2.5), "reused": True}])
        r = b["rows"][0]
        self.assertEqual((r["verdict"], r["cached"], r["fallback"]), ("PASS", True, True))
        self.assertTrue(r["reason"].startswith("cached Pick6 line (from an earlier pull today)"))
        self.assertGreaterEqual(r["p"], pricing.take_p("sog"))                       # the number is unchanged, only the call
        self.assertEqual((r["pick_tier"], r["lean"], b["counts"]["takes"], b["picks"]), ("", False, 0, []))

    def test_label_rows_marks_it_not_this_builds(self):
        rows = sources.label_rows([{"source": "Pick6", "fetched_at": "2026-11-10T16:09:00+00:00", "reused": True},
                                   {"source": "Pick6", "fetched_at": "2026-11-10T18:25:00+00:00"}], NOW, {"pick6": {"status": "fresh"}})
        self.assertEqual([r["fallback"] for r in rows], [True, False])
        self.assertAlmostEqual(rows[0]["age_min"], 136, delta=1)


if __name__ == "__main__":
    unittest.main()
