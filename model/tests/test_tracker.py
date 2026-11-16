"""Log de-dup and DFS-leg pricing."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pricing  # noqa: E402
import tracker  # noqa: E402


def row(**kw):
    base = {"date": "2026-10-20", "market": "saves", "player": "Igor Shesterkin", "team": "NYR", "book": "Pick6",
            "line": "25.5", "mult": 1, "side": "UNDER", "model_p": 0.6, "price": "", "result": "", "ev": ""}
    base.update(kw)
    return base


class Dedup(unittest.TestCase):
    def test_one_row_per_key(self):
        rows = [row(), row(result="HIT", actual=22), row(line="25.5"), row(player="I. Shesterkin", line=25.5),
                row(book="DraftKings"), row(line="26.5"), row(market="sog", line="2.5")]
        out = tracker.dedup(rows)
        keys = {(r["date"], tracker.prizepicks.name_key(r["player"]), r["market"], float(r["line"]), r["book"]) for r in out}
        self.assertEqual(len(out), len(keys))
        self.assertEqual(len(out), 4)                      # Pick6 25.5, DK 25.5, Pick6 26.5, SOG 2.5
        p6 = [r for r in out if r["book"] == "Pick6" and float(r["line"]) == 25.5 and r["market"] == "saves"]
        self.assertEqual(p6[0]["result"], "HIT")           # the graded copy survives

    def test_write_log_dedups(self):
        import tempfile
        old = tracker.LOG
        try:
            with tempfile.TemporaryDirectory() as d:
                tracker.LOG = os.path.join(d, "log.csv")
                tracker._write_log([row(), row(), row(book="DraftKings")])
                self.assertEqual(len(tracker._read_log()), 2)
        finally:
            tracker.LOG = old


class DfsLegPricing(unittest.TestCase):
    def test_pick6_rows_priced(self):
        be = pricing.dfs_break_even(1)
        self.assertAlmostEqual(tracker._units(row(result="HIT")), 1 / be - 1)
        self.assertEqual(tracker._units(row(result="MISS")), -1.0)
        self.assertEqual(tracker._units(row(result="PUSH")), 0.0)
        self.assertAlmostEqual(tracker.dfs_leg(row())[1], 0.6 / be - 1)
        rec = tracker._rec([row(result="HIT"), row(result="MISS")])
        self.assertEqual(rec["priced"], 2)
        self.assertIsNotNone(rec["roi"])


class Shown(unittest.TestCase):
    """The record counts every call the page ever showed, not only the ones still standing on the last board."""

    def setUp(self):
        import tempfile
        self.d = tempfile.mkdtemp()
        self.keep = tracker.LEGS, tracker.BACKFILL
        tracker.LEGS, tracker.BACKFILL = os.path.join(self.d, "legs.csv"), os.path.join(self.d, "legs_shown.json")

    def tearDown(self):
        import shutil
        tracker.LEGS, tracker.BACKFILL = self.keep
        shutil.rmtree(self.d)

    def leg(self, pid=1, line=2.5, source="PrizePicks", **kw):
        return {"date": "2026-11-16", "game": 2026020300, "player_id": pid, "name": f"P{pid}", "team": "TOR", "opp": "FLA", "market": "sog",
                "line": line, "source": source, "mo": 1.0, "mu": 1.0, "side": "UNDER", "mult": 1.0, "p_model": .6, "p_mkt": .56,
                "p_blend": .41, "p": .59, "verdict": "PASS", "tier": "", "reason": "x", **kw}

    def one(self, pid=1):
        return next(r for r in tracker._read_legs() if r["player_id"] == str(pid))

    def test_the_strongest_call_is_kept(self):
        lean = dict(lean=True, pick_side="UNDER", pick_p=.59)
        tracker.log_legs([self.leg(**lean), self.leg(2)], "2026-11-16T15:00:00+00:00")
        r = self.one()
        self.assertEqual((r["shown"], r["shown_at"], r["shown_side"], r["shown_p"], r["shown_mult"]),
                         ("lean", "2026-11-16T15:00:00+00:00", "UNDER", "0.59", "1.0"))
        never = self.one(2)
        self.assertEqual((never["shown"], never["shown_at"]), ("", "-"))            # logged, nothing shown
        # by 6 PM the line has moved and he is no longer a lean: the snapshot changes, the call that was shown stays
        tracker.log_legs([self.leg(p=.53, mu=0.9)], "2026-11-16T23:00:00+00:00")
        r = self.one()
        self.assertEqual((r["p"], r["lean"], r["mu"], r["built"]), ("0.53", "", "0.9", "2026-11-16T23:00:00+00:00"))
        self.assertEqual((r["shown"], r["shown_at"], r["shown_p"], r["shown_mult"]), ("lean", "2026-11-16T15:00:00+00:00", "0.59", "1.0"))
        # a play outranks the lean and is kept with its own numbers; a later lean never downgrades it
        tracker.log_legs([self.leg(p=.63, verdict="TAKE LESS")], "2026-11-16T23:15:00+00:00")
        self.assertEqual((self.one()["shown"], self.one()["shown_at"], self.one()["shown_p"]), ("play", "2026-11-16T23:15:00+00:00", "0.63"))
        tracker.log_legs([self.leg(**lean)], "2026-11-16T23:30:00+00:00")
        self.assertEqual((self.one()["shown"], self.one()["shown_at"], self.one()["lean"]), ("play", "2026-11-16T23:15:00+00:00", "1"))
        tracker.log_legs([self.leg(2, **lean)], "2026-11-16T23:30:00+00:00")       # a first call on a leg seen before
        self.assertEqual((self.one(2)["shown"], self.one(2)["shown_at"]), ("lean", "2026-11-16T23:30:00+00:00"))

    def test_a_lean_is_kept_on_the_side_it_was_shown_for(self):
        # the row's own side is the likelier one; the pick's side and chance are what the page showed
        tracker.log_legs([self.leg(side="OVER", p=.52, lean=True, pick_side="UNDER", pick_p=.48, mu=1.3, pick_promo="Power Up")], "t1")
        r = self.one()
        self.assertEqual((r["shown_side"], r["shown_p"], r["shown_mult"], r["promo"]), ("UNDER", "0.48", "1.3", "Power Up"))

    def test_a_graded_leg_is_never_touched(self):
        tracker.log_legs([self.leg(lean=True, pick_side="UNDER", pick_p=.59)], "t1")
        rows = tracker._read_legs()
        rows[0].update(result="HIT", actual=1)
        tracker._write_legs(rows)
        tracker.log_legs([self.leg(p=.7, verdict="TAKE LESS")], "t2")
        r = self.one()
        self.assertEqual((r["shown"], r["built"], r["result"]), ("lean", "t1", "HIT"))

    def test_old_rows_take_their_call_from_the_history(self):
        import csv
        import json
        old = [f for f in tracker.LEG_FIELDS if f not in tracker.SHOWN_FIELDS and f != "promo"]      # the log before Nov 16
        rows = [self.leg(1, lean=""), self.leg(2, verdict="TAKE LESS", p=.64, lean=""), self.leg(3, lean="1"), self.leg(4, lean="")]
        with open(tracker.LEGS, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=old, extrasaction="ignore")
            w.writeheader()
            w.writerows({**r, "built": "t9", "result": "", "actual": ""} for r in rows)
        # the history saw leg 1 shown as a lean at noon, on other numbers than its last snapshot's
        with open(tracker.BACKFILL, "w") as f:
            json.dump({"2026-11-16|1|sog|2.5|PrizePicks": {"shown": "lean", "shown_at": "t3", "shown_side": "UNDER", "shown_p": "0.5712", "shown_mult": "1.0"}}, f)
        got = {r["player_id"]: (r.get("shown"), r.get("shown_at"), r.get("shown_p")) for r in tracker._read_legs()}
        self.assertEqual(got["1"], ("lean", "t3", "0.5712"))                        # from the history
        self.assertEqual(got["2"], ("play", "t9", "0.64"))                          # no history: its own last snapshot
        self.assertEqual(got["3"], ("lean", "t9", "0.59"))
        self.assertEqual(got["4"][0], None)                                         # nothing was ever shown
        # once the new log has seen a leg ("-"), the history is not asked again
        tracker.log_legs([self.leg(4)], "t10")
        with open(tracker.BACKFILL, "w") as f:
            json.dump({"2026-11-16|4|sog|2.5|PrizePicks": {"shown": "play", "shown_at": "t1", "shown_side": "UNDER", "shown_p": "0.7", "shown_mult": "1.0"}}, f)
        self.assertEqual((self.one(4)["shown"], self.one(4)["shown_at"]), ("", "-"))
        os.remove(tracker.BACKFILL)                                                 # a missing or broken file is no history
        self.assertEqual(self.one(1)["shown"], "lean")                              # (already written into the log)

    def graded(self, pid, shown, side, actual, **kw):
        return {"date": "2026-11-16", "player_id": str(pid), "market": "sog", "line": "2.5", "source": "PrizePicks", "side": side,
                "p": "0.53", "mult": "1.0", "result": tracker._result(side, actual, 2.5), "actual": str(actual), "shown": shown,
                "shown_at": "2026-11-16T15:00:00+00:00", "shown_side": side, "shown_p": "0.59", "shown_mult": "1.0", **kw}

    def test_calls_are_graded_as_they_were_shown(self):
        rows = [self.graded(1, "lean", "UNDER", 1), self.graded(2, "lean", "UNDER", 4), self.graded(3, "play", "OVER", 3),
                self.graded(4, "", "OVER", 3), self.graded(5, "lean", "OVER", 3, line="3.0", result="PUSH"),
                self.graded(6, "lean", "OVER", 3, result="VOID"), self.graded(7, "lean", "OVER", 3, result="")]
        leans = tracker.shown_legs(rows, "lean")
        self.assertEqual(sorted((r["player_id"], r["result"]) for r in leans), [("1", "HIT"), ("2", "MISS")])   # a push is no bet
        self.assertEqual([(r["p"], r["mult"]) for r in leans], [("0.59", "1.0")] * 2)                       # the numbers shown
        self.assertEqual([r["player_id"] for r in tracker.shown_legs(rows, "play")], ["3"])
        # the last snapshot had flipped to the other side and lost; the lean that was shown (UNDER) won
        flipped = self.graded(8, "lean", "OVER", 1, shown_side="UNDER")
        self.assertEqual(flipped["result"], "MISS")
        self.assertEqual(tracker.shown_legs([flipped], "lean")[0]["result"], "HIT")
        self.assertEqual(tracker.shown_legs([flipped], "lean")[0]["side"], "UNDER")

    def test_the_same_bet_on_two_apps_counts_once(self):
        a = self.graded(1, "lean", "UNDER", 1, source="PrizePicks", shown_at="2026-11-16T16:00:00+00:00", shown_p="0.58")
        b = self.graded(1, "lean", "UNDER", 1, source="Pick6", shown_at="2026-11-16T15:00:00+00:00", shown_p="0.60")
        other_line = self.graded(1, "lean", "UNDER", 1, line="3.5")
        out = tracker.shown_legs([a, b, other_line], "lean")
        self.assertEqual(sorted((r["line"], r["p"]) for r in out), [("2.5", "0.60"), ("3.5", "0.59")])     # the earlier showing

    def test_split_by_what_the_last_board_still_showed(self):
        # the same bet on two apps: dropped on one, still a lean on the other at puck drop -> still standing
        a = self.graded(1, "lean", "UNDER", 1, source="PrizePicks", lean="")
        b = self.graded(1, "lean", "UNDER", 1, source="Pick6", lean="1")
        gone = self.graded(2, "lean", "UNDER", 4, lean="")
        play = self.graded(3, "lean", "UNDER", 1, lean="", verdict="TAKE LESS")       # became a play: still a call
        flipped = self.graded(4, "lean", "OVER", 3, shown_side="UNDER", lean="1")     # a lean again, on the other side
        left = self.graded(5, "lean", "UNDER", 1, lean="1", built="t1")              # his line left the board at noon
        rows = [{"game": "g1", "built": "t2", **r} for r in (a, b, gone, play, flipped)] + [{"game": "g1", **left}]
        got = {k: sorted(r["player_id"] for r in v) for k, v in tracker.shown_split(rows, tracker.shown_legs(rows, "lean")).items()}
        self.assertEqual(got, {"last": ["1", "3"], "gone": ["5"], "erased": ["2", "4"]})

    def test_since_keeps_calls_first_shown_under_the_current_rules(self):
        early = self.graded(1, "play", "OVER", 3, shown_at="2026-11-08T13:00:00+00:00")
        late = self.graded(2, "play", "OVER", 3, shown_at="2026-11-08T15:00:00+00:00")
        self.assertEqual([r["player_id"] for r in tracker.shown_legs([early, late], "play", tracker.RULES_LIVE_AT)], ["2"])
        self.assertEqual(len(tracker.shown_legs([early, late], "play")), 2)

    def test_summary_reports_both_bases(self):
        lean = dict(lean=True, pick_side="UNDER", pick_p=.59)
        tracker.log_legs([self.leg(1, **lean), self.leg(2, **lean), self.leg(3, **lean), self.leg(4, p=.64, verdict="TAKE LESS")],
                         "2026-11-16T15:00:00+00:00")
        # by the last board legs 2 and 3 are no longer leans
        tracker.log_legs([self.leg(1, **lean), self.leg(2, p=.52), self.leg(3, p=.52), self.leg(4, p=.6)], "2026-11-16T23:00:00+00:00")
        rows = tracker._read_legs()
        for r, actual in zip(rows, (1, 4, 4, 1)):
            r.update(actual=actual, result=tracker._result("UNDER", actual, 2.5))
        tracker._write_legs(rows)
        s = tracker.legs_summary()
        sog = s["by_market"]["sog"]
        self.assertEqual((sog["leans"]["n"], sog["leans"]["hit"]), (1, 1))            # the survivor only: 1-0
        self.assertEqual((sog["leans_shown"]["n"], sog["leans_shown"]["hit"]), (3, 1))   # every lean shown: 1-2
        self.assertEqual((sog["leans_shown_by_side"]["UNDER"]["n"], sog["leans_shown_by_side"]["OVER"]["n"]), (3, 0))
        self.assertEqual((sog["leans_shown_last"]["hit"], sog["leans_shown_last"]["miss"]), (1, 0))       # still a lean on the last board
        self.assertEqual((sog["leans_shown_erased"]["hit"], sog["leans_shown_erased"]["miss"]), (0, 2))   # the page dropped them
        self.assertEqual(sog["leans_shown_gone"]["n"], 0)
        self.assertEqual((sog["plays_shown"]["n"], sog["plays_shown"]["hit"], sog["takes_now"]["n"]), (1, 1, 0))
        self.assertEqual(sog["plays_shown_by_side"]["UNDER"]["n"], 1)
        self.assertAlmostEqual(sog["leans_shown"]["pred"], .59)                       # the chance shown, not the last one
        self.assertIn("every play and lean", s["shown_basis"])


if __name__ == "__main__":
    unittest.main()
