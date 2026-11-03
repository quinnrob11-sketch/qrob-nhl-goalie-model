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
        b = self.build([p6(10, "Mitch Marner", "TOR", 2.5), p6(10, "Mitch Marner", "TOR", 3.5), p6(10, "Mitch Marner", "TOR", 1.5, mo=0.8)])
        m = [r for r in b["rows"] if r["player_id"] == 10]
        takes = [r for r in m if r["verdict"].startswith("TAKE")]
        self.assertEqual(len(takes), 1)
        self.assertEqual(takes[0]["line"], 2.5)                      # highest EV that passes at >= 1x (p 77% vs 60%)
        alt = next(r for r in m if r["line"] == 3.5)
        self.assertEqual(alt["verdict"], "PASS"); self.assertIn("alt line", alt["reason"])
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
        self.assertEqual(next(r for r in b["rows"] if r["name"] == "Nobody")["reason"], "unmatched player")
        per_player = {}
        for r in b["rows"]:
            if r["verdict"].startswith("TAKE"):
                per_player[(r["player_id"], r["market"])] = per_player.get((r["player_id"], r["market"]), 0) + 1
        self.assertTrue(all(v == 1 for v in per_player.values()))

    def test_market_driven_legs_pass(self):
        # DK prices Reinhart's 1.5 over at 70% no-vig; blended p (w = 0) is 70%, but the model alone leans under
        dk = [{"name": "Sam Reinhart", "player_id": 20, "teams": ["TOR", "FLA"], "date": "2026-11-03", "line": 1.5, "over": -233, "under": 233}]
        b = self.build([p6(20, "Sam Reinhart", "FLA", 1.5)], dk)
        r = b["rows"][0]
        self.assertGreaterEqual(r["p_blend"], 0.58)
        self.assertEqual(r["verdict"], "PASS"); self.assertIn("model alone", r["reason"])

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
        self.assertEqual(pricing.verdict("sog", .60, .58, 2.5, 3.0, 0.8, 1.2)["reason"], "pays 0.8x")
        self.assertEqual(pricing.verdict("sog", .56, .56, 2.5, 3.0, 1, 1)["reason"], "56% near miss")
        self.assertEqual(pricing.verdict("sog", .60, .6, 2.5, 3.0, 1, 1, matched=False)["reason"], "unmatched player")
        t = pricing.verdict("sog", .63, .6, 2.5, 3.0, 1, 1)
        self.assertEqual((t["verdict"], t["tier"]), ("TAKE MORE", "Lock"))
        self.assertEqual(pricing.verdict("sog", .40, .41, 2.5, 2.0, 1, 1)["verdict"], "TAKE LESS")

    def test_saves_edges(self):
        self.assertIn("edge +2.0 < 2.5", pricing.verdict("saves", .62, .6, 25.5, 27.5, 1, 1)["reason"])
        self.assertEqual(pricing.verdict("saves", .62, .6, 25.5, 28.1, 1, 1)["verdict"], "TAKE MORE")
        self.assertIn("< 3", pricing.verdict("saves", .38, .4, 25.5, 22.8, 1, 1)["reason"])    # under needs 3.0
        self.assertEqual(pricing.verdict("saves", .38, .4, 25.5, 22.4, 1, 1)["verdict"], "TAKE LESS")
        self.assertEqual(pricing.verdict("saves", .62, .6, 25.5, 28.1, 1, 1, confirmed=False)["reason"], "starter not confirmed")


if __name__ == "__main__":
    unittest.main()
