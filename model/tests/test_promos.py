"""Pick6 promo cards (Stat Slice: the line cut, More only at 1x; Power Up: both sides boosted): read from the page as
their own cards and folded onto the player's line with the ordinary multipliers kept; judged for what they pay;
Pick6's own payout table and lineup rules; and the slip legs the board builds from one app's lines."""
import datetime as dt
import json
import os
import tempfile
import unittest

import pick6
import players
import pricing
import props_board as pb
import slips
from tests.fixtures import make_pick6_fixture as fx
from tests.test_picks import NO_MKT, row
from tests.test_players import ROSTERS

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
NOW = dt.datetime(2026, 11, 3, 20, 0, tzinfo=dt.timezone.utc)
SLATE = [{"id": 2026020101, "date": "2026-11-03", "start": "2026-11-04T00:00:00Z", "home": "FLA", "away": "TOR", "state": "FUT"}]


def cards_page(cards, promos=True, payouts=True):
    """A Pick6 page in its card format. cards: [(dk id, name, team, [(market id, line, more, less, promo type, cut from)])]."""
    pc = {"pickCategoryId": 31, "pickCategoryById": {"31": {"filterKey": "shots-on-goal", "categoryName": "Shots On Goal"}},
          "pickSixMarketById": {"208": {"name": "Shots on Goal"}, "581": {"name": "Shots on Goal"}},
          "displayTeamById": {"1": {"name": "TOR"}, "2": {"name": "FLA"}},
          "competitionById": {"900": {"compId": 900, "startTime": "2026-11-04T00:00:00Z", "entityCompByDkId": {}}},
          "entityInfoByDkId": {}, "pickCardByPickableId": {}, "userLineupRequirements": {"minimumDistinctTeamCount": 2, "maximumPicksPerDkIdCount": 1}}
    if promos:
        pc["promotionalPickConfigurationsByPromotionTypeId"] = {
            "3": {"promotionalPickType": "Stat Slice", "maxNumberOfPromotionalPicks": 1, "minimumRequiredNumOfPicks": 2},
            "4": {"promotionalPickType": "Power Up", "maxNumberOfPromotionalPicks": 1, "minimumRequiredNumOfPicks": 2}}
    n = 0
    for dk, name, team, markets in cards:
        pc["entityInfoByDkId"][str(dk)] = {"fullName": name}
        pc["competitionById"]["900"]["entityCompByDkId"][str(dk)] = {"teamId": 1 if team == "TOR" else 2, "position": "RW"}
        for mk, line, more, less, ptype, cut in markets:
            n += 1
            sel = [{"statLinePropositionId": pick6.MORE_ID, "standingsMultiplier": more}]
            if less:
                sel.append({"statLinePropositionId": pick6.LESS_ID, "standingsMultiplier": less})
            m = {"pickSixMarketId": mk, "targetValue": line, "isPaused": False, "activeSelections": sel, "promoPickTypeId": ptype}
            if ptype not in (None, 1):
                m.update(originalTargetValue=cut if cut is not None else line, marketLimit=20)
            pc["pickCardByPickableId"][f"c{n}"] = {"entities": [{"dkId": dk, "compIds": [900]}], "activePickableMarkets": [m]}
    data = {"root": {"loaderData": {"routes/_homeShared": {"pickCardsResponse": pc}}}}
    if payouts:
        data["root"]["loaderData"]["routes/_homeShared"]["entryDetails"] = {"payoutPackages": [
            {"pickSetSize": 2, "payoutTiers": [{"numberOfPicksCorrect": 2, "guaranteedMultiplier": 3, "guaranteedMultiplierLimit": 20}]},
            {"pickSetSize": 3, "payoutTiers": [{"numberOfPicksCorrect": 3, "guaranteedMultiplier": 6, "guaranteedMultiplierLimit": 60}]},
            {"pickSetSize": 5, "payoutTiers": [{"numberOfPicksCorrect": 5, "guaranteedMultiplier": 12, "guaranteedMultiplierLimit": 150},
                                               {"numberOfPicksCorrect": 4, "guaranteedMultiplier": 1, "guaranteedMultiplierLimit": 6}]},
            {"pickSetSize": "x"}, {"pickSetSize": 4, "payoutTiers": []}]}
    stream = fx.flatten(data) + "\n"
    js = f"window.__reactRouterContext.streamController.enqueue({json.dumps(stream)});"
    return f"<html><body><script>window.__reactRouterContext = {{}};</script><script>{js}</script></body></html>"


MARNER = (501, "Mitch Marner", "TOR", [(208, 3.5, 1.1, 0.8, 1, None), (581, 2.5, 0.7, None, 1, None), (581, 4.5, 1.7, None, 1, None),
                                        (581, 2.5, 1.0, None, 3, 3.5)])              # Stat Slice: 3.5 cut to 2.5, More at 1x
TKACHUK = (502, "Matthew Tkachuk", "FLA", [(208, 3.5, 1.3, 1.3, 4, None)])           # a Power Up card on its own


class Cards(unittest.TestCase):
    def test_promo_cards_fold_onto_the_line(self):
        rows = pick6.extract(cards_page([MARNER, TKACHUK]))
        by = {(r["name"], r["line"]): r for r in rows}
        self.assertEqual(len(rows), 4)                                              # the promo is never a fifth row
        cut = by[("Mitch Marner", 2.5)]
        self.assertEqual((cut["mo"], cut["mu"], cut["promo"], cut["promo_sides"], cut["promo_from"], cut["mo_reg"], cut["limit"]),
                         (1.0, 0.0, "Stat Slice", "O", 3.5, 0.7, 20.0))
        self.assertNotIn("promo", by[("Mitch Marner", 3.5)])                        # his ordinary lines are untouched
        up = by[("Matthew Tkachuk", 3.5)]
        self.assertEqual((up["mo"], up["mu"], up["promo"], up["promo_sides"], up["promo_from"], up["mo_reg"], up["mu_reg"]),
                         (1.3, 1.3, "Power Up", "OU", None, None, None))
        self.assertTrue(pick6.understood)
        self.assertEqual(pick6.last_info["promos"], {"Stat Slice": {"max": 1, "min_picks": 2}, "Power Up": {"max": 1, "min_picks": 2}})
        self.assertEqual(pick6.last_info["lineup"], {"min_teams": 2, "max_per_player": 1})
        self.assertEqual(pick6.last_info["payouts"], {"2": {"all": 3.0, "cap": 20.0}, "3": {"all": 6.0, "cap": 60.0},
                                                      "5": {"all": 12.0, "cap": 150.0, "miss1": 1.0, "cap1": 6.0}})

    def test_board_rows_carry_the_promo(self):
        rows, st = pick6.build_rows(cards_page([MARNER, TKACHUK]), SLATE, ROSTERS, "2026-11-03T20:00:00+00:00", NOW)
        self.assertEqual((st["raw"], st["kept"]), (4, 4))
        by = {(r["player_id"], r["line"]): r for r in rows}
        cut = by[(8478483, 2.5)]
        self.assertEqual({f: cut.get(f) for f in pick6.PROMO_FIELDS}, {"promo": "Stat Slice", "promo_sides": "O", "promo_from": 3.5,
                                                                       "limit": 20.0, "mo_reg": 0.7, "mu_reg": 0.0})
        self.assertFalse(any(f in by[(8478483, 3.5)] for f in pick6.PROMO_FIELDS))
        for r in rows:
            for f in pick6.REQUIRED:
                self.assertNotIn(r[f], (None, ""), f)

    def test_an_empty_board_is_understood_not_a_parse_failure(self):
        self.assertEqual(pick6.extract(cards_page([])), [])
        self.assertTrue(pick6.understood)                                           # the card data was there, with no cards
        self.assertEqual(pick6.last_info["lineup"], {"min_teams": 2, "max_per_player": 1})   # its rules still hold
        self.assertEqual(pick6.extract("<html><body>Access Denied</body></html>"), [])
        self.assertFalse(pick6.understood)
        self.assertEqual(pick6.last_info, {})                                       # nothing carried over from the page before

    def test_pull_status(self):
        keep = pick6.urllib.request.urlopen, pick6.FAILED, pick6.status, pick6.stats
        d = tempfile.mkdtemp()
        pick6.FAILED = os.path.join(d, "failed.html")

        class Resp:
            def __init__(self, page): self.page = page
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return self.page.encode()
        try:
            for page, want, saved in ((cards_page([MARNER, TKACHUK]), "ok", False), (cards_page([]), "no lines posted", False),
                                      ("<html><body>Access Denied</body></html>", "parse failed: 0 rows", True)):
                pick6.urllib.request.urlopen = lambda req, timeout=30, page=page: Resp(page)
                rows, st = pick6._pull(SLATE, ROSTERS)
                self.assertEqual(pick6.status, want)
                self.assertEqual(os.path.exists(pick6.FAILED), saved, want)          # only an unreadable page is kept for the fix
                if want == "ok":
                    self.assertEqual((len(rows), st["promos"], st["lineup"]["min_teams"], st["payouts"]["3"]["all"]), (4, 2, 2, 6.0))
                    self.assertEqual(sorted(st["promo_rules"]), ["Power Up", "Stat Slice"])
        finally:
            pick6.urllib.request.urlopen, pick6.FAILED, pick6.status, pick6.stats = keep

    @unittest.skipUnless(os.path.exists(os.path.join(FIX, "pick6.html")), "no real Pick6 page saved yet")
    def test_real_saved_page(self):
        # the page the build fetched on 2026-11-03: three Stat Slices and three Power Ups among its 714 lines
        with open(os.path.join(FIX, "pick6.html"), encoding="utf-8", errors="replace") as f:
            rows = pick6.extract(f.read())
        promo = {r["name"]: r for r in rows if r.get("promo")}
        self.assertEqual(sorted(promo), ["Cole Caufield", "Connor McDavid", "Filip Forsberg", "Leo Carlsson", "Matt Boldy", "Nathan MacKinnon"])
        mc = promo["Connor McDavid"]
        self.assertEqual((mc["line"], mc["mo"], mc["mu"], mc["promo"], mc["promo_sides"], mc["promo_from"], mc["mo_reg"]),
                         (2.5, 1.0, 0.0, "Stat Slice", "O", 3.5, 0.7))              # the ordinary 2.5 pays 0.7x
        ff = promo["Filip Forsberg"]
        self.assertEqual((ff["line"], ff["mo"], ff["mu"], ff["promo"], ff["promo_sides"], ff["mo_reg"], ff["mu_reg"]),
                         (2.5, 1.3, 1.3, "Power Up", "OU", 1.0, 0.9))
        self.assertEqual(len([r for r in rows if r["name"] == "Connor McDavid" and r["line"] == 2.5]), 1)
        self.assertEqual(pick6.last_info["promos"]["Stat Slice"], {"max": 1, "min_picks": 2})
        self.assertEqual(pick6.last_info["promos"]["Gimme Pick"], {"max": 1, "min_picks": 3})
        self.assertEqual(pick6.last_info["lineup"], {"min_teams": 2, "max_per_player": 1})
        self.assertEqual(pick6.last_info["payouts"], slips.PAYOUTS["Pick6"])        # the table the slips default to is the page's


class MergePromo(unittest.TestCase):
    REG = {"name": "A", "line": 2.5, "mo": 0.7, "mu": 0.0}

    def test_each_side_takes_the_better_multiplier(self):
        cut = pick6.merge_promo(self.REG, {"name": "A", "line": 2.5, "mo": 1.0, "mu": 0.0, "promo": "Stat Slice", "promo_from": 3.5, "limit": 20.0})
        self.assertEqual((cut["mo"], cut["mu"], cut["promo_sides"], cut["mo_reg"], cut["mu_reg"]), (1.0, 0.0, "O", 0.7, 0.0))
        up = pick6.merge_promo({"line": 2.5, "mo": 1.0, "mu": 0.9}, {"line": 2.5, "mo": 1.3, "mu": 1.3, "promo": "Power Up"})
        self.assertEqual((up["mo"], up["mu"], up["promo_sides"], up["mo_reg"], up["mu_reg"]), (1.3, 1.3, "OU", 1.0, 0.9))
        one = pick6.merge_promo({"line": 2.5, "mo": 1.5, "mu": 0.9}, {"line": 2.5, "mo": 1.3, "mu": 1.3, "promo": "Power Up"})
        self.assertEqual((one["mo"], one["mu"], one["promo_sides"]), (1.5, 1.3, "U"))   # the ordinary More already pays more

    def test_a_promo_that_pays_no_more_changes_nothing(self):
        out = pick6.merge_promo({"line": 2.5, "mo": 1.3, "mu": 1.3}, {"line": 2.5, "mo": 1.3, "mu": 1.0, "promo": "Power Up"})
        self.assertEqual(out, {"line": 2.5, "mo": 1.3, "mu": 1.3})

    def test_a_promo_on_its_own(self):
        out = pick6.merge_promo(None, {"line": 2.5, "mo": 1.0, "mu": 0.0, "promo": "Stat Slice", "promo_from": 3.5})
        self.assertEqual((out["promo"], out["promo_sides"], out["mo_reg"], out["mu_reg"]), ("Stat Slice", "O", None, None))

    def test_the_inputs_are_not_changed(self):
        reg = dict(self.REG)
        pick6.merge_promo(reg, {"line": 2.5, "mo": 1.0, "mu": 0.0, "promo": "Stat Slice"})
        self.assertEqual(reg, self.REG)


class PayoutTable(unittest.TestCase):
    def test_reads_the_pages_own_table(self):
        tree = {"a": [{"entryDetails": {"payoutPackages": [
            {"pickSetSize": 6, "payoutTiers": [{"numberOfPicksCorrect": 6, "guaranteedMultiplier": "25", "guaranteedMultiplierLimit": 300},
                                               {"numberOfPicksCorrect": 5, "guaranteedMultiplier": 1.5, "guaranteedMultiplierLimit": 10}]},
            {"pickSetSize": 2, "payoutTiers": [{"numberOfPicksCorrect": 2, "guaranteedMultiplier": 3, "guaranteedMultiplierLimit": 20}]},
            {"pickSetSize": 3, "payoutTiers": [{"numberOfPicksCorrect": 2, "guaranteedMultiplier": 1}]}, "junk", {"pickSetSize": None}]}}]}
        self.assertEqual(pick6.payout_table(tree), {"6": {"all": 25.0, "cap": 300.0, "miss1": 1.5, "cap1": 10.0}, "2": {"all": 3.0, "cap": 20.0}})
        self.assertEqual(pick6.payout_table({"x": 1}), {})
        self.assertEqual(pick6.payout_table({"entryDetails": {"payoutPackages": None}}), {})


class DayBoard(unittest.TestCase):
    def test_a_promo_card_on_its_own_replaces_only_its_line(self):
        path = os.path.join(tempfile.mkdtemp(), "day.json")
        slate = [{"id": 1, "date": "2026-11-10", "start": "2026-11-11T00:00:00Z", "home": "FLA", "away": "TOR", "state": "FUT"}]
        now = dt.datetime(2026, 11, 10, 18, 25, tzinfo=dt.timezone.utc)
        line = lambda ln, at, **kw: {"name": "P1", "player_id": 1, "team": "TOR", "game": 1, "date": "2026-11-10", "market": "sog",
                                     "line": ln, "mo": 1.0, "mu": 1.0, "source": "Pick6", "fetched_at": at, "pos": "F", **kw}
        cats = {"categories": {"31": ["shots-on-goal", "Shots On Goal", "31"]}}
        pick6.merge_day([line(2.5, "2026-11-10T16:09:00+00:00", mo=0.7, mu=0.0), line(3.5, "2026-11-10T16:09:00+00:00")],
                        {"category": 31, **cats}, slate, now - dt.timedelta(hours=2), path)
        # the featured page now shows only his Stat Slice (2.5, More at 1x) with no ordinary card beside it
        promo = line(2.5, "2026-11-10T18:25:00+00:00", mu=0.0, promo="Stat Slice", promo_sides="O", promo_from=3.5)
        rows, st = pick6.merge_day([promo], {"category": 1, **cats}, slate, now, path)
        got = {r["line"]: (r.get("reused", False), r.get("promo")) for r in rows}
        self.assertEqual(got, {2.5: (False, "Stat Slice"), 3.5: (True, None)})      # his 3.5 from the earlier pull is kept
        # a promo folded onto his ordinary card (the ordinary multipliers are known) is his card: it replaces his lines
        merged = {**promo, "mo_reg": 0.7, "mu_reg": 0.0}
        rows, st = pick6.merge_day([merged], {"category": 1, **cats}, slate, now, path)
        self.assertEqual([r["line"] for r in rows], [2.5])


class Judged(unittest.TestCase):
    def test_promo_value_rule(self):
        V = pricing.PROMO_VALUE
        self.assertTrue(pricing.promo_lean("sog", .5, .5, 1.3))                     # 0.65 on both numbers
        self.assertTrue(pricing.promo_lean("points", V / 1.1, V / 1.1, 1.1))        # exactly at the bar
        self.assertFalse(pricing.promo_lean("sog", .52, .52, 1.1))                  # 0.572: under the bar
        self.assertFalse(pricing.promo_lean("sog", .52, .40, 1.3))                  # the market's own number does not clear it
        self.assertFalse(pricing.promo_lean("sog", .47, .55, 1.3))                  # not the likelier side
        self.assertFalse(pricing.promo_lean("sog", .9, .9, 1.0))                    # 1x is an ordinary side
        self.assertFalse(pricing.promo_lean("sog", .6, None, 1.3))                  # no market price
        self.assertFalse(pricing.promo_lean("sog", .6, float("nan"), 1.3))
        self.assertFalse(pricing.promo_lean("saves", .6, .6, 1.3))
        self.assertFalse(pricing.promo_lean("sog", .6, .6, None))
        self.assertEqual(pricing.config()["promo_value"], V)
        self.assertGreater(V, pricing.dfs_break_even(1.0))                          # above a 1x leg's break-even

    def test_which_side_is_the_promo(self):
        cut = row(1, "A", 2.5, .6, mo=1.0, mu=0.0, source="Pick6", promo="Stat Slice", promo_sides="O")
        self.assertEqual(pb.promo_on(cut, "OVER"), "Stat Slice")
        self.assertIsNone(pb.promo_on(cut, "UNDER"))
        self.assertEqual(pb.side_offer(cut, "OVER")["promo"], "Stat Slice")
        self.assertIsNone(pb.promo_on(row(1, "A", 2.5, .6, source="Pick6"), "OVER"))
        both = row(1, "A", 2.5, .6, mo=1.3, mu=1.3, source="Pick6", promo="Power Up", promo_sides="OU")
        self.assertEqual((pb.promo_on(both, "OVER"), pb.promo_on(both, "UNDER")), ("Power Up", "Power Up"))

    def test_a_stat_slice_is_an_ordinary_side_at_its_multiplier(self):
        cut = row(1, "A", 2.5, .6, mo=1.0, mu=0.0, source="Pick6", promo="Stat Slice", promo_sides="O", promo_from=3.5, mo_reg=0.7)
        o = pb.pick_for([cut])
        self.assertEqual((o["tier"], o["side"], o["promo"], o["mult"]), ("lean", "OVER", "Stat Slice", 1.0))
        weak = row(1, "A", 2.5, .53, mo=1.0, mu=0.0, source="Pick6", promo="Stat Slice", promo_sides="O")
        self.assertEqual(pb.pick_for([weak])["tier"], "")                           # 53% at 1x is no lean, promo or not
        short = row(1, "A", 2.5, .6, mo=0.7, mu=0.0, source="Pick6")                # the same line without the promo
        self.assertEqual(pb.pick_for([short])["tier"], "")

    def test_a_power_up_is_judged_on_what_it_is_worth(self):
        up = row(1, "A", 2.5, .53, mo=1.3, mu=1.3, source="Pick6", promo="Power Up", promo_sides="OU")
        o = pb.pick_for([up])
        self.assertEqual((o["tier"], o["side"], o["promo"], o["mult"]), ("lean", "OVER", "Power Up", 1.3))   # 53% x 1.3 = 0.69
        plain = row(1, "A", 2.5, .53, mo=1.3, mu=1.3, source="Pick6")               # 1.3x on an ordinary card: priced in
        self.assertEqual(pb.pick_for([plain])["tier"], "")
        self.assertEqual(pb.pick_for([{**up, "p_mkt": None}])["tier"], "")          # no market price: no call
        self.assertEqual(pb.pick_for([row(1, "A", 2.5, .53, mo=1.3, mu=1.3, source="Pick6", promo="Power Up", promo_sides="OU",
                                          role_change={"from": "F1", "to": "F3"})])["tier"], "check")
        self.assertEqual(pb.pick_for([{**up, "cached": True}])["tier"], "")         # an old line is never a call

    def test_the_pick_carries_the_promo(self):
        up = row(1, "A", 2.5, .53, mo=1.3, mu=1.3, source="Pick6", promo="Power Up", promo_sides="OU")
        pp_ = row(1, "A", 2.5, .53, source="PrizePicks")
        out = pb.picks([up, pp_])
        self.assertEqual(len(out), 1)
        r = out[0]
        self.assertEqual((r["source"], r["pick_side"], r["pick_tier"], r["pick_promo"], r["lean"]), ("Pick6", "OVER", "lean", "Power Up", True))
        self.assertEqual(r["pick_apps"][0], {"app": "Pick6", "mult": 1.3, "price": None, "promo": "Power Up"})
        self.assertEqual(r["pick_apps"][1], {"app": "PrizePicks", "mult": 1.0, "price": None})   # the same bet without the boost
        plain = pb.picks([row(2, "B", 2.5, .6, source="PrizePicks")])[0]
        self.assertIsNone(plain["pick_promo"])
        self.assertNotIn("promo", plain["pick_apps"][0])
        for k in ("pick_promo", "promo_from", "p_push"):
            self.assertIn(k, pb.PICK_KEYS)


def leg_row(pid, p, team, game, source="PrizePicks", line=2.5, **kw):
    return row(pid, f"P{pid}", line, p, source=source, team=team, game=game, **kw)


class SlipLegs(unittest.TestCase):
    def test_one_apps_plays_and_leans(self):
        rows = [leg_row(1, .62, "TOR", 1, verdict="TAKE MORE", sog_tier="Strong"), leg_row(2, .40, "FLA", 1), leg_row(3, .52, "BOS", 2),
                leg_row(4, .60, "NYR", 2, source="Pick6"), leg_row(5, .58, "DAL", 3, cached=True), leg_row(6, .58, "COL", 3, fallback=True),
                leg_row(7, .58, "EDM", 4, stale=True), leg_row(8, .58, "VAN", 4, role_change={"from": "F1", "to": "F3"}),
                leg_row(9, .7, "SEA", 5, market="saves", line=27.5)]
        legs = pb.slip_legs(rows, "PrizePicks")
        self.assertEqual([(l["player_id"], l["side"], l["tier"]) for l in legs], [(1, "OVER", "play"), (2, "UNDER", "lean")])
        a = legs[0]
        self.assertEqual((a["id"], a["team"], a["game"], a["market"], a["line"], a["mult"], a["push"], a["promo"], a["app"]),
                         ("1|sog|1", "TOR", 1, "sog", 2.5, 1.0, 0.0, None, "PrizePicks"))
        self.assertAlmostEqual(legs[1]["p"], .60)
        self.assertEqual([l["player_id"] for l in pb.slip_legs(rows, "Pick6")], [4])
        self.assertEqual(pb.slip_legs([], "Pick6"), [])

    def test_push_chance_and_promo_travel_with_the_leg(self):
        rows = [leg_row(1, .62, "TOR", 1, source="Pick6", line=2.0, p_push=.24), leg_row(2, .6, "FLA", 1, source="Pick6", mo=1.0, mu=0.0,
                                                                                         promo="Stat Slice", promo_sides="O")]
        legs = {l["player_id"]: l for l in pb.slip_legs(rows, "Pick6")}
        self.assertEqual((legs[1]["push"], legs[1]["line"]), (.24, 2.0))
        self.assertEqual(legs[2]["promo"], "Stat Slice")

    def test_partners_are_added_when_an_entry_cannot_otherwise_be_made(self):
        promo = leg_row(1, .6, "TOR", 1, source="Pick6", mo=1.0, mu=0.0, promo="Stat Slice", promo_sides="O")
        others = [leg_row(2, .53, "FLA", 1, source="Pick6"),                         # 53% at 1x: worth 0.53
                  leg_row(3, .66, "BOS", 2, source="Pick6", mo=0.8, mu=0.0),         # 66% at 0.8x: worth 0.53
                  leg_row(4, .52, "NYR", 2, source="Pick6", mo=0.9, mu=0.9),         # worth 0.47: under the floor
                  leg_row(5, .54, "DAL", 3, source="Pick6", role_change={"from": "F1", "to": "F3"}),
                  leg_row(6, .54, "COL", 3, source="Pick6", cached=True),
                  leg_row(7, .7, "EDM", 4, source="Pick6", market="saves", line=27.5),
                  leg_row(8, .54, "VAN", 4, source="Pick6", mo=1.3, mu=1.3, promo="Power Up", promo_sides="OU", p_mkt=NO_MKT)]
        legs = pb.slip_legs([promo] + others, "Pick6")
        self.assertEqual([(l["player_id"], l["tier"]) for l in legs], [(3, "fill"), (1, "lean"), (2, "fill")])
        fill = legs[0]
        self.assertEqual((fill["side"], fill["mult"], fill["promo"]), ("OVER", 0.8, None))
        best = slips.best_slips(legs, "Pick6")
        self.assertEqual(sorted(best["by_size"]), ["2", "3"])
        self.assertTrue(all("1|sog|1" in s["legs"] or s["n"] == 2 for s in best["by_size"].values()))
        # with two ordinary legs of its own the app needs no partners; with no leg at all it gets none
        two = [leg_row(1, .6, "TOR", 1, source="Pick6"), leg_row(2, .6, "FLA", 1, source="Pick6")] + others
        self.assertEqual({l["tier"] for l in pb.slip_legs(two, "Pick6")}, {"lean"})
        self.assertEqual(pb.slip_legs(others[:4], "Pick6"), [])

    def test_partner_count_is_capped(self):
        promo = leg_row(1, .6, "TOR", 1, source="Pick6", mo=1.0, mu=0.0, promo="Stat Slice", promo_sides="O")
        many = [leg_row(10 + i, .53, f"T{i}", 2 + i, source="Pick6") for i in range(slips.FILLERS + 4)]
        legs = pb.slip_legs([promo] + many, "Pick6")
        self.assertEqual(sum(l["tier"] == "fill" for l in legs), slips.FILLERS)

    def test_a_line_that_met_every_bar_is_the_play_on_its_own_app(self):
        # his kept line is on Pick6; the PrizePicks line stood down as "alt line" although it met every bar of a play
        kept = leg_row(1, .64, "TOR", 1, source="Pick6", verdict="TAKE MORE", sog_tier="Lock")
        alt = leg_row(1, .63, "TOR", 1, verdict="PASS", reason="alt line (best is 2.5 more)", sog_tier="Strong")
        self.assertTrue(pb.play_grade(kept)); self.assertTrue(pb.play_grade(alt))
        self.assertFalse(pb.play_grade({**alt, "sog_tier": "review"}))
        self.assertFalse(pb.play_grade({**alt, "reason": "market only 53%"}))
        self.assertTrue(pb.play_grade({**alt, "market": "points", "sog_tier": None}))
        self.assertEqual(pb.pick_for([alt])["tier"], "play")                        # PrizePicks' own lines: this is its play
        self.assertEqual(pb.pick_for([kept, alt])["row"]["source"], "Pick6")        # the whole board: the kept line
        self.assertEqual([(l["tier"], l["app"]) for l in pb.slip_legs([kept, alt], "PrizePicks")], [("play", "PrizePicks")])

    def test_both_apps(self):
        rows = [leg_row(1, .62, "TOR", 1), leg_row(2, .60, "FLA", 1), leg_row(3, .61, "BOS", 2), leg_row(4, .6, "NYR", 2, source="Pick6")]
        out = pb.build_slips(rows)
        self.assertEqual(sorted(out), ["Pick6", "PrizePicks"])
        self.assertEqual((len(out["PrizePicks"]["legs"]), out["PrizePicks"]["n_legs"], sorted(out["PrizePicks"]["by_size"])), (3, 3, ["2", "3"]))
        self.assertEqual((len(out["Pick6"]["legs"]), out["Pick6"]["top"], out["Pick6"]["searched"]), (1, [], 0))   # one leg: no entry
        json.dumps(out)                                                             # ships in the page's data


if __name__ == "__main__":
    unittest.main()
