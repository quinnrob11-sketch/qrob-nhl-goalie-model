"""Nothing to pull is not a failed pull. Late at night every game has started and the next slate is most of a day
away: an empty answer from an app or a book is then the true answer ("fresh", no lines), not a "fallback" or a
"parse failed" that raises the stale-data banner for hours. A pull that fails, or comes back empty with a game close,
is still a failure."""
import datetime as dt
import os
import shutil
import tempfile
import unittest

import odds
import pick6
import prizepicks as pp
import sources

NOW = dt.datetime(2026, 11, 16, 6, 0, tzinfo=dt.timezone.utc)          # midnight in Chicago
ISO = lambda t: t.isoformat(timespec="seconds").replace("+00:00", "Z")


def game(gid, hours, state="FUT"):
    return {"id": gid, "date": "2026-11-16", "start": ISO(NOW + dt.timedelta(hours=hours)), "home": "FLA", "away": "TOR", "state": state}


class Pick6Idle(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.keep = pick6.CACHE, pick6._pull, pick6.status, pick6.fetch_status, pick6.fetched_at
        pick6.CACHE = os.path.join(self.d, "p6.json")

    def tearDown(self):
        pick6.CACHE, pick6._pull, pick6.status, pick6.fetch_status, pick6.fetched_at = self.keep
        shutil.rmtree(self.d)

    def test_nothing_open(self):
        none = {"raw": 0, "kept": 0, "dropped": {}}
        self.assertTrue(pick6.nothing_open([game(1, -3, "LIVE"), game(2, 19)], none, NOW))       # under way, and tomorrow night
        self.assertTrue(pick6.nothing_open([game(1, -5, "OFF")], none, NOW))
        self.assertTrue(pick6.nothing_open([], none, NOW))
        self.assertFalse(pick6.nothing_open([game(1, -3, "LIVE"), game(2, 11)], none, NOW))      # one starts within 12 hours
        self.assertFalse(pick6.nothing_open([game(1, pick6.OPEN_WITHIN_H)], none, NOW))
        self.assertTrue(pick6.nothing_open([game(1, pick6.OPEN_WITHIN_H + .1)], none, NOW))
        self.assertFalse(pick6.nothing_open([{**game(1, 30), "start": "soon"}], none, NOW))      # no start time: cannot rule it out
        # every line the page had was for a game already under way: an empty board is the answer, whatever starts soon
        started = {"raw": 40, "kept": 0, "dropped": {"game started": 40}}
        self.assertTrue(pick6.nothing_open([game(1, 2)], started, NOW))
        self.assertFalse(pick6.nothing_open([game(1, 2)], {"raw": 40, "kept": 0, "dropped": {"game started": 30, "unmatched player": 10}}, NOW))
        self.assertFalse(pick6.nothing_open([game(1, 2)], {"raw": 0, "kept": 0, "dropped": {}}, NOW))
        self.assertFalse(pick6.nothing_open([game(1, 2)], None, NOW))

    def test_an_empty_pull_with_nothing_open_is_fresh(self):
        def empty(slate, R, timeout=30):
            pick6.status = "parse failed: 0 rows"
            return [], {"raw": 0, "kept": 0, "dropped": {}}
        pick6._pull = empty
        with open(pick6.CACHE, "w") as f:                                    # a last good board exists and must not be reused
            f.write('{"at": "2026-11-15T23:00:00+00:00", "rows": [{"game": 2, "player_id": 1, "market": "sog", "line": 2.5}]}')
        rows, st = pick6.fetch([game(1, -3, "LIVE"), game(2, 19)], None, now=NOW)
        self.assertEqual((rows, st.get("idle"), pick6.fetch_status, pick6.status), ([], True, "fresh", "ok"))
        self.assertEqual(pick6.fetched_at, NOW.isoformat(timespec="seconds"))
        self.assertFalse(sources.info(pick6.fetch_status, pick6.fetched_at, NOW)["stale"])

    def test_a_request_that_failed_is_a_failure_at_any_hour(self):
        def blocked(slate, R, timeout=30):
            pick6.status = "blocked (HTTP 403)"
            return [], {}
        pick6._pull = blocked
        rows, st = pick6.fetch([game(1, -3, "LIVE"), game(2, 19)], None, now=NOW)
        self.assertEqual((rows, pick6.fetch_status, pick6.status), ([], "error", "blocked (HTTP 403)"))
        self.assertNotIn("idle", st)

    def test_an_empty_pull_with_a_game_close_is_still_a_failure(self):
        def empty(slate, R, timeout=30):
            pick6.status = "parse failed: 0 rows"
            return [], {"raw": 0, "kept": 0, "dropped": {}}
        pick6._pull = empty
        rows, st = pick6.fetch([game(2, 5)], None, now=NOW)
        self.assertEqual((rows, pick6.fetch_status, pick6.status), ([], "error", "parse failed: 0 rows"))
        self.assertNotIn("idle", st)


class OddsIdle(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.keep = odds.CACHE, odds._get, odds.fetch_moneylines, os.environ.get("ODDS_API_KEY")
        odds.CACHE = os.path.join(self.d, "odds.json")
        odds.fetch_moneylines = lambda key: []
        os.environ["ODDS_API_KEY"] = "test-key-not-real"
        self.asked = []

    def tearDown(self):
        odds.CACHE, odds._get, odds.fetch_moneylines, key = self.keep
        if key is None:
            os.environ.pop("ODDS_API_KEY", None)
        else:
            os.environ["ODDS_API_KEY"] = key
        shutil.rmtree(self.d)

    def events(self, *hours, odds_js=None, fail=False):
        evs = [{"id": f"e{i}", "commence_time": ISO(NOW + dt.timedelta(hours=h)), "home_team": "Florida Panthers",
                "away_team": "Toronto Maple Leafs"} for i, h in enumerate(hours)]

        def get(url, params):
            self.asked.append(url)
            if url.endswith("/events"):
                if fail:
                    raise OSError("HTTP 500")
                return evs
            return odds_js if odds_js is not None else {"bookmakers": []}
        odds._get = get

    def test_no_game_in_the_window(self):
        self.events(-3, 30)                                                  # one under way, one tomorrow night
        self.assertEqual(odds.fetch([], NOW), [])
        self.assertTrue(odds.idle)
        self.assertEqual((odds.status, odds.fetched_at, odds.last_error), ("fresh", NOW.isoformat(timespec="seconds"), None))
        self.assertEqual(len(self.asked), 1)                                 # the events list only: no credits spent
        self.assertFalse(sources.info(odds.status, odds.fetched_at, NOW, odds.last_error)["stale"])

    def test_no_lines_posted_yet_for_a_game_half_a_day_off(self):
        self.events(-3, 17)                                                  # in the window, more than 12 hours away
        self.assertEqual(odds.fetch([], NOW), [])
        self.assertTrue(odds.idle)
        self.assertEqual((odds.status, odds.last_error), ("fresh", None))
        self.assertEqual(len(self.asked), 2)                                 # it did ask; no book had a line

    def test_no_lines_with_a_game_close_is_a_failure(self):
        self.events(5)
        self.assertEqual(odds.fetch([], NOW), [])
        self.assertFalse(odds.idle)
        self.assertEqual(odds.status, "error")                               # no last good pull to fall back to
        self.assertTrue(sources.info(odds.status, odds.fetched_at, NOW, odds.last_error)["stale"])

    def test_a_failed_request_is_never_idle(self):
        self.events(30, fail=True)
        odds.fetch([], NOW)
        self.assertFalse(odds.idle)
        self.assertEqual((odds.status, odds.last_error), ("error", "HTTP 500"))


class PrizePicksIdle(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.keep = pp.CACHE, pp.last_js, pp.last_error, pp.props_status, pp.props_fetched_at
        pp.CACHE = os.path.join(self.d, "pp.json")
        pp.last_js = None

    def tearDown(self):
        pp.CACHE, pp.last_js, pp.last_error, pp.props_status, pp.props_fetched_at = self.keep
        shutil.rmtree(self.d)

    def test_follows_the_odds_pull(self):
        at = NOW.isoformat(timespec="seconds")
        with open(pp.CACHE, "w") as f:                                       # a last good board exists and must not be reused
            f.write('{"at": "2026-11-15T23:00:00+00:00", "rows": [{"game": 2, "player_id": 1, "market": "sog", "line": 2.5, "fetched_at": "2026-11-15T23:00:00+00:00"}]}')
        rows = pp.props([game(2, 19)], None, NOW, odds_rows=[], odds_status="fresh", odds_at=at, odds_idle=True)
        self.assertEqual((rows, pp.props_status, pp.props_fetched_at), ([], "fresh", at))
        # the odds pull itself failed (or was not idle): the last good board, labelled
        rows = pp.props([game(2, 19)], None, NOW, odds_rows=[], odds_status="fallback", odds_at=at, odds_idle=True)
        self.assertEqual(pp.props_status, "fallback")
        rows = pp.props([game(2, 19)], None, NOW, odds_rows=[], odds_status="fresh", odds_at=at, odds_idle=False)
        self.assertEqual(pp.props_status, "fallback")


if __name__ == "__main__":
    unittest.main()
