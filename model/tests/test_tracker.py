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


if __name__ == "__main__":
    unittest.main()
