"""Slips (slips.py, mirrored by bvn / mvn / slipBook / bestSlips in template.html): the joint chance of an entry's
legs, what the entry pays (multipliers, the app's same-game cut, caps), pushes, Flex, the lineup rules, the search,
the correlations measured from box scores, and the page's own code run against the Python."""
import itertools
import json
import math
import os
import shutil
import subprocess
import tempfile
import unittest

import slips

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POWER, FLEX, P6 = slips.PAYOUTS["PrizePicks Power"], slips.PAYOUTS["PrizePicks Flex"], slips.PAYOUTS["Pick6"]


def leg(i, p, market="sog", team="TOR", game=1, side="OVER", mult=1.0, push=0.0, promo=None, proj=None):
    return {"id": f"{i}|{market}|{game}", "name": f"P{i}", "player_id": i, "team": team, "game": game, "market": market,
            "side": side, "p": p, "push": push, "mult": mult, "promo": promo, "proj": proj, "line": 2.5}


def apart(*ps, **kw):
    """Legs in different games on different teams: independent."""
    return [leg(i + 1, p, team=f"T{i}", game=i + 1, **kw) for i, p in enumerate(ps)]


def phi(x):
    return 0.5 * math.erfc(-x / math.sqrt(2))


def ref_bvn(h, k, r, n=4000):
    """P(X < h, Y < k) by Simpson's rule on the exact normal CDF: an independent reference."""
    a, s = -9.0, 0.0
    step = (h - a) / n
    for i in range(n + 1):
        x = a + i * step
        w = 1 if i in (0, n) else 4 if i % 2 else 2
        s += w * math.exp(-x * x / 2) / math.sqrt(2 * math.pi) * phi((k - r * x) / math.sqrt(1 - r * r))
    return s * step / 3


class Normal(unittest.TestCase):
    def test_cdf_and_inverse(self):
        self.assertAlmostEqual(slips.ncdf(0), 0.5, places=7)
        for x in (-3.1, -1.2, -0.3, 0.0, 0.7, 1.96, 2.8):
            self.assertAlmostEqual(slips.ncdf(x), phi(x), places=6)
            self.assertAlmostEqual(slips.ninv(phi(x)), x, places=6)
        self.assertEqual(slips.ninv(0.0), slips.ninv(1e-12))                 # clamped, never infinite
        self.assertAlmostEqual(slips.ninv(0.3), -slips.ninv(0.7), places=9)

    def test_two_events(self):
        for r in (-0.9, -0.3, 0.2, 0.7, 0.95):                              # both below their medians: a closed form
            self.assertAlmostEqual(slips.bvn(0, 0, r), 0.25 + math.asin(r) / (2 * math.pi), places=6)
        self.assertAlmostEqual(slips.bvn(0.4, -1.1, 0.0), phi(0.4) * phi(-1.1), places=6)
        for h, k, r in ((0.5, -0.3, 0.6), (1.2, 0.4, -0.5), (-1.0, -1.5, 0.9), (2.0, 1.0, 0.3), (0.25, 0.25, 0.31)):
            self.assertAlmostEqual(slips.bvn(h, k, r), ref_bvn(h, k, r), places=6)
        self.assertAlmostEqual(slips.bvn(0.3, 0.8, 0.4), slips.bvn(0.8, 0.3, 0.4), places=9)
        self.assertLessEqual(slips.bvn(0.3, 0.8, 0.999999), min(phi(0.3), phi(0.8)) + 1e-6)   # never above either chance

    def test_three_and_more(self):
        r12, r13, r23 = 0.3, -0.2, 0.5
        R = [[1, r12, r13], [r12, 1, r23], [r13, r23, 1]]
        self.assertAlmostEqual(slips.mvn([0, 0, 0], R), 1 / 8 + (math.asin(r12) + math.asin(r13) + math.asin(r23)) / (4 * math.pi), places=4)
        for n, tol in ((3, 5e-5), (4, 2e-4), (5, 5e-4), (6, 8e-4)):         # every pair tied at 0.5: exactly 1 / (n + 1)
            R = [[1.0 if i == j else 0.5 for j in range(n)] for i in range(n)]
            self.assertLess(abs(slips.mvn([0.0] * n, R) - 1 / (n + 1)), tol)
        eye = [[1.0 if i == j else 0.0 for j in range(4)] for i in range(4)]
        z = [0.3, -0.4, 1.1, 0.0]
        self.assertAlmostEqual(slips.mvn(z, eye), math.prod(phi(x) for x in z), places=5)
        self.assertEqual(slips.mvn([], []), 1.0)

    def test_quadrature(self):
        xs, ws = slips.gauleg(20)
        self.assertAlmostEqual(sum(ws), 2.0, places=12)
        self.assertAlmostEqual(slips.quad(lambda x: x ** 6, 0, 2, 8), 2 ** 7 / 7, places=9)


class Pairs(unittest.TestCase):
    def test_pair_types(self):
        sk = lambda mk, team, game=1: leg(1, .6, mk, team, game)
        T = slips.pair_type
        self.assertIsNone(T(sk("sog", "TOR", 1), sk("sog", "TOR", 2)))                  # different games
        self.assertEqual(T(sk("sog", "TOR"), sk("sog", "TOR")), "tm_sog")
        self.assertEqual(T(sk("sog", "TOR"), sk("sog", "FLA")), "opp_sog")
        self.assertEqual(T(sk("points", "TOR"), sk("points", "TOR")), "tm_pts")
        self.assertEqual(T(sk("points", "TOR"), sk("points", "FLA")), "opp_pts")
        self.assertEqual(T(sk("points", "TOR"), sk("sog", "TOR")), "tm_sog_pts")
        self.assertEqual(T(sk("sog", "TOR"), sk("points", "FLA")), "opp_sog_pts")
        self.assertEqual(T(sk("sog", "TOR"), sk("saves", "FLA")), "sog_opp_g")
        self.assertEqual(T(sk("saves", "TOR"), sk("sog", "TOR")), "sog_own_g")
        self.assertEqual(T(sk("points", "TOR"), sk("saves", "FLA")), "pts_opp_g")
        self.assertEqual(T(sk("saves", "TOR"), sk("points", "TOR")), "pts_own_g")
        self.assertEqual(T(sk("saves", "TOR"), sk("saves", "FLA")), "g_g")
        self.assertIsNone(T({"game": None, "team": "TOR", "market": "sog"}, {"game": None, "team": "TOR", "market": "sog"}))

    def test_leg_correlation(self):
        shooter, goalie = leg(1, .6, "sog", "TOR", proj=2.0), leg(2, .55, "saves", "FLA")
        self.assertAlmostEqual(slips.leg_rho(shooter, goalie), slips.RHO["sog_opp_g"])
        self.assertAlmostEqual(slips.leg_rho(shooter, {**goalie, "side": "UNDER"}), -slips.RHO["sog_opp_g"])   # one LESS flips it
        self.assertAlmostEqual(slips.leg_rho({**shooter, "side": "UNDER"}, {**goalie, "side": "UNDER"}), slips.RHO["sog_opp_g"])
        top = leg(1, .6, "sog", "TOR", proj=slips.TOP_SOG)
        self.assertAlmostEqual(slips.leg_rho(top, goalie), slips.RHO_TOP["sog_opp_g"])                  # a high-volume shooter
        a, b = leg(1, .6, "points", "TOR", proj=1.0), leg(2, .6, "points", "TOR", proj=0.6)
        self.assertAlmostEqual(slips.leg_rho(a, b), slips.RHO["tm_pts"])                                # both must be high volume
        self.assertAlmostEqual(slips.leg_rho(a, {**b, "proj": 0.9}), slips.RHO_TOP["tm_pts"])
        self.assertEqual(slips.leg_rho(a, leg(3, .6, "points", "TOR", game=2)), 0.0)
        self.assertAlmostEqual(slips.leg_rho(shooter, goalie, {"sog_opp_g": 0.4}, {}), 0.4)             # the build's own table

    def test_pick6_cut(self):
        shooter, goalie = leg(1, .6, "sog", "TOR"), leg(2, .55, "saves", "FLA")
        self.assertEqual(slips.pair_factor(shooter, goalie), 0.82)
        self.assertEqual(slips.pair_factor(shooter, {**goalie, "side": "UNDER"}), 1.0)                  # opposite ways: no cut
        self.assertEqual(slips.pair_factor(shooter, leg(3, .6, "saves", "FLA", game=2)), 1.0)
        self.assertEqual(slips.pair_factor(shooter, goalie, {("sog_opp_g", "same"): 0.7}), 0.7)


class Joint(unittest.TestCase):
    def test_independent_games_multiply(self):
        self.assertAlmostEqual(slips.joint(apart(.6, .55, .7)), .6 * .55 * .7, places=12)

    def test_same_game_moves_together(self):
        a, b = leg(1, .6, "points", "TOR"), leg(2, .6, "points", "TOR")
        both = slips.joint([a, b])
        self.assertGreater(both, .36 + .01)                                   # teammates' points rise together
        against = slips.joint([a, {**b, "side": "UNDER", "p": .4}])
        self.assertLess(against, .6 * .4 - .01)
        self.assertAlmostEqual(both + against, .6, places=6)                  # b either hits or misses: the two add up to a
        self.assertAlmostEqual(slips.joint([a, b]), slips.bvn(slips.ninv(.6), slips.ninv(.6), slips.RHO["tm_pts"]), places=12)

    def test_groups(self):
        a, b = leg(1, .6, "points", "TOR"), leg(2, .58, "points", "TOR")
        c, d = leg(3, .62, "sog", "BOS", game=2), leg(4, .55, "saves", "NYR", game=2)
        whole = slips.joint([a, c, b, d])                                     # two games, interleaved
        self.assertAlmostEqual(whole, slips.joint([a, b]) * slips.joint([c, d]), places=12)
        self.assertGreater(whole, .6 * .58 * .62 * .55)

    def test_chain_through_a_third_leg(self):
        # shooter - opposing goalie - that goalie's own skater's points: tied in one group even where a pair is ~0
        legs = [leg(1, .6, "sog", "TOR", proj=3.0), leg(2, .55, "saves", "FLA"), leg(3, .6, "points", "FLA", proj=1.0)]
        R = [[1.0 if i == j else slips.leg_rho(legs[i], legs[j]) for j in range(3)] for i in range(3)]
        self.assertAlmostEqual(slips.joint(legs), slips.mvn([slips.ninv(l["p"]) for l in legs], R), places=12)


class Value(unittest.TestCase):
    def test_power(self):
        v = slips.value(apart(.6, .6), POWER, "PrizePicks")
        self.assertAlmostEqual(v["ret"], .36 * 3); self.assertAlmostEqual(v["p_all"], .36); self.assertAlmostEqual(v["p_cash"], .36)
        self.assertEqual(v["pays"], 3.0)
        self.assertAlmostEqual(slips.value(apart(.6, .6, .6, .6, .6, .6), POWER, "PrizePicks")["ret"], .6 ** 6 * 37.5)

    def test_break_even_matches_the_board(self):
        import pricing
        be = pricing.dfs_break_even(1.0)
        self.assertAlmostEqual(slips.value(apart(be, be), POWER, "PrizePicks")["ret"], 1.0, places=9)

    def test_stress_trims_every_leg(self):
        v = slips.value(apart(.6, .6), POWER, "PrizePicks", stress=slips.STRESS)
        self.assertAlmostEqual(v["ret"], .57 * .57 * 3)

    def test_flex_pays_part(self):
        p, q = .6, .4
        v = slips.value(apart(p, p, p), FLEX, "PrizePicks")
        self.assertAlmostEqual(v["ret"], p ** 3 * 3 + 3 * p * p * q * 1.0)
        self.assertAlmostEqual(v["p_cash"], p ** 3 + 3 * p * p * q)              # 2 of 3 returns the stake
        v = slips.value(apart(*[p] * 5), FLEX, "PrizePicks")
        self.assertAlmostEqual(v["ret"], p ** 5 * 10 + 5 * p ** 4 * q * 2 + 10 * p ** 3 * q * q * 0.4)
        self.assertAlmostEqual(v["p_cash"], p ** 5 + 5 * p ** 4 * q)             # 0.4x back is not a cash
        v = slips.value(apart(.7, .6, .55, .5, .65, .58), FLEX, "PrizePicks")    # unequal chances: count it leg by leg
        ps, ret = [.7, .6, .55, .5, .65, .58], 0.0
        for hits in itertools.product((0, 1), repeat=6):
            w = math.prod(p if h else 1 - p for p, h in zip(ps, hits))
            ret += w * {6: 25, 5: 2, 4: 0.4}.get(sum(hits), 0)
        self.assertAlmostEqual(v["ret"], ret, places=9)

    def test_flex_with_same_game_legs(self):
        # the partial payouts use the same joint chances: check against brute force over the copula for two tied legs
        a, b, c = leg(1, .6, "points", "TOR"), leg(2, .6, "points", "TOR"), leg(3, .55, "sog", "BOS", game=2)
        j = slips.joint([a, b])
        p_all, p_ab_only = j * .55, j * .45
        p_one_of_ab = (.6 - j) * 2 * .55
        v = slips.value([a, b, c], FLEX, "PrizePicks")
        self.assertAlmostEqual(v["ret"], p_all * 3 + (p_ab_only + p_one_of_ab) * 1.0, places=9)

    def test_push_drops_a_level(self):
        a, b, c = apart(.6, .6, .6)
        a["push"] = .2
        v = slips.value([a, b], POWER, "PrizePicks")                           # a 2-pick with a push is refunded
        self.assertAlmostEqual(v["ret"], .8 * (.36 * 3) + .2 * 1.0)
        self.assertAlmostEqual(v["p_all"], .8 * .36); self.assertAlmostEqual(v["p_cash"], .8 * .36)
        v = slips.value([a, b, c], POWER, "PrizePicks")                        # a 3-pick becomes a 2-pick
        self.assertAlmostEqual(v["ret"], .8 * (.216 * 6) + .2 * (.36 * 3))
        v = slips.value([a, b, c], FLEX, "PrizePicks", cfg={"fallback": POWER})   # Flex has no 2-pick: it becomes Power
        self.assertAlmostEqual(v["ret"], .8 * (.216 * 3 + 3 * .36 * .4 * 1.0) + .2 * (.36 * 3))
        v = slips.value([a, b, c], FLEX, "PrizePicks")                         # no table to fall back to: a refund
        self.assertAlmostEqual(v["ret"], .8 * (.216 * 3 + 3 * .36 * .4 * 1.0) + .2 * 1.0)
        b["push"] = .1                                                         # two legs that can push
        v = slips.value([a, b, c], POWER, "PrizePicks")
        self.assertAlmostEqual(v["ret"], .8 * .9 * (.216 * 6) + (.2 * .9 + .8 * .1) * (.36 * 3) + .2 * .1 * 1.0)

    def test_pick6_multipliers_cut_and_cap(self):
        a, b = apart(.4, .45, mult=1.5)
        b["mult"] = 2.0
        v = slips.value([a, b], P6, "Pick6")
        self.assertAlmostEqual(v["pays"], 3 * 1.5 * 2.0); self.assertAlmostEqual(v["ret"], .4 * .45 * 9)
        a["mult"] = b["mult"] = 3.0
        self.assertEqual(slips.value([a, b], P6, "Pick6")["pays"], 20.0)       # 27x is capped at the 2-pick's 20x
        shooter, goalie = leg(1, .6, "sog", "TOR"), leg(2, .55, "saves", "FLA")
        v = slips.value([shooter, goalie], P6, "Pick6")
        self.assertAlmostEqual(v["factor"], 0.82); self.assertAlmostEqual(v["pays"], 3 * 0.82)
        self.assertAlmostEqual(v["ret"], slips.joint([shooter, goalie]) * 3 * 0.82)
        self.assertEqual(slips.value([shooter, goalie], POWER, "PrizePicks")["factor"], 1.0)   # the cut is Pick6's alone
        five = apart(.6, .6, .6, .6, .6)
        v = slips.value(five, P6, "Pick6")
        self.assertAlmostEqual(v["ret"], .6 ** 5 * 12 + 5 * .6 ** 4 * .4 * 1.0)   # 4 of 5 returns the stake
        five[0]["mult"] = 8.0
        v = slips.value(five, P6, "Pick6")
        self.assertAlmostEqual(v["ret"], .6 ** 5 * 96 + 5 * .6 ** 4 * .4 * 6.0)   # ... capped at 6x with multipliers

    def test_slip_summary(self):
        legs = apart(.6, .6, .6)
        legs[0]["push"] = .2
        s = slips.slip(legs, "PrizePicks", "PrizePicks Power")
        self.assertEqual((s["n"], s["play"], s["pays"], s["pushes"], s["same_game"], s["promo"]), (3, "PrizePicks Power", 6.0, 1, False, False))
        self.assertAlmostEqual(s["ev"], .8 * (.216 * 6) + .2 * (.36 * 3) - 1)
        self.assertAlmostEqual(s["ev_stress"], .8 * (.57 ** 3 * 6) + .2 * (.57 ** 2 * 3) - 1)
        self.assertLess(s["ev_stress"], s["ev"])
        self.assertAlmostEqual(s["joint"], .216); self.assertAlmostEqual(s["indep"], .216)
        self.assertIsNone(slips.slip(legs[:2], "PrizePicks", "PrizePicks Flex"))   # Flex has no 2-pick
        self.assertEqual(s["legs"], [l["id"] for l in legs])


class Lineup(unittest.TestCase):
    def test_rules(self):
        a, b = leg(1, .6, team="TOR"), leg(2, .6, team="FLA")
        self.assertIsNone(slips.allowed([a, b]))
        self.assertEqual(slips.allowed([a, leg(1, .6, "points", "TOR")]), "one pick per player")
        self.assertEqual(slips.allowed([a, leg(3, .6, team="TOR")]), "needs players from 2 teams")
        self.assertEqual(slips.allowed([{**a, "promo": "Stat Slice"}, {**b, "promo": "Power Up"}]), "one promo pick per entry")
        self.assertIsNone(slips.allowed([{**a, "promo": "Stat Slice"}, b]))
        nameless = [{**a, "player_id": None, "name": "X"}, {**b, "player_id": None, "name": "X"}]
        self.assertEqual(slips.allowed(nameless), "one pick per player")


class Search(unittest.TestCase):
    def pool(self):
        legs = apart(.66, .63, .61, .6, .58, .57)
        legs += [leg(7, .62, "points", "T0", game=1, proj=1.0), leg(8, .6, "saves", "T9", game=2),
                 leg(9, .59, "sog", "T0", game=1, promo="Stat Slice"), leg(10, .64, "sog", "T3", game=4, promo="Power Up", mult=1.3)]
        legs[2]["push"] = .15
        return legs

    def brute(self, legs, app, tables):
        best = {}
        for n in range(2, 7):
            for combo in itertools.combinations(sorted(legs, key=lambda l: (-l["p"], l["id"]))[:slips.SEARCH_TOP[n]], n):
                if slips.allowed(list(combo)):
                    continue
                for play in slips.PLAYS[app]:
                    s = slips.slip(list(combo), app, play, tables)
                    if s is not None and (str(n) not in best or slips.slip_key(s) < slips.slip_key(best[str(n)])):
                        best[str(n)] = s
        return best

    def test_finds_the_best_of_each_size(self):
        for app in ("PrizePicks", "Pick6"):
            legs = self.pool()
            out = slips.best_slips(legs, app)
            want = self.brute(legs, app, slips.PAYOUTS)
            self.assertEqual(set(out["by_size"]), set(want))
            for n, s in want.items():
                self.assertEqual(out["by_size"][n]["legs"], s["legs"], (app, n))
                self.assertEqual(out["by_size"][n]["play"], s["play"])
                self.assertAlmostEqual(out["by_size"][n]["ev_stress"], s["ev_stress"], places=12)
            top = out["top"]
            self.assertEqual(len(top), 3)
            self.assertEqual(top, sorted(top, key=slips.slip_key))
            self.assertEqual(top[0], min(out["by_size"].values(), key=slips.slip_key))
            self.assertEqual(out["n_legs"], len(legs))
            by_id = {l["id"]: l for l in legs}
            for s in list(out["by_size"].values()) + top:
                self.assertIsNone(slips.allowed([by_id[i] for i in s["legs"]]))
            self.assertEqual(len({tuple(sorted(s["legs"])) for s in top}), 3)        # one play type per set of legs

    def test_counts_what_it_valued(self):
        out = slips.best_slips(apart(.6, .6, .6, .6), "PrizePicks")
        self.assertEqual(out["searched"], 6 + 4 * 2 + 1 * 2)                         # Power at every size, Flex from 3
        self.assertEqual(slips.best_slips(apart(.6, .6, .6, .6), "Pick6")["searched"], 6 + 4 + 1)
        self.assertEqual(slips.best_slips(apart(.6), "PrizePicks")["top"], [])

    def test_ranks_by_the_stress_test(self):
        # a 6-pick of 60% legs is worth more on paper; after the trim the order can change, and ties break to fewer legs
        out = slips.best_slips(apart(*[.6] * 6), "PrizePicks", sizes=(2, 6))
        two, six = out["by_size"]["2"], out["by_size"]["6"]
        self.assertEqual(out["top"][0]["n"], 6 if six["ev_stress"] > two["ev_stress"] else 2)
        same = slips.best_slips(apart(.6, .6, .6), "PrizePicks", sizes=(2,))
        self.assertEqual(same["top"][0]["legs"], ["1|sog|1", "2|sog|2"])            # equal value: the stable order

    def test_own_tables_and_settings(self):
        legs = apart(.6, .6, .6)
        st = slips.settings(None, {"2": {"all": 2.5, "cap": 20.0}, "3": {"all": 5.0, "cap": 60.0}})
        cfg, tables = slips.run_cfg(st)
        self.assertEqual(slips.best_slips(legs, "Pick6", tables, cfg)["by_size"]["3"]["pays"], 5.0)
        self.assertEqual(st["payouts"]["PrizePicks Power"], POWER)
        self.assertIn("this build", st["payouts_from"]["Pick6"])
        st = slips.settings(None, {"2": {"all": 3.0}})                               # a table with no 3-pick: not trusted
        self.assertEqual(st["payouts"]["Pick6"], P6)
        self.assertIn("default", st["payouts_from"]["Pick6"])
        self.assertEqual(slips.run_cfg(None)[0]["factor"][("sog_opp_g", "same")], 0.82)
        json.dumps(slips.settings({"tm_pts": {"rho": .2, "n": 100, "games": 40}}, None))   # ships in the page's data


class Measure(unittest.TestCase):
    def test_implied_correlation_round_trips(self):
        for pa, pb, r in ((.4, .6, -.5), (.5, .5, 0.0), (.45, .52, .3), (.3, .35, .8)):
            both = slips.bvn(slips.ninv(pa), slips.ninv(pb), r)
            self.assertAlmostEqual(slips.implied_rho(pa, pb, both), r, places=5)
        self.assertIsNone(slips.implied_rho(0.0, .5, 0.0))
        self.assertIsNone(slips.implied_rho(.4, .5, .45))                           # together more often than either

    def test_from_box_scores(self):
        import numpy as np
        import pandas as pd
        rng = np.random.default_rng(7)
        sk, gl = [], []
        for g in range(400):
            a, b = g % 8, (g % 8 + 1 + g % 5) % 8
            if a == b:
                b = (a + 1) % 8
            for team, opp in ((a, b), (b, a)):
                pace = rng.gamma(8.0, 1 / 8.0)                                     # the team's night: shared by its skaters
                shots = 0
                for k in range(6):
                    s = rng.poisson((2.2 + 0.5 * k) * pace)
                    shots += s
                    sk.append({"season": 2027, "game_id": g, "team_abbrev": f"T{team}", "player_id": team * 10 + k,
                               "shots_on_goal": s, "points": rng.poisson(0.7 * pace), "toi_min": 16.0})
                gl.append({"season": 2027, "game_id": g, "team_abbrev": f"T{opp}", "player_id": 900 + opp,
                           "saves": shots - rng.binomial(shots, 0.1), "toi_min": 60.0})
        sk, gl = pd.DataFrame(sk), pd.DataFrame(gl)
        m = slips.measure_rho(sk, gl, 2027)
        for k in ("sog_opp_g", "sog_opp_g_top", "sog_own_g", "tm_sog", "opp_sog", "tm_pts", "opp_pts", "tm_sog_pts", "opp_sog_pts", "pts_opp_g", "pts_own_g", "g_g"):
            self.assertIn(k, m)
        self.assertEqual((m["g_g"]["n"], m["g_g"]["games"]), (400, 400))            # one pair of goalies a game
        self.assertEqual(m["tm_sog"]["games"], 400)
        self.assertEqual(m["sog_opp_g"]["n"], 400 * 12)
        self.assertEqual(m["tm_sog"]["n"], 400 * 2 * 15)                            # each pair of teammates once
        self.assertGreater(m["sog_opp_g"]["rho"], 0.25)                             # his shots are the other goalie's saves
        self.assertGreater(m["tm_sog"]["rho"], 0.1); self.assertGreater(m["tm_pts"]["rho"], 0.05)
        self.assertLess(abs(m["sog_own_g"]["rho"]), 0.2); self.assertLess(abs(m["opp_sog"]["rho"]), 0.1)    # unrelated here
        self.assertEqual(slips.measure_rho(sk[sk.season == 1], gl, 1), {})
        short = slips.measure_rho(sk[sk.game_id < 3], gl[gl.game_id < 3], 2027)     # under 50 pairs: nothing claimed
        self.assertNotIn("g_g", short)

    def test_blend_leans_on_the_games_played(self):
        G = slips.RHO_PRIOR_GAMES
        rho, top = slips.blend_rho({"tm_pts": {"rho": .5, "n": 50000, "games": G}, "tm_pts_top": {"rho": .1, "n": 9000, "games": G},
                                    "g_g": {"rho": -.5, "n": 300, "games": 300}, "made_up": {"rho": 1, "n": 9, "games": 9},
                                    "tm_sog": {"rho": .9, "n": 99999}})
        self.assertAlmostEqual(rho["tm_pts"], (.5 + slips.RHO["tm_pts"]) / 2, places=4)
        self.assertAlmostEqual(top["tm_pts"], (.1 + slips.RHO_TOP["tm_pts"]) / 2, places=4)
        self.assertAlmostEqual(rho["g_g"], (300 * -.5 + G * slips.RHO["g_g"]) / (300 + G), places=4)
        self.assertNotIn("made_up", rho)
        self.assertEqual(rho["tm_sog"], slips.RHO["tm_sog"])                        # no game count: not trusted at all
        self.assertEqual(slips.blend_rho(None), (slips.RHO, slips.RHO_TOP))
        self.assertEqual(slips.RHO["tm_pts"], 0.23)                                 # the module's own table is not touched


PAGE_HARNESS = r"""
const fs = require("fs");
const D = {slips: JSON.parse(fs.readFileSync(process.argv[2], "utf8"))};
const store = {get: (k, d) => d}, hasVal = v => v !== undefined && v !== null && v !== "" && !isNaN(+v);
__PAGE__
const cases = JSON.parse(fs.readFileSync(process.argv[3], "utf8")), st = slipSettings(), out = {defaults: SLIP_DEF};
out.numbers = cases.numbers.map(c => c.R ? mvn(c.z, c.R) : c.inv !== undefined ? nInv(c.inv) : bvn(c.h, c.k, c.r));
out.settings = {stress: st.stress, payouts: st.payouts, factor: [...st.factor], search_top: st.search_top, plays: st.plays};
out.search = cases.search.map(c => { const b = bestSlips(c.legs, c.app, st); return {top: b.top, by_size: b.by_size, searched: b.searched, n_legs: b.n_legs}; });
out.entries = cases.entries.map(c => slipBook(c.legs, c.app, st).slip(c.legs.map((_, i) => i), c.play));
out.allowed = cases.allowed.map(c => slipAllowed(c, st));
process.stdout.write(JSON.stringify(out));
"""


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class PageMirror(unittest.TestCase):
    """The page's own slip maths (cut out of template.html and run under node) against slips.py."""

    def page_code(self):
        with open(os.path.join(HERE, "template.html"), encoding="utf-8") as f:
            src = f.read()
        erfc = src[src.index("function erfc(x){"):]
        erfc = erfc[:erfc.index("\n}\n") + 3]
        a = src.index("// ---------- slips: entries of 2-6 legs")
        b = src.index("// ---------- slips: the board's legs")
        return erfc + src[a:b]

    def rnd_legs(self, rng, n, app):
        legs = []
        for i in range(n):
            mk = rng.choice(["sog", "sog", "sog", "points", "points", "saves"])
            game = rng.randrange(1, 4)
            team = f"G{game}{rng.choice('AB')}"
            p = round(rng.uniform(.5, .72), 4)
            l = leg(i + 1, p, mk, team, game, rng.choice(["OVER", "UNDER"]),
                    mult=rng.choice([1.0, 1.0, 1.0, 0.8, 1.3, 1.5]) if app == "Pick6" else 1.0,
                    push=rng.choice([0.0, 0.0, 0.0, round(rng.uniform(.05, .3), 3)]),
                    promo=rng.choice([None, None, None, None, "Stat Slice"]) if app == "Pick6" else None,
                    proj=rng.choice([None, 0.4, 0.9, 2.0, 3.1]))
            legs.append(l)
        return legs

    def test_page_matches_python(self):
        import random
        rng = random.Random(11)
        st = slips.settings({"tm_pts": {"rho": .21, "n": 9000, "games": 320}, "sog_opp_g_top": {"rho": .33, "n": 2500, "games": 300}},
                            {"2": {"all": 3.0, "cap": 20.0}, "3": {"all": 6.0, "cap": 60.0}, "4": {"all": 10.0, "cap": 100.0},
                             "5": {"all": 12.0, "cap": 150.0, "miss1": 1.0, "cap1": 6.0}, "6": {"all": 25.0, "cap": 300.0, "miss1": 1.5, "cap1": 10.0}})
        cfg, tables = slips.run_cfg(st)
        numbers = [{"h": rng.uniform(-2, 2), "k": rng.uniform(-2, 2), "r": rng.uniform(-.95, .95)} for _ in range(40)]
        numbers += [{"inv": rng.uniform(0.001, 0.999)} for _ in range(40)]
        for n in (3, 4, 5, 6):
            for _ in range(6):
                r = rng.uniform(-.1, .45)
                R = [[1.0 if i == j else round(r + (0.05 if (i + j) % 2 else -0.03), 4) for j in range(n)] for i in range(n)]
                numbers.append({"z": [rng.uniform(-1, 1.5) for _ in range(n)], "R": R})
        search = [{"app": app, "legs": self.rnd_legs(rng, n, app)} for app in ("PrizePicks", "Pick6") for n in (2, 5, 8, 11)]
        entries = []
        for app, plays in slips.PLAYS.items():
            for play in plays:
                for n in (2, 3, 4, 5, 6):
                    entries.append({"app": app, "play": play, "legs": self.rnd_legs(rng, n, app)})
        allowed = [self.rnd_legs(rng, n, "Pick6") for n in (2, 2, 3, 3, 4)] + [[leg(1, .6), leg(1, .6, "points")]]
        d = tempfile.mkdtemp()
        try:
            js, sf, cf = (os.path.join(d, x) for x in ("page.js", "settings.json", "cases.json"))
            for path, text in ((js, PAGE_HARNESS.replace("__PAGE__", self.page_code())), (sf, json.dumps(st)),
                               (cf, json.dumps({"numbers": numbers, "search": search, "entries": entries, "allowed": allowed}))):
                with open(path, "w", encoding="utf-8") as f:
                    f.write(text)
            run = subprocess.run(["node", js, sf, cf], capture_output=True, text=True, timeout=120)
            self.assertEqual(run.returncode, 0, run.stderr[-2000:])
            page = json.loads(run.stdout)
        finally:
            shutil.rmtree(d)
        # the page's built-in defaults (used only if a build ships none) are this module's
        want = slips.config()
        for k in want:
            self.assertEqual(page["defaults"][k], json.loads(json.dumps(want[k])), k)
        # the settings the page ends up with are the build's
        self.assertEqual(page["settings"]["stress"], slips.STRESS)
        self.assertEqual(page["settings"]["payouts"], st["payouts"])
        self.assertEqual({tuple(k.split("|")): v for k, v in page["settings"]["factor"]}, cfg["factor"])
        self.assertEqual(page["settings"]["search_top"], {str(k): v for k, v in slips.SEARCH_TOP.items()})
        self.assertEqual(page["settings"]["plays"], {k: list(v) for k, v in slips.PLAYS.items()})
        for c, got in zip(numbers, page["numbers"]):
            want = slips.mvn(c["z"], c["R"]) if "R" in c else slips.ninv(c["inv"]) if "inv" in c else slips.bvn(c["h"], c["k"], c["r"])
            self.assertAlmostEqual(got, want, places=10)

        def same(a, b, what):
            self.assertEqual(a is None, b is None, what)
            if a is None:
                return
            for k in ("app", "play", "n", "legs", "same_game", "promo", "pushes"):
                self.assertEqual(a[k], b[k], (what, k))
            for k in ("pays", "factor", "p_all", "p_cash", "joint", "indep", "ev", "ev_stress"):
                self.assertAlmostEqual(a[k], b[k], places=9, msg=str((what, k)))
        for c, got in zip(entries, page["entries"]):
            same(slips.Book(c["legs"], c["app"], cfg).slip(tuple(range(len(c["legs"]))), c["play"], tables), got, (c["app"], c["play"], len(c["legs"])))
        for i, (c, got) in enumerate(zip(search, page["search"])):
            want = slips.best_slips(c["legs"], c["app"], tables, cfg)
            self.assertEqual((want["searched"], want["n_legs"]), (got["searched"], got["n_legs"]), i)
            self.assertEqual(sorted(want["by_size"]), sorted(got["by_size"]), i)
            for n in want["by_size"]:
                same(want["by_size"][n], got["by_size"][n], (i, "size", n))
            self.assertEqual(len(want["top"]), len(got["top"]), i)
            for a, b in zip(want["top"], got["top"]):
                same(a, b, (i, "top"))
        self.assertEqual([slips.allowed(c) for c in allowed], page["allowed"])


if __name__ == "__main__":
    unittest.main()
