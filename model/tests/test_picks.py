"""One pick per player and market (props_board.picks, mirrored by pickFor / pickItems in template.html): the side
to take, the line, the apps that offer exactly that bet at >= 1x, and a tier: play (a TAKE), lean, check, or no edge."""
import copy
import os
import tempfile
import unittest

import pricing
import props_board as pb
import tracker
from tests.test_board import PLAYERS, p6, payload

NO_MKT = object()


def row(pid, name, line, p_over, mo=1.0, mu=1.0, source="PrizePicks", market="sog", p_mkt=None, verdict="PASS", game=1, **kw):
    """A scored row as score_lines leaves it: p_blend = P(over), side / p = the likelier side, p_mkt = the market's
    P(over) (the blend's own number unless given; NO_MKT for a line no book prices)."""
    return {"name": name, "player_id": pid, "team": "TOR", "opp": "FLA", "game": game, "market": market,
            "label": pb.LABEL[market], "line": line, "mo": mo, "mu": mu, "source": source, "p_blend": p_over,
            "p_mkt": None if p_mkt is NO_MKT else p_over if p_mkt is None else p_mkt,
            "side": "OVER" if p_over >= .5 else "UNDER", "p": max(p_over, 1 - p_over), "matched": True,
            "verdict": verdict, "tier": "", "reason": "" if verdict != "PASS" else "x", **kw}


def tier(*rows):
    o = pb.pick_for(list(rows))
    return None if o is None else o["tier"]


class Offer(unittest.TestCase):
    def test_multipliers(self):
        r = row(1, "A", 2.5, .6, mo=1.0, mu=0.8)
        self.assertTrue(pb.side_offer(r, "OVER")["full"])
        self.assertAlmostEqual(pb.side_offer(r, "OVER")["be"], pricing.dfs_break_even(1.0))
        self.assertFalse(pb.side_offer(r, "UNDER")["full"])                  # 0.8x pays short
        self.assertIsNone(pb.side_offer(row(1, "A", 4.5, .1, mo=3.0, mu=0.0), "UNDER"))   # 0 = not offered
        self.assertEqual(pb.side_offer(row(1, "A", 2.5, .6, mo=None, mu=None), "OVER")["mult"], 1.0)

    def test_priced_lines(self):
        # a PrizePicks demon (+200, More only) and goblin (-250), and a DraftKings row: priced at their odds
        demon = row(1, "A", 4.5, .2, mo=None, mu=None, priced=True, dk_over=200, dk_under=None)
        self.assertTrue(pb.side_offer(demon, "OVER")["full"]); self.assertIsNone(pb.side_offer(demon, "UNDER"))
        goblin = row(1, "A", 1.5, .8, mo=None, mu=None, priced=True, dk_over=-250, dk_under=None)
        self.assertFalse(pb.side_offer(goblin, "OVER")["full"])
        dk = row(1, "A", 2.5, .6, mo=None, mu=None, source="DraftKings", dk_over=-130, dk_under=105)
        self.assertEqual(pb.side_offer(dk, "UNDER")["price"], 105)


class LeanRule(unittest.TestCase):
    def test_probability_bars(self):
        L, M = pricing.LEAN_P, pricing.LEAN_MKT_MIN
        self.assertTrue(pricing.lean("sog", "OVER", L, M, 2.5))
        self.assertFalse(pricing.lean("sog", "OVER", L - .001, M + .1, 2.5))      # under the chance bar
        self.assertFalse(pricing.lean("sog", "OVER", L + .1, M - .001, 2.5))      # the market does not lean that way
        self.assertFalse(pricing.lean("sog", "OVER", L + .1, None, 2.5))          # no market price
        self.assertFalse(pricing.lean("saves", "UNDER", .7, .7, 25.5))            # saves have no leans
        self.assertFalse(pricing.lean("points", "UNDER", .7, .7, 1.5))            # points 1.5+ unders are off
        self.assertTrue(pricing.lean("points", "UNDER", .6, .6, 0.5))
        self.assertTrue(pricing.lean("points", "OVER", .6, .6, 1.5))

    def test_bars_sit_under_the_play_bars(self):
        self.assertLess(pricing.LEAN_P, min(pricing.take_p(m) for m in ("sog", "points", "saves")))
        self.assertLess(pricing.LEAN_MKT_MIN, pricing.MKT_MIN)
        self.assertEqual((pricing.config()["lean_p"], pricing.config()["lean_mkt_min"]), (pricing.LEAN_P, pricing.LEAN_MKT_MIN))


class Tiers(unittest.TestCase):
    def test_lean_needs_the_bar_the_market_and_full_pay(self):
        self.assertEqual(tier(row(1, "A", 2.0, .60, p_mkt=.58)), "lean")
        self.assertEqual(tier(row(1, "A", 2.0, .40, p_mkt=.44)), "lean")          # LESS 60%, market 56% for LESS
        self.assertEqual(tier(row(1, "A", 2.0, .549, p_mkt=.58)), "")
        self.assertEqual(tier(row(1, "A", 2.0, .60, p_mkt=.51)), "")
        self.assertEqual(tier(row(1, "A", 2.0, .60, p_mkt=NO_MKT)), "")
        # the likelier side pays 0.8x: never a lean, however likely
        self.assertEqual(tier(row(1, "A", 2.5, .70, mo=0.8, mu=1.2, source="Pick6")), "")

    def test_market_rules(self):
        self.assertEqual(tier(row(1, "A", 1.5, .30, market="points")), "")        # points 1.5 under
        self.assertEqual(tier(row(1, "A", 0.5, .40, market="points")), "lean")    # points 0.5 under
        self.assertEqual(tier(row(1, "A", 25.5, .30, market="saves")), "")        # saves: plays only

    def test_reused_lines_and_line_changes(self):
        self.assertEqual(tier(row(1, "A", 2.0, .60, cached=True)), "")
        self.assertEqual(tier(row(1, "A", 2.0, .60, role_change="F3→F1")), "check")
        self.assertEqual(tier(row(1, "A", 2.0, .60, team_mismatch=True)), "check")
        self.assertEqual(tier(row(1, "A", 0.5, .60, market="points", role_change="F3→F1")), "lean")   # shots only
        self.assertEqual(tier(row(1, "A", 2.0, .52, role_change="F3→F1")), "")    # a pass anyway: no flag needed

    def test_a_take_is_the_play(self):
        t = row(1, "A", 2.5, .66, verdict="TAKE MORE", source="Pick6")
        o = pb.pick_for([row(1, "A", 2.0, .75, mo=0.7, mu=0.0, source="Pick6"), t, row(1, "A", 3.0, .45)])
        self.assertEqual((o["tier"], o["row"] is t, o["side"]), ("play", True, "OVER"))


class WhichBet(unittest.TestCase):
    def test_best_line_across_the_apps(self):
        # PrizePicks posts 2 (1x both ways), Pick6 posts 2.5 at More 1.2x / Less 0.8x: MORE is likelier on the lower line
        pp = row(1, "A", 2.0, .60, p_mkt=.58)
        p6r = row(1, "A", 2.5, .47, mo=1.2, mu=0.8, source="Pick6")
        o = pb.pick_for([p6r, pp])
        self.assertEqual((o["row"] is pp, o["side"], o["tier"]), (True, "OVER", "lean"))

    def test_no_edge_shows_the_likelier_side(self):
        # a coin flip at 1x both ways: the likelier side, no tier
        o = pb.pick_for([row(1, "A", 3.5, .49)])
        self.assertEqual((o["side"], round(o["p"], 2), o["tier"]), ("UNDER", .51, ""))
        # Pick6 pays 0.9x on the likelier side and 1x on the other: the row says MORE 54% (pays 0.9x), not LESS 46%
        o = pb.pick_for([row(1, "A", 3.5, .54, mo=0.9, mu=1.0, source="Pick6"), row(1, "A", 4.5, .25, mo=1.9, mu=0.0, source="Pick6")])
        self.assertEqual((o["side"], o["row"]["line"], o["full"], o["tier"]), ("OVER", 3.5, False, ""))

    def test_more_only_ladder_never_shows_an_unoffered_side(self):
        # every rung is More-only: the rung nearest 1x, on MORE (the old board showed "LESS not offered")
        rs = [row(1, "A", ln, p, mo=mo, mu=0.0, source="Pick6") for ln, p, mo in ((0.5, .95, .6), (1.5, .62, .9), (2.5, .30, 1.6), (3.5, .11, 3.3))]
        o = pb.pick_for(rs)
        self.assertEqual((o["side"], o["row"]["line"], o["tier"]), ("OVER", 1.5, ""))
        self.assertIsNotNone(pb.side_offer(o["row"], o["side"]))

    def test_no_app_no_pick(self):
        dk = row(1, "A", 2.5, .6, mo=None, mu=None, source="DraftKings", dk_over=-130, dk_under=105)
        self.assertIsNone(pb.pick_for([dk]))                                   # sportsbook odds are not an app
        self.assertIsNone(pb.pick_for([row(1, "A", 2.5, .6, matched=False)]))
        self.assertIsNone(pb.pick_for([{**row(1, "A", 2.5, .6), "p_blend": None}]))


class Apps(unittest.TestCase):
    def pick(self, rows):
        return next(r for r in pb.picks(rows) if r["pick"])

    def test_both_apps_when_both_post_the_bet(self):
        r = self.pick([row(1, "A", 3.5, .60, source="PrizePicks"), row(1, "A", 3.5, .60, source="Pick6")])
        self.assertEqual([a["app"] for a in r["pick_apps"]], ["Pick6", "PrizePicks"])   # Pick6 first on a tie
        self.assertEqual((r["pick_side"], r["pick_tier"], r["lean"]), ("OVER", "lean", True))

    def test_other_app_is_left_out_when_it_differs(self):
        # same line but 0.8x on that side; a different line; a line from an earlier pull that is too old to name
        for other in (row(1, "A", 3.5, .60, mo=0.8, mu=1.1, source="Pick6"), row(1, "A", 2.5, .75, mo=0.7, mu=0.0, source="Pick6"),
                      row(1, "A", 3.5, .60, source="Pick6", fallback=True, cached=True, age_min=pb.OLD_APP_MAX_MIN + 1),
                      row(1, "A", 3.5, .60, source="Pick6", fallback=True, cached=True, age_min=None)):
            r = self.pick([row(1, "A", 3.5, .60, source="PrizePicks"), other])
            self.assertEqual([a["app"] for a in r["pick_apps"]], ["PrizePicks"], other)

    def test_an_earlier_pulls_line_is_named_with_its_age(self):
        # Pick6's page showed only its featured picks this build: the line it had two hours ago is named, marked old,
        # after the fresh app; it never makes the lean itself
        old = row(1, "A", 3.5, .60, source="Pick6", fallback=True, cached=True, reused=True, age_min=120.0)
        r = self.pick([old, row(1, "A", 3.5, .60, source="PrizePicks")])
        self.assertEqual((r["source"], r["pick_tier"]), ("PrizePicks", "lean"))
        self.assertEqual([(a["app"], a.get("old", False)) for a in r["pick_apps"]], [("PrizePicks", False), ("Pick6", True)])
        self.assertEqual(r["pick_apps"][1]["age_min"], 120.0)
        alone = self.pick([row(2, "B", 3.5, .60, source="Pick6", fallback=True, cached=True, reused=True, age_min=120.0)])
        self.assertEqual((alone["pick_tier"], alone["lean"], alone["pick_apps"][0].get("old")), ("", False, True))

    def test_a_fresh_line_is_shown_before_a_reused_one(self):
        # no edge either way: the row shows the app whose line this build pulled itself
        r = self.pick([row(1, "A", 3.5, .52, source="Pick6", fallback=True, cached=True), row(1, "A", 3.5, .52, source="PrizePicks")])
        self.assertEqual((r["source"], [a["app"] for a in r["pick_apps"]], r["pick_tier"]), ("PrizePicks", ["PrizePicks"], ""))

    def test_short_pay_pick_names_its_own_app_and_multiplier(self):
        r = self.pick([row(1, "A", 3.5, .58, mo=0.8, mu=0.0, source="Pick6")])
        self.assertEqual((r["pick_apps"][0]["app"], r["pick_apps"][0]["mult"], r["pick_tier"]), ("Pick6", 0.8, ""))


class Board(unittest.TestCase):
    def test_marks_one_row_per_player_and_keeps_every_call(self):
        rows = [row(1, "A", 2.0, .60), row(1, "A", 2.5, .45, mo=1.3, mu=0.75, source="Pick6"),
                row(2, "B", 1.5, .52), row(3, "C", 2.5, .30, role_change="F1→F3"),
                row(4, "D", 2.5, .66, verdict="TAKE MORE", source="Pick6"),
                row(5, "E", 2.5, .6, mo=None, mu=None, source="DraftKings", dk_over=-130, dk_under=105)]
        before = copy.deepcopy([{k: r[k] for k in ("verdict", "tier", "reason", "side", "p", "p_blend", "p_mkt")} for r in rows])
        pk = pb.picks(rows)
        self.assertEqual([(r["name"], r["pick_tier"]) for r in pk], [("D", "play"), ("A", "lean"), ("C", "check"), ("B", "")])
        self.assertEqual(sum(r["pick"] for r in rows), 4)                       # one per player; none for the DraftKings-only one
        self.assertEqual([r["name"] for r in rows if r["lean"]], ["A"])
        self.assertEqual(before, [{k: r[k] for k in ("verdict", "tier", "reason", "side", "p", "p_blend", "p_mkt")} for r in rows])

    def test_build_ships_the_picks(self):
        # Marner projects 4.2 and DraftKings prices his 2.5 at 72% over: a play, posted by both apps at 1x
        dk = [{"name": "M. Marner", "player_id": 10, "teams": ["TOR", "FLA"], "date": "2026-11-03", "line": 2.5, "over": -300, "under": 230}]
        b = pb.build(payload(PLAYERS, dk), [p6(10, "Mitch Marner", "TOR", 2.5), {**p6(10, "Mitch Marner", "TOR", 2.5), "source": "PrizePicks"},
                                            p6(20, "Sam Reinhart", "FLA", 1.5)])
        m = next(p for p in b["picks"] if p["player_id"] == 10)
        self.assertEqual((m["pick_tier"], m["pick_side"], m["line"]), ("play", "OVER", 2.5))
        self.assertEqual(sorted(a["app"] for a in m["pick_apps"]), ["Pick6", "PrizePicks"])
        self.assertEqual(b["counts"]["takes"], 1)
        self.assertEqual(b["counts"]["picks"], 2)                                # Marner and Reinhart, one each
        self.assertTrue(all(p["pick_tier"] for p in b["picks"]))                 # only plays, leans and checks ship


class LegLog(unittest.TestCase):
    def test_leans_are_logged_and_graded_as_their_own_record(self):
        old = tracker.LEGS
        tracker.LEGS = os.path.join(tempfile.mkdtemp(), "legs.csv")
        try:
            leg = lambda pid, lean, **kw: {"date": "2026-11-03", "game": 2026020101, "player_id": pid, "name": f"P{pid}", "team": "TOR",
                                           "market": "sog", "line": 2.0, "source": "PrizePicks", "side": "OVER", "p": .58, "mult": 1.0,
                                           "verdict": "PASS", "lean": lean, **kw}
            tracker.log_legs([leg(1, True), leg(2, False), leg(3, True)], "t1")
            legs = tracker._read_legs()
            self.assertEqual({r["player_id"]: r["lean"] for r in legs}, {"1": "1", "2": "", "3": "1"})
            for r, res in zip(legs, ("HIT", "MISS", "MISS")):
                r["result"], r["actual"] = res, 3 if res == "HIT" else 1
            tracker._write_legs(legs)
            s = tracker.legs_summary()["by_market"]["sog"]
            self.assertEqual((s["leans"]["n"], s["leans"]["hit"], s["all"]["n"]), (2, 1, 3))
            self.assertEqual(s["leans_by_side"]["OVER"]["n"], 2)
            self.assertEqual(tracker.legs_summary()["rules_from"], tracker.RULES_FROM)
        finally:
            tracker.LEGS = old

    def test_plays_under_the_current_rules_are_counted_apart(self):
        old = tracker.LEGS
        tracker.LEGS = os.path.join(tempfile.mkdtemp(), "legs.csv")
        try:
            leg = lambda pid, date: {"date": date, "game": 1 if date < tracker.RULES_FROM else 2, "player_id": pid, "name": f"P{pid}", "team": "TOR",
                                     "market": "sog", "line": 2.5, "source": "PrizePicks", "side": "OVER", "p": .64, "mult": 1.0,
                                     "verdict": "TAKE MORE", "built": "t1", "result": "HIT", "actual": 4}
            tracker._write_legs([leg(1, "2026-11-01"), leg(2, tracker.RULES_FROM), leg(3, "2026-11-20")])
            s = tracker.legs_summary()["by_market"]["sog"]
            self.assertEqual((s["takes"]["n"], s["takes_now"]["n"]), (3, 2))
        finally:
            tracker.LEGS = old

    def test_old_log_without_the_column_still_reads(self):
        self.assertFalse(tracker._is_lean({"side": "OVER"}))
        self.assertFalse(tracker._is_lean({"lean": ""}))
        self.assertTrue(tracker._is_lean({"lean": "1"}))


if __name__ == "__main__":
    unittest.main()
