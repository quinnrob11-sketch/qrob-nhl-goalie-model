"""Item 9: one explicit verdict per prop; never two TAKEs for a player; every PASS has a reason;
Today's plays is exactly the TAKE rows; the best of a player's lines is the one taken."""
import unittest

import pricing
import props_board


def payload(players, dk_sog=(), cal=None):
    prm = {"rate_hl": 60, "toi_hl": 8, "k_min": 100, "k_toi": 1, "carry": .7, "c_opp": 1, "home": 1.0, "disp": 12,
           "disp_k": 10, "b2b": 1, "opp_b2b": 1, "c_team": 0, "cal_a": 0, "cal_b": 1, "disp_edges": [], "disp_f": [], "disp_d": []}
    return {"slate": [{"id": 1, "date": "2026-11-03", "start": "2099-01-01T00:00:00Z", "home": "FLA", "away": "TOR", "state": "FUT"}],
            "sog": {"params": prm, "players": players, "opp": {}, "team": {}}, "points": {"params": prm, "opp": {}, "team": {}},
            "last_played": {}, "dk_sog": list(dk_sog), "dk_points": [], "dk": [],
            "calib": {"markets": {"sog": {"cal": cal or {"a": 0, "b": 1, "w": 0.0}}}}}


def p6(pid, name, team, line, mo=1.0, mu=1.0, market="sog"):
    return {"name": name, "player_id": pid, "team": team, "game": 1, "date": "2026-11-03", "market": market,
            "line": line, "mo": mo, "mu": mu, "source": "Pick6", "fetched_at": "x"}


# r60 x toi / 60 = projection: Marner 4.2, Nylander 0.9, Reinhart 1.0
PLAYERS = {"TOR": [{"id": 10, "name": "M. Marner", "pos": "F", "r60": 14.0, "toi": 18.0},
                   {"id": 11, "name": "W. Nylander", "pos": "F", "r60": 3.0, "toi": 18.0}],
           "FLA": [{"id": 20, "name": "S. Reinhart", "pos": "F", "r60": 3.0, "toi": 20.0}]}


class Verdicts(unittest.TestCase):
    def build(self, rows, dk=()):
        return props_board.build(payload(PLAYERS, dk), rows)

    def test_best_line_only_take(self):
        # DraftKings prices Marner at 2.5 (no-vig over 63%) and 3.5 (53%): only the 2.5 has the market's support
        dk = [{"name": "M. Marner", "teams": ["TOR", "FLA"], "date": "2026-11-03", "line": ln, "over": o, "under": u,
               "player_id": 10, "team": "TOR"} for ln, o, u in ((2.5, -200, 160), (3.5, -130, 100))]
        b = self.build([p6(10, "Mitch Marner", "TOR", 2.5), p6(10, "Mitch Marner", "TOR", 3.5), p6(10, "Mitch Marner", "TOR", 1.5, mo=0.8)], dk)
        m = [r for r in b["rows"] if r["player_id"] == 10 and r["source"] == "Pick6"]
        takes = [r for r in m if r["verdict"].startswith("TAKE")]
        self.assertEqual(len(takes), 1)
        self.assertEqual(takes[0]["line"], 2.5)
        alt = next(r for r in m if r["line"] == 3.5)
        self.assertEqual(alt["verdict"], "PASS"); self.assertIn("market only 53%", alt["reason"])
        self.assertIn("0.8x", next(r for r in m if r["line"] == 1.5)["reason"])

    def test_every_pass_has_a_reason_and_plays_match_table(self):
        b = self.build([p6(10, "Mitch Marner", "TOR", 3.5), p6(11, "William Nylander", "TOR", 0.5),
                        p6(20, "Sam Reinhart", "FLA", 1.5), p6(None, "Nobody", "TOR", 1.5),
                        p6(10, "Mitch Marner", "TOR", 0.5, market="blocks")])
        for r in b["rows"]:
            self.assertIn(r["verdict"], ("TAKE MORE", "TAKE LESS", "PASS"))
            if r["verdict"] == "PASS":
                self.assertTrue(r["reason"], r)
        self.assertEqual([(p["player_id"], p["line"]) for p in b["plays"]],
                         [(r["player_id"], r["line"]) for r in b["rows"] if r["verdict"].startswith("TAKE")])
        self.assertEqual(next(r for r in b["rows"] if r["name"] == "Nobody")["reason"], "needs review: unmatched or ambiguous player")
        per_player = {}
        for r in b["rows"]:
            if r["verdict"].startswith("TAKE"):
                per_player[(r["player_id"], r["market"])] = per_player.get((r["player_id"], r["market"]), 0) + 1
        self.assertTrue(all(v == 1 for v in per_player.values()))

    def test_market_driven_legs_pass(self):
        # DK prices Reinhart's 1.5 over at 70% no-vig, the model projects 1.0 shots: the 50/50 mean blend sits between
        # the two (expected shots ~1.7, near 50% at 1.5), so the market alone can't make it a TAKE
        dk = [{"name": "Sam Reinhart", "player_id": 20, "teams": ["TOR", "FLA"], "date": "2026-11-03", "line": 1.5, "over": -233, "under": 233}]
        b = self.build([p6(20, "Sam Reinhart", "FLA", 1.5)], dk)
        r = b["rows"][0]
        self.assertTrue(r["mean_blend"])
        self.assertAlmostEqual(r["p_mkt"], 0.70, places=2)
        self.assertLess(r["p_raw"], 0.40)                                   # the model alone leans under
        self.assertTrue(r["p_raw"] < r["p_blend"] < r["p_mkt"])
        self.assertGreater(r["mu_mkt"], r["proj"])
        self.assertEqual(r["verdict"], "PASS")
        self.assertLess(r["p"], pricing.take_p("sog"))

    def test_dk_fallback_priced_at_dk_odds(self):
        # Pick6 doesn't list Reinhart; DK's -233 over is the fallback. At w = 0 the blended p is DK's own no-vig
        # (70%), which can't beat the -233 price (70.0% implied plus vig), so it is never a free 1x TAKE
        dk = [{"name": "Sam Reinhart", "player_id": 20, "teams": ["TOR", "FLA"], "date": "2026-11-03", "line": 0.5, "over": -233, "under": 180}]
        b = self.build([], dk)
        r = b["rows"][0]
        self.assertEqual(r["source"], "DraftKings")
        self.assertEqual(r["verdict"], "PASS"); self.assertIn("break-even", r["reason"])

    def test_conflicting_teammates(self):
        rows = [{"name": "A", "player_id": 1, "team": "TOR", "opp": "FLA", "game": 1, "market": "sog", "label": "SOG",
                 "side": "OVER", "p": .64, "verdict": "TAKE MORE"},
                {"name": "B", "player_id": 2, "team": "TOR", "opp": "FLA", "game": 1, "market": "sog", "label": "SOG",
                 "side": "UNDER", "p": .60, "verdict": "TAKE LESS"},
                {"name": "G", "player_id": 3, "team": "TOR", "opp": "FLA", "game": 1, "market": "saves", "label": "Saves",
                 "side": "UNDER", "p": .61, "verdict": "TAKE LESS"},
                {"name": "C", "player_id": 4, "team": "FLA", "opp": "TOR", "game": 1, "market": "sog", "label": "SOG",
                 "side": "OVER", "p": .59, "verdict": "TAKE MORE"}]
        props_board.conflicts(rows)
        v = {r["name"]: r["verdict"] for r in rows}
        self.assertEqual(v, {"A": "TAKE MORE", "B": "PASS", "G": "TAKE LESS", "C": "PASS"})
        self.assertTrue(rows[1]["reason"].startswith("conflict"))
        self.assertTrue(rows[3]["reason"].startswith("conflict"))


class Rule(unittest.TestCase):
    def test_reasons(self):
        v = lambda *a, mk=.6, **k: pricing.verdict(*a, p_mkt_over=mk, **k)
        self.assertEqual(v("sog", .60, .58, 2.5, 3.0, 0.8, 1.2)["reason"], "pays 0.8x")
        self.assertEqual(v("sog", .40, .42, 2.5, 2.0, 1.7, 0.0)["reason"], "LESS not offered on this line")
        nm = v("sog", .60, .60, 2.5, 3.0, 1, 1, mk=.56)                     # SOG bar 62%: 59-62% is a near miss
        self.assertEqual((nm["reason"], nm["tier"]), ("60% near miss", "Near miss"))
        self.assertEqual(v("sog", .57, .57, 2.5, 3.0, 1, 1, mk=.56)["reason"], "57% < 62%")
        self.assertEqual(v("sog", .60, .6, 2.5, 3.0, 1, 1, matched=False)["reason"], "unmatched player")
        t = v("sog", .65, .6, 2.5, 3.0, 1, 1)
        self.assertEqual((t["verdict"], t["tier"], round(t["p_mkt_side"], 2)), ("TAKE MORE", "Lock", .6))
        self.assertEqual(v("sog", .63, .6, 2.5, 3.0, 1, 1)["tier"], "Strong")
        self.assertEqual(v("sog", .37, .41, 2.5, 2.0, 1, 1, mk=.42)["verdict"], "TAKE LESS")
        # SOG (rule R1) has no "model alone agrees" check: the mean blend already carries the model; points keep it
        self.assertEqual(v("sog", .63, .45, 2.5, 3.0, 1, 1)["verdict"], "TAKE MORE")
        self.assertIn("model alone 45% disagrees", v("points", .60, .45, 0.5, 0.9, 1, 1)["reason"])

    def test_market_support_and_blocks(self):
        # no market quote: model-only picks have not won (SOG 52-54% at 1x, points' own leans 56.6%)
        self.assertTrue(pricing.verdict("sog", .70, .70, 2.5, 3.4, 1, 1)["reason"].startswith("no market price"))
        # the market prices the line but leans only 52% our way
        r = pricing.verdict("points", .60, .80, 0.5, 0.9, 1, 1, p_mkt_over=.52)
        self.assertEqual((r["verdict"], r["reason"], r["tier"]), ("PASS", "market only 52% on this side", ""))
        # a line priced at the sportsbook's own odds is never a TAKE
        self.assertEqual(pricing.verdict("points", .70, .72, 0.5, 0.9, None, None, -150, 120, p_mkt_over=.6)["reason"],
                         "sportsbook price: no edge over the book's own odds")
        # points 1.5+ unders are blocked; 0.5 unders are not
        self.assertIn("unders", pricing.verdict("points", .30, .30, 1.5, 0.6, 1, 1, p_mkt_over=.35)["reason"])
        self.assertEqual(pricing.verdict("points", .38, .30, 0.5, 0.4, 1, 1, p_mkt_over=.40)["verdict"], "TAKE LESS")
        # a side failing the market check is not a near miss
        self.assertEqual(pricing.verdict("sog", .60, .60, 2.5, 3.0, 1, 1, p_mkt_over=.50)["tier"], "")

    def test_saves_edges(self):
        v = lambda *a, mk=.6, **k: pricing.verdict(*a, p_mkt_over=mk, **k)
        self.assertEqual(v("saves", .62, .6, 25.5, 28.1, 1, 1)["reason"], "saves overs: no edge (they lost at every threshold)")
        self.assertIn("< 3", v("saves", .38, .4, 25.5, 22.8, 1, 1, mk=.4)["reason"])    # under needs 3.0
        self.assertEqual(v("saves", .38, .4, 25.5, 22.4, 1, 1, mk=.41)["verdict"], "TAKE LESS")
        self.assertTrue(pricing.verdict("saves", .38, .4, 25.5, 22.4, 1, 1)["reason"].startswith("no market price"))
        self.assertEqual(v("saves", .62, .6, 25.5, 28.1, 1, 1, confirmed=False)["reason"], "starter not confirmed")


if __name__ == "__main__":
    unittest.main()


class LegLog(unittest.TestCase):
    def test_second_build_appends_to_csv(self):
        # rows read back from legs.csv are strings; the next build's rows have int game ids (the live crash)
        import os, tempfile, tracker
        old = tracker.LEGS
        tracker.LEGS = os.path.join(tempfile.mkdtemp(), "legs.csv")
        try:
            row = lambda game, pid, line: {"date": "2026-11-03", "game": game, "player_id": pid, "name": "A", "team": "TOR",
                                           "market": "sog", "line": line, "source": "Pick6", "side": "OVER", "p": .6}
            tracker.log_legs([row(2026020101, 1, 2.5)], "t1")
            tracker.log_legs([row(2026020099, 2, 1.5), row(2026020101, 1, 2.5)], "t2")
            legs = tracker._read_legs()
            self.assertEqual(len(legs), 2)
            self.assertEqual(next(r for r in legs if r["player_id"] == "1")["built"], "t2")   # latest snapshot replaces
        finally:
            tracker.LEGS = old
