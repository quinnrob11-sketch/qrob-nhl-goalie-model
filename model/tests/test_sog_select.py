"""SOG selection (props_board.select_sog, mirrored by selectSog in template.html): Lock / Strong TAKEs in
Today's plays, near misses (within NEAR_BAND of the bar) in their own list, sub-1x sides in neither, one line per
player per game, conflict fallback to the next-best line, role changes and bad matches in Needs review, saves
unchanged."""
import copy
import unittest

import pricing
import props_board as pb
from tests.test_board import PLAYERS, p6, payload


# The cases were written against SOG bars of 55% (near miss) / 58% (TAKE) / 62% (Lock). P() moves a case's p onto
# the current bars (pricing.near_p / take_p / lock_p) piecewise-linearly, so every case keeps its meaning whatever
# the bars are: a near miss stays a near miss, a Strong a Strong, a Lock a Lock, and the order of p is unchanged.
_OLD = (0.0, 0.55, 0.58, 0.62, 1.0)


def P(p):
    new = (0.0, pricing.near_p("sog"), pricing.take_p("sog"), pricing.lock_p("sog"), 1.0)
    for i in range(1, len(_OLD)):
        if p <= _OLD[i] or i == len(_OLD) - 1:
            a, b, c, d = _OLD[i - 1], _OLD[i], new[i - 1], new[i]
            return round(c + (p - a) * (d - c) / (b - a), 4)


def row(pid, name, line, p, side="OVER", mult=1.0, team="TOR", ev=None, take=None, pms=None, **kw):
    """A scored SOG row as score_lines + finish leave it (tier 'Near miss' where pricing.verdict would set it:
    a DFS side at >= 1x whose p is within NEAR_BAND of the bar)."""
    take = p >= pricing.take_p("sog") if take is None else take
    sd = "MORE" if side == "OVER" else "LESS"
    near = (not take) and mult is not None and mult >= pricing.MIN_MULT and pricing.near_p("sog") - 1e-9 <= p < pricing.take_p("sog")
    return {"name": name, "player_id": pid, "team": team, "opp": "FLA" if team == "TOR" else "TOR", "game": 1,
            "market": "sog", "label": "SOG", "line": line, "side": side, "p": p, "p_model_side": pms if pms is not None else p,
            "mult": mult, "ev": ev if ev is not None else (p * (1 + mult) - 1 if mult else None), "matched": True,
            "verdict": f"TAKE {sd}" if take else "PASS", "reason": "" if take else "below the bar",
            "tier": "Near miss" if near else "", "source": "Pick6", **kw}


def names(xs):
    return [(r["name"], r["line"], r["side"]) for r in xs]


class SogSelect(unittest.TestCase):
    def test_zero_takes_still_shows_near_misses(self):
        rows = [row(1, "A", 2.5, P(0.565)), row(2, "B", 1.5, P(0.551), side="UNDER", team="FLA"), row(3, "C", 3.5, P(0.54)),
                row(4, "D", 0.5, P(0.57), pms=0.48)]      # D: the model alone disagrees (no check for SOG, rule R1)
        sel = pb.select_sog(rows)
        self.assertEqual(sel["plays"], [])
        self.assertEqual(names(sel["near"]), [("D", 0.5, "OVER"), ("A", 2.5, "OVER"), ("B", 1.5, "UNDER")])
        self.assertTrue(all(r["verdict"] == "PASS" and r["tier"] == "Near miss" for r in sel["near"]))
        self.assertEqual(sel["counts"]["near_miss"], 3)
        self.assertEqual((sel["counts"]["lock"], sel["counts"]["strong"]), (0, 0))

    def test_sub_1x_never_listed_even_at_62(self):
        rows = [row(1, "A", 0.5, P(0.80), mult=0.6, take=False), row(2, "B", 1.5, P(0.63), mult=0.9, take=True),
                row(3, "C", 1.5, P(0.56), mult=0.8, take=False)]
        sel = pb.select_sog(rows)
        self.assertEqual((sel["plays"], sel["near"]), ([], []))
        self.assertTrue(all(not r["verdict"].startswith("TAKE") for r in rows))
        self.assertEqual(sel["counts"]["hidden_discounts"], 3)
        self.assertIn("pays 0.9x", rows[1]["reason"])

    def test_dk_priced_rows_are_never_listed(self):
        # DraftKings fallback rows (no multiplier, priced at DK's own odds) are info only: never a play or a near
        # miss (pricing.verdict PASSes them); a price worse than a 1x leg also counts as a hidden discount
        rows = [{**row(5, "E", 1.5, P(0.60), mult=None, take=False), "be": 0.60},
                {**row(6, "F", 1.5, P(0.565), mult=None, team="FLA"), "be": 0.52}]
        sel = pb.select_sog(rows)
        self.assertEqual((sel["plays"], sel["near"]), ([], []))
        self.assertEqual(sel["counts"]["hidden_discounts"], 1)
        self.assertIn("worse than 1x", rows[0]["reason"])

    def test_one_line_per_player_main_and_alts(self):
        # main 1.5 at 66% (1x) and alt 2.5 at 59% paying 1.5x (higher EV): the higher-p line wins, never the payout
        rows = [row(1, "A", 1.5, P(0.66)), row(1, "A", 2.5, P(0.59), mult=1.5), row(1, "A", 3.5, P(0.565), mult=2.0),
                row(2, "B", 2.5, P(0.60)), row(2, "B", 2.5, P(0.57), side="UNDER", team="TOR", take=False)]
        rows[-1]["player_id"] = 2
        sel = pb.select_sog(rows)
        shown = sel["plays"] + sel["near"]
        self.assertEqual(len({(r["player_id"], r["game"]) for r in shown}), len(shown))
        self.assertEqual(names(sel["plays"]), [("A", 1.5, "OVER"), ("B", 2.5, "OVER")])
        self.assertEqual(rows[0]["tier"], "Lock"); self.assertEqual(rows[3]["tier"], "Strong")
        self.assertEqual(sum(r["verdict"].startswith("TAKE") for r in rows if r["player_id"] == 1), 1)
        self.assertIn("alt line (best is 1.5 more)", rows[1]["reason"])
        self.assertEqual([r["primary"] for r in rows[:3]], [True, False, False])

    def test_conflict_falls_back_to_next_best_line(self):
        # teammate A takes MORE at 70%; B's best side is LESS 2.5 at 64% (conflict), next is MORE 0.5 at 60%
        rows = [row(1, "A", 2.5, P(0.70)), row(2, "B", 2.5, P(0.64), side="UNDER"), row(2, "B", 0.5, P(0.60))]
        sel = pb.select_sog(rows)
        self.assertEqual(names(sel["plays"]), [("A", 2.5, "OVER"), ("B", 0.5, "OVER")])
        self.assertTrue(rows[1]["reason"].startswith("conflict: A SOG MORE"))
        self.assertEqual(rows[0]["conflicts"], ["B SOG LESS"])         # the warning sits on the kept line
        # with no other line, the loser is just out
        rows = [row(1, "A", 2.5, P(0.70)), row(2, "B", 2.5, P(0.64), side="UNDER")]
        self.assertEqual(names(pb.select_sog(rows)["plays"]), [("A", 2.5, "OVER")])

    def test_saves_take_beats_opposing_sog(self):
        sv = {"name": "G", "label": "Saves", "market": "saves", "game": 1, "opp": "TOR", "side": "OVER", "verdict": "TAKE MORE"}
        rows = [row(1, "A", 2.5, P(0.66), side="UNDER"), row(1, "A", 1.5, P(0.59))]
        sel = pb.select_sog(rows, [sv])
        self.assertEqual(names(sel["plays"]), [("A", 1.5, "OVER")])
        self.assertIn("conflict: G Saves MORE", rows[0]["reason"])

    def test_role_change_and_bad_matches_go_to_review(self):
        rows = [row(1, "A", 2.5, P(0.70), role_change="F2→F4"), row(2, "B", 1.5, P(0.65), team_mismatch=True, roster_team="UTA"),
                {**row(None, "Nobody", 1.5, P(0.6)), "matched": False, "side": None, "p": None, "verdict": "PASS"},
                row(4, "D", 1.5, P(0.60))]
        sel = pb.select_sog(rows)
        self.assertEqual(names(sel["plays"]), [("D", 1.5, "OVER")])
        self.assertEqual([r["name"] for r in sel["review"]], ["A", "B", "Nobody"])
        self.assertIn("role change F2→F4 (old → new line)", rows[0]["reason"])
        self.assertIn("team mismatch: board TOR, roster UTA", rows[1]["reason"])
        self.assertTrue(all(r["verdict"] == "PASS" for r in sel["review"]))
        self.assertEqual(sel["counts"]["needs_review"], 3)

    def test_shows_the_main_line_not_a_more_only_alt(self):
        # Jack Hughes, Nov 7: Pick6 main 3.5 (1x / 0.9x) and More-only alts up to 7.5 (10.1x). Nothing is kept, and
        # the board used to show the alt with the highest p: "SOG 7.5 LESS 89%", a side Pick6 doesn't offer.
        main = {**row(1, "Jack Hughes", 3.5, P(0.545), side="UNDER", take=False), "mo": 1.0, "mu": 0.9, "mult": 0.9}
        alts = [{**row(1, "Jack Hughes", ln, p, side="UNDER", take=False), "mo": m, "mu": 0.0, "mult": 0.0}
                for ln, p, m in ((7.5, 0.895, 10.1), (6.5, 0.834, 5.0), (5.5, 0.752, 2.7))]
        pp_row = {**row(1, "Jack Hughes", 3.5, P(0.545), side="UNDER", take=False), "source": "PrizePicks", "mo": 1.0, "mu": 1.0}
        rows = alts + [pp_row, main]
        pb.select_sog(rows)
        shown = [r for r in rows if r["primary"]]
        self.assertEqual([(r["line"], r["source"]) for r in shown], [(3.5, "Pick6")])
        self.assertTrue(all(r["verdict"] == "PASS" for r in rows))                 # display only: no call changes

    def test_all_ladder_player_shows_the_rung_nearest_1x(self):
        # Michael McCarron, Nov 8: only More-only Pick6 rungs (no line offered both ways). The board showed
        # 'SOG 4.5 LESS 92%' (a side Pick6 doesn't offer); it should show the rung paying closest to 1x.
        rungs = [{**row(9, "Michael McCarron", ln, p, side="UNDER", take=False), "mo": m, "mu": 0.0, "mult": 0.0}
                 for ln, p, m in ((4.5, 0.92, 4.8), (2.5, 0.70, 1.6), (1.5, 0.48, 1.05), (0.5, 0.20, 0.6))]
        pb.select_sog(rungs)
        self.assertEqual([r["line"] for r in rungs if r["primary"]], [1.5])

    def test_deterministic_under_input_order(self):
        rows = [row(1, "A", 2.5, P(0.60)), row(2, "B", 1.5, P(0.60), side="UNDER"), row(3, "C", 0.5, P(0.56)), row(1, "A", 1.5, P(0.60))]
        a = names(pb.select_sog(copy.deepcopy(rows))["plays"])
        b = names(pb.select_sog(copy.deepcopy(rows[::-1]))["plays"])
        self.assertEqual(a, b)


class BuildAndSaves(unittest.TestCase):
    def test_build_exports_near_miss_review_and_counts(self):
        b = pb.build(payload(PLAYERS), [p6(10, "Mitch Marner", "TOR", 2.5), p6(10, "Mitch Marner", "TOR", 1.5, mo=0.8)],
                     review=[{"name": "J. Smith", "team": "TOR", "market": "sog", "line": 1.5, "reason": "2 players match"}])
        c = b["counts"]["sog"]
        self.assertEqual(set(c), {"rows", "lock", "strong", "near_miss", "needs_review", "hidden_discounts"})
        self.assertEqual(c["rows"], 2)
        self.assertGreaterEqual(c["needs_review"], 1)
        self.assertIn("J. Smith", [r["name"] for r in b["review"]])
        self.assertIn("near_miss", b)
        self.assertTrue(all(p["verdict"].startswith("TAKE") for p in b["plays"]))

    def test_saves_rows_identical_to_legacy_rule(self):
        def sv(gid, name, team, opp, line, p, side, take, mult=1.0):
            sd = "MORE" if side == "OVER" else "LESS"
            return {"name": name, "player_id": gid, "team": team, "opp": opp, "game": 1, "market": "saves", "label": "Saves",
                    "line": line, "side": side, "p": p, "mult": mult, "ev": p * (1 + mult) - 1, "matched": True,
                    "verdict": f"TAKE {sd}" if take else "PASS", "reason": "" if take else "edge below 2.5", "tier": "Strong" if take else "",
                    "source": "Pick6"}
        rows = [sv(30, "G1", "FLA", "TOR", 26.5, 0.61, "OVER", True), sv(30, "G1", "FLA", "TOR", 27.5, 0.59, "OVER", True, 1.2),
                sv(31, "G2", "TOR", "FLA", 24.5, 0.55, "UNDER", False),
                row(1, "A", 2.5, P(0.64), side="UNDER"), row(2, "B", 1.5, P(0.60)), row(3, "C", 2.5, P(0.66), team="FLA", side="UNDER")]
        want = [r for r in pb.legacy_conflicts(pb.legacy_choose(copy.deepcopy(rows))) if r["market"] == "saves"]
        out, _ = pb.finalize(copy.deepcopy(rows))
        self.assertEqual([r for r in out if r["market"] == "saves"], want)
        # and with no SOG on the board at all
        only = [r for r in rows if r["market"] == "saves"]
        self.assertEqual(pb.finalize(copy.deepcopy(only))[0], pb.legacy_conflicts(pb.legacy_choose(copy.deepcopy(only))))


if __name__ == "__main__":
    unittest.main()
