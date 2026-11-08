"""Shots on goal: the market-implied mean and the 50/50 mean-space blend (props_board.score_lines, mirrored by the
page's finishRow / impliedMean). One NB mean per player from the market, averaged with the model's projection,
then priced at any line with the model's dispersion; no Platt."""
import unittest

import pricing
import props_board as pb
import sog
from tests.test_board import PLAYERS, p6, payload

PRM = sog.SogParams.load(__import__("os").path.join(__import__("os").path.dirname(__file__), "..", "output", "sog_params.json"))


def dk(pid, name, line, over, under):
    return {"name": name, "player_id": pid, "teams": ["TOR", "FLA"], "date": "2026-11-03", "line": line,
            "over": over, "under": under}


class ImpliedMean(unittest.TestCase):
    def test_round_trip(self):
        # exact in probability: the mean found reproduces the price at that line. The dispersion steps at the tier
        # edges (1.5 / 2.5 / 3.5 expected shots), so within ~0.2 of an edge two means can give the same price; on
        # lines priced 20-80% they differ by at most ~0.1 shots (half that after the 50/50 blend)
        for pos in ("F", "D"):
            for mu in [x / 20 for x in range(4, 120)]:
                for line in (0.5, 1.5, 2.5, 3.5, 4.5, 5.5):
                    p = sog.p_over(mu, line, sog.size_for(mu, PRM, pos))
                    if not 0.02 < p < 0.98:
                        continue
                    m = sog.implied_mean(p, line, PRM, pos)
                    self.assertAlmostEqual(sog.p_over(m, line, sog.size_for(m, PRM, pos)), p, places=5)
                    if 0.2 < p < 0.8:
                        self.assertLess(abs(m - mu), 0.11, (pos, mu, line, p, m))

    def test_monotone_and_bounded(self):
        a = sog.implied_mean(0.40, 2.5, PRM, "F"); b = sog.implied_mean(0.60, 2.5, PRM, "F")
        self.assertLess(a, b)
        self.assertIsNone(sog.implied_mean(None, 2.5, PRM, "F"))
        self.assertIsNone(sog.implied_mean(1.0, 2.5, PRM, "F"))


class Blend(unittest.TestCase):
    def setUp(self):
        self.w = pricing.SOG_MEAN_W
        self.assertGreater(self.w, 0)

    def score(self, lines, quotes, players=PLAYERS):
        pl = payload(players, quotes)
        pl["sog"]["params"] = PRM.to_dict()
        return pb.score_lines(pl, lines)

    def test_same_line_uses_the_quote_and_blends_in_mean_space(self):
        # Marner projects 4.2 (r60 14 x 18 min); DK prices his 2.5 at no-vig 64.8% over
        r = self.score([p6(10, "Mitch Marner", "TOR", 2.5)], [dk(10, "M. Marner", 2.5, -200, 160)])[0]
        nv = pricing.novig(-200, 160)
        mu_m = sog.implied_mean(nv, 2.5, PRM, "F")
        mu = (1 - self.w) * r["proj"] + self.w * mu_m
        self.assertTrue(r["mean_blend"])
        self.assertAlmostEqual(r["p_mkt"], round(nv, 4), places=4)
        self.assertAlmostEqual(r["mu_mkt"], round(mu_m, 3), places=3)
        self.assertAlmostEqual(r["p_blend"], round(sog.p_over(mu, 2.5, sog.size_for(mu, PRM, "F")), 4), places=4)
        self.assertEqual(r["mkt_src"], "DraftKings")
        self.assertTrue(min(r["p_raw"], nv) - 1e-4 <= r["p_blend"] <= max(r["p_raw"], nv) + 1e-4)

    def test_other_line_transfers_the_market_mean(self):
        # DK posts only 2.5; the Pick6 line is 3.5: the market's mean is priced at 3.5 (shown as "(other line)")
        r = self.score([p6(10, "Mitch Marner", "TOR", 3.5)], [dk(10, "M. Marner", 2.5, -200, 160)])[0]
        mu_m = sog.implied_mean(pricing.novig(-200, 160), 2.5, PRM, "F")
        self.assertAlmostEqual(r["p_mkt"], round(sog.p_over(mu_m, 3.5, sog.size_for(mu_m, PRM, "F")), 4), places=4)
        self.assertEqual(r["mkt_src"], "DraftKings (other line)")
        mu = (1 - self.w) * r["proj"] + self.w * mu_m
        self.assertAlmostEqual(r["p_blend"], round(sog.p_over(mu, 3.5, sog.size_for(mu, PRM, "F")), 4), places=4)

    def test_market_mean_from_the_line_nearest_50(self):
        # two DK lines: 2.5 at ~65% over and 3.5 at ~48%: the mean comes from the 3.5 (nearest a coin flip)
        r = self.score([p6(10, "Mitch Marner", "TOR", 4.5)], [dk(10, "M. Marner", 2.5, -200, 160), dk(10, "M. Marner", 3.5, 105, -125)])[0]
        self.assertAlmostEqual(r["mu_mkt"], round(sog.implied_mean(pricing.novig(105, -125), 3.5, PRM, "F"), 3), places=3)

    def test_no_market_price_keeps_the_raw_model_and_passes(self):
        r = self.score([p6(10, "Mitch Marner", "TOR", 2.5)], [])[0]
        self.assertEqual(r["p_blend"], r["p_raw"])
        self.assertIsNone(r["p_mkt"]); self.assertIsNone(r["mu_mkt"])
        self.assertEqual(r["verdict"], "PASS")
        self.assertTrue(r["reason"].startswith("no market price"))

    def test_take_needs_the_bar_and_market_support(self):
        # the model (4.2) and the market (2.5 at 72% over) agree: blended p clears 62% and the market's own side
        # clears 55%, offered at 1x on Pick6 -> TAKE MORE
        r = self.score([p6(10, "Mitch Marner", "TOR", 2.5)], [dk(10, "M. Marner", 2.5, -300, 230)])[0]
        self.assertGreaterEqual(r["p"], pricing.take_p("sog"))
        self.assertGreaterEqual(r["p_mkt_side"], pricing.MKT_MIN)
        self.assertEqual(r["verdict"], "TAKE MORE")
        # the same line Pick6 offers at 0.8x: never a play
        r = self.score([p6(10, "Mitch Marner", "TOR", 2.5, mo=0.8)], [dk(10, "M. Marner", 2.5, -300, 230)])[0]
        self.assertEqual(r["verdict"], "PASS"); self.assertEqual(r["reason"], "pays 0.8x")


class Dates(unittest.TestCase):
    """A market quote belongs to one game: a later game's line is never priced from tonight's quote."""
    def test_later_game_takes_no_quote_from_tonight(self):
        pl = payload(PLAYERS, [{**dk(10, "M. Marner", 2.5, -300, 230), "date": "2026-11-03"}])
        pl["sog"]["params"] = PRM.to_dict()
        pl["slate"].append({"id": 2, "date": "2026-11-04", "start": "2099-01-02T00:00:00Z", "home": "TOR", "away": "FLA", "state": "FUT"})
        pl["books"] = [{"market": "sog", "player_id": 10, "date": "2026-11-03", "line": 3.5, "book": "FanDuel", "over": 110, "under": -140}]
        tonight, later = p6(10, "Mitch Marner", "TOR", 2.5), {**p6(10, "Mitch Marner", "TOR", 2.5), "game": 2, "date": "2026-11-04"}
        later35 = {**p6(10, "Mitch Marner", "TOR", 3.5), "game": 2, "date": "2026-11-04"}
        a, b, c = pb.score_lines(pl, [tonight, later, later35])
        self.assertIsNotNone(a["p_mkt"]); self.assertEqual(a["mkt_src"], "DraftKings")
        for r in (b, c):
            self.assertIsNone(r["p_mkt"]); self.assertIsNone(r["mu_mkt"])
            self.assertEqual(r["verdict"], "PASS"); self.assertTrue(r["reason"].startswith("no market price"))


class OneSided(unittest.TestCase):
    def test_more_only_priced_line_is_never_a_less(self):
        # a PrizePicks demon priced More-only (+200, no Less): even when Less is the likely side, it is not offered
        v = pricing.verdict("sog", 0.10, 0.10, 4.5, 2.0, None, None, 200, None, p_mkt_over=0.10)
        self.assertEqual((v["side"], v["verdict"]), ("UNDER", "PASS"))
        self.assertEqual(v["reason"], "LESS not offered on this line")


class NoPlatt(unittest.TestCase):
    def test_sog_chance_ignores_the_platt_calibration(self):
        # a strongly non-identity SOG calibration in the payload must not move the shots chance (it does move points)
        pl = payload(PLAYERS, [dk(10, "M. Marner", 2.5, -200, 160)], cal={"a": 0.4, "b": 0.3, "b_under": 0.3, "w": 0.5})
        pl["sog"]["params"] = PRM.to_dict()
        r = pb.score_lines(pl, [p6(10, "Mitch Marner", "TOR", 2.5)])[0]
        mu_m = sog.implied_mean(pricing.novig(-200, 160), 2.5, PRM, "F")
        mu = 0.5 * r["proj"] + 0.5 * mu_m                       # proj on the row is rounded to 3 decimals
        self.assertAlmostEqual(r["p_blend"], sog.p_over(mu, 2.5, sog.size_for(mu, PRM, "F")), places=3)
        self.assertEqual(r["p_model"], r["p_raw"])               # the model alone is the raw model, not calibrated
        platt = pricing.platt(r["p_raw"], {"a": 0.4, "b": 0.3, "b_under": 0.3})
        self.assertGreater(abs(platt - r["p_raw"]), 0.05)        # the calibration would have moved it a lot


if __name__ == "__main__":
    unittest.main()
