"""PrizePicks through The Odds API (bookmaker "prizepicks"): pulled in the same request as DraftKings at no
extra cost, matched within the game, standard lines scored as 1x DFS legs, demons / goblins priced at their odds."""
import datetime as dt
import os
import shutil
import tempfile
import unittest

import odds
import prizepicks as pp
from tests.test_pick6 import NOW, R, SLATE

EV = {"id": "e1", "home_team": "Florida Panthers", "away_team": "Toronto Maple Leafs", "commence_time": "2026-11-04T00:00:00Z"}


def outc(name, side, point, price):
    return {"name": side, "description": name, "point": point, "price": price}


JS = {"bookmakers": [
    {"key": "draftkings", "markets": [{"key": "player_shots_on_goal", "outcomes": [outc("Mitch Marner", "Over", 3.5, 110), outc("Mitch Marner", "Under", 3.5, -150)]}]},
    {"key": "prizepicks", "markets": [
        {"key": "player_shots_on_goal", "outcomes": [outc("Mitch Marner", "Over", 3.5, -137), outc("Mitch Marner", "Under", 3.5, -137),
                                                     outc("Nobody Atall", "Over", 1.5, -137)]},
        {"key": "player_points", "outcomes": [outc("Mitch Marner", "Over", 0.5, -137), outc("Mitch Marner", "Under", 0.5, -137)]},
        {"key": "player_total_saves", "outcomes": [outc("Joseph Woll", "Over", 26.5, -137), outc("Joseph Woll", "Under", 26.5, -137)]},
        {"key": "player_shots_on_goal_alternate", "outcomes": [outc("Mitch Marner", "Over", 1.5, -400), outc("Mitch Marner", "Over", 5.5, 250)]}]}]}


class OddsPrizePicks(unittest.TestCase):
    def test_parse_by_book(self):
        dk = odds.parse_event(EV, JS, odds.SOG_MARKET)
        self.assertEqual([(r["name"], r["line"], r["over"], r["source"]) for r in dk], [("Mitch Marner", 3.5, 110, "DK")])
        ppr = odds.parse_event(EV, JS, odds.SOG_MARKET, odds.PP_BOOK)
        self.assertEqual(sorted((r["name"], r["line"], r.get("over"), r.get("under")) for r in ppr),
                         [("Mitch Marner", 3.5, -137, -137), ("Nobody Atall", 1.5, -137, None)])
        alts = odds.parse_event(EV, JS, odds.SOG_MARKET + "_alternate", odds.PP_BOOK)
        self.assertEqual(sorted(r["line"] for r in alts), [1.5, 5.5])            # several lines per player

    def test_one_request_both_books_no_extra_markets(self):
        seen = []
        def fake_get(url, params):
            seen.append((url, dict(params)))
            if url.endswith("/events"):
                return [EV]
            return JS if "/events/e1/odds" in url else []
        old, os.environ["ODDS_API_KEY"] = odds._get, "dummy"
        os.environ.pop("ODDS_PP_ALT", None)
        odds._get = fake_get
        try:
            odds._fetch([], dt.datetime(2026, 11, 3, 20, 0, tzinfo=dt.timezone.utc), R)
        finally:
            odds._get = old
            os.environ.pop("ODDS_API_KEY")
        ev = [p for u, p in seen if "/events/e1/odds" in u]
        self.assertEqual(len(ev), 1)
        books = ev[0]["bookmakers"].split(",")
        self.assertEqual(books[:2], ["draftkings", "prizepicks"])
        self.assertLessEqual(len(books), 10)                                      # <= 10 books = 1 region: same cost
        self.assertEqual(ev[0]["markets"], "player_total_saves,player_shots_on_goal,player_points")
        self.assertNotIn("regions", ev[0])
        got = sorted((r["market"], r["name"], r["line"], r["match"]) for r in odds.pp_rows)
        self.assertEqual(got, [("points", "Mitch Marner", 0.5, "MATCHED"), ("saves", "Joseph Woll", 26.5, "MATCHED"),
                               ("sog", "Mitch Marner", 3.5, "MATCHED"), ("sog", "Nobody Atall", 1.5, "UNMATCHED")])
        self.assertEqual(next(r for r in odds.pp_rows if r["market"] == "saves")["player_id"], 8479361)

    def test_other_books_and_rejected_list(self):
        js = {"bookmakers": JS["bookmakers"] + [{"key": "fanduel", "markets": [{"key": "player_shots_on_goal", "outcomes": [
            outc("Mitch Marner", "Over", 2.5, -125), outc("Mitch Marner", "Under", 2.5, 105), outc("Joseph Woll", "Over", 1.5, -110)]}]}]}
        seen = []
        def fake_get(url, params):
            seen.append(dict(params))
            if url.endswith("/events"):
                return [EV]
            if "/events/e1/odds" in url and len(params["bookmakers"].split(",")) > 2:
                import urllib.error
                raise urllib.error.HTTPError(url, 422, "invalid bookmaker", {}, None)
            return js if "/events/e1/odds" in url else []
        old, os.environ["ODDS_API_KEY"] = odds._get, "dummy"
        odds._get = fake_get
        try:
            odds._fetch([], dt.datetime(2026, 11, 3, 20, 0, tzinfo=dt.timezone.utc), R)
            self.assertEqual([p["bookmakers"] for p in seen if "markets" in p][-1], "draftkings,prizepicks")
            # with the full list accepted, FanDuel's two-sided line comes through matched; one-sided lines are dropped
            odds._get = lambda url, params: [EV] if url.endswith("/events") else (js if "/events/e1/odds" in url else [])
            odds._fetch([], dt.datetime(2026, 11, 3, 20, 0, tzinfo=dt.timezone.utc), R)
            fd = [(r["book"], r["market"], r["line"], r["player_id"]) for r in odds.book_rows]
            self.assertEqual(fd, [("FanDuel", "sog", 2.5, 8478483)])
        finally:
            odds._get = old
            os.environ.pop("ODDS_API_KEY")

    def test_board_rows_and_precedence(self):
        at = "2026-11-03T20:00:00+00:00"
        rows = [{"name": "Mitch Marner", "teams": ["TOR", "FLA"], "line": 3.5, "over": -137, "under": -137, "market": "sog",
                 "start": "2026-11-04T00:00:00Z", "player_id": 8478483, "team": "TOR", "match": "MATCHED", "fetched_at": at},
                {"name": "Mitch Marner", "teams": ["TOR", "FLA"], "line": 5.5, "over": 250, "market": "sog", "alt": True,
                 "start": "2026-11-04T00:00:00Z", "player_id": 8478483, "team": "TOR", "match": "MATCHED", "fetched_at": at},
                {"name": "Nobody Atall", "teams": ["TOR", "FLA"], "line": 1.5, "over": -137, "market": "sog", "match": "UNMATCHED",
                 "match_reason": "no TOR/FLA player named Nobody Atall", "start": "2026-11-04T00:00:00Z"}]
        d = tempfile.mkdtemp(); c, pp.CACHE = pp.CACHE, os.path.join(d, "pp.json"); js, pp.last_js = pp.last_js, None
        try:
            out = pp.props(SLATE, R, NOW, odds_rows=rows, odds_status="fresh", odds_at=at)
            std = next(r for r in out if not r.get("alt")); alt = next(r for r in out if r.get("alt"))
            self.assertEqual((std["mo"], std["mu"], std["source"], std["fetched_at"]), (1.0, 1.0, "PrizePicks", at))
            self.assertEqual((alt["mo"], alt["over"], alt["priced"]), (None, 250, True))
            self.assertEqual((pp.props_status, pp.props_fetched_at), ("fresh", at))
            self.assertEqual([r["name"] for r in pp.props_review], ["Nobody Atall"])
            self.assertTrue(os.path.exists(pp.CACHE))
            pp.last_js = {"data": [], "included": []}                              # PrizePicks' own API answered: it wins
            self.assertEqual(pp.props(SLATE, R, NOW, odds_rows=rows), [])
        finally:
            pp.CACHE, pp.last_js = c, js
            shutil.rmtree(d)

    def test_priced_rows_use_their_odds_on_the_board(self):
        import props_board as pb
        from tests.test_board import PLAYERS, p6, payload
        pl = payload(PLAYERS)
        alt = {**p6(10, "Mitch Marner", "TOR", 1.5), "source": "PrizePicks", "mo": None, "mu": None, "over": -400, "priced": True}
        std = {**p6(10, "Mitch Marner", "TOR", 2.5), "source": "PrizePicks"}
        b = pb.build(pl, [alt, std], dt.datetime(2026, 11, 3, 18, tzinfo=dt.timezone.utc))
        a = next(r for r in b["rows"] if r["line"] == 1.5)
        self.assertEqual(a["dk_over"], -400)
        self.assertAlmostEqual(a["be"], 0.8, places=3)                            # a -400 goblin needs 80%, not 57.7%


if __name__ == "__main__":
    unittest.main()
