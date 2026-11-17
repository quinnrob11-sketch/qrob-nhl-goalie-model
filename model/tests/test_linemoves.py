"""Opening lines and line movement (linemoves): each prop's first line is kept, every change of line or price after
it is written with its time, a prop that comes off the board is written as such only when the pull proves it, and
cached pulls are never logged again."""
import csv
import datetime as dt
import os
import shutil
import tempfile
import unittest

import linemoves as lm

T0 = dt.datetime(2026, 11, 17, 15, 0, tzinfo=dt.timezone.utc)
SLATE = [{"id": 2026020340, "date": "2026-11-17", "away": "TOR", "home": "FLA", "start": "2026-11-18T00:00:00Z"},
         {"id": 2026020341, "date": "2026-11-17", "away": "BOS", "home": "LAK", "start": "2026-11-18T03:00:00Z"},
         {"id": 2026020355, "date": "2026-11-18", "away": "TOR", "home": "FLA", "start": "2026-11-19T00:00:00Z"}]


def at(minutes):
    return (T0 + dt.timedelta(minutes=minutes)).isoformat(timespec="seconds")


def dk(name, pid, line, over, under, t, team="FLA", teams=("TOR", "FLA"), day="2026-11-17"):
    return {"name": name, "player_id": pid, "goalie_id": pid, "team": team, "teams": list(teams), "date": day,
            "line": line, "over": over, "under": under, "fetched_at": at(t)}


def book(name, pid, line, over, under, t, book_="ESPN BET", market="sog", teams=("TOR", "FLA")):
    return {"name": name, "player_id": pid, "team": "TOR", "teams": list(teams), "date": "2026-11-17", "market": market,
            "line": line, "over": over, "under": under, "book": book_, "source": book_, "fetched_at": at(t)}


def app(name, pid, line, mo, mu, t, game=2026020340, market="sog", **kw):
    return {"name": name, "player_id": pid, "team": "TOR", "game": game, "date": "2026-11-17", "market": market,
            "line": line, "mo": mo, "mu": mu, "fetched_at": at(t), **kw}


class Log(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.d)

    def pull(self, t, pick6_full=(), **src):
        obs = lm.observations(SLATE, at(t), **src)
        return lm.record(obs, lm.covered(obs, pick6_full), now=T0 + dt.timedelta(minutes=t), base=self.d)

    def rows(self, day="2026-11-17"):
        return lm.read(day, self.d)

    def test_the_open_is_kept_and_every_change_is_written_once(self):
        self.assertEqual(self.pull(0, dk_saves=[dk("Sergei Bobrovsky", 8475683, 25.5, -110, -110, 0)]), 1)
        self.assertEqual(self.pull(15, dk_saves=[dk("Sergei Bobrovsky", 8475683, 25.5, -110, -110, 15)]), 0)   # no change
        self.assertEqual(self.pull(30, dk_saves=[dk("Sergei Bobrovsky", 8475683, 25.5, -125, -105, 30)]), 1)   # price only
        self.assertEqual(self.pull(45, dk_saves=[dk("Sergei Bobrovsky", 8475683, 24.5, -110, -110, 45)]), 1)   # line
        self.assertEqual(self.pull(60, dk_saves=[dk("Sergei Bobrovsky", 8475683, 25.5, -110, -110, 60)]), 1)   # back to the open
        r = self.rows()
        self.assertEqual([(x["snap"], x["line"], x["over"], x["under"]) for x in r],
                         [(at(0), "25.5", "-110", "-110"), (at(30), "25.5", "-125", "-105"), (at(45), "24.5", "-110", "-110"),
                          (at(60), "25.5", "-110", "-110")])
        self.assertEqual({(x["market"], x["source"], x["player_id"], x["team"], x["teams"]) for x in r},
                         {("saves", "DraftKings", "8475683", "FLA", "TOR/FLA")})
        h = lm.for_page(["2026-11-17"], base=self.d)["2026-11-17|saves|8475683"]["DraftKings"]
        self.assertEqual(h[0][1:], [25.5, -110, -110])                                  # the open
        self.assertEqual([p[1] for p in h], [25.5, 25.5, 24.5, 25.5])
        self.assertEqual(h[0][0], int(T0.timestamp() // 60))

    def test_a_pull_read_twice_is_not_a_new_observation(self):
        s = dk("Sergei Bobrovsky", 8475683, 25.5, -110, -110, 30)
        self.pull(30, dk_saves=[s])
        # a fallback build reuses the last good pull with its ORIGINAL fetch time: even if handed in, nothing is written
        self.assertEqual(self.pull(45, dk_saves=[dict(s, over=-120)]), 0)
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(lm.observations(SLATE, at(0), dk_saves=None, books=None, pp=None, pick6=None), [])

    def test_main_line_when_a_source_lists_several(self):
        alts = [book("Auston Matthews", 8479318, 2.5, -115, -105, 0), book("Auston Matthews", 8479318, 1.5, -300, 220, 0),
                book("Auston Matthews", 8479318, 3.5, 200, -260, 0)]
        self.pull(0, books=alts)
        self.assertEqual([(x["source"], x["line"]) for x in self.rows()], [("ESPN BET", "2.5")])
        # an alternate's price moving is not a move of the main line
        alts2 = [dict(a, fetched_at=at(15)) for a in alts]
        alts2[2]["over"] = 210
        self.assertEqual(self.pull(15, books=alts2), 0)
        # the main line's own price moving is not a move for a skater's prop either (it is for saves)
        alts3 = [dict(a, fetched_at=at(30)) for a in alts]
        alts3[0]["over"], alts3[0]["under"] = -125, 105
        self.assertEqual(self.pull(30, books=alts3), 0)
        # Pick6's ladder: the line it takes both ways on; a reused (earlier pull) line and a promo card alone are not seen
        lad = [app("Auston Matthews", 8479318, 1.5, 0.6, 0.0, 0), app("Auston Matthews", 8479318, 2.5, 1.0, 0.9, 0),
               app("Auston Matthews", 8479318, 3.5, 1.9, 0.0, 0), app("Mitch Marner", 8478483, 2.5, 1.0, 1.0, 0, reused=True),
               app("Matthew Knies", 8482720, 1.5, 2.0, 2.0, 0, promo="Boost")]
        self.pull(0, pick6=lad)
        p6 = [(x["name"], x["line"], x["mo"], x["mu"]) for x in self.rows() if x["source"] == "Pick6"]
        self.assertEqual(p6, [("Auston Matthews", "2.5", "1", "0.9")])
        # PrizePicks: the standard line, never a demon or goblin
        pp = [app("Auston Matthews", 8479318, 3.5, 1.0, 1.0, 0), app("Auston Matthews", 8479318, 5.5, None, None, 0, alt=True, over=250)]
        self.pull(0, pp=pp)
        self.assertEqual([(x["line"], x["mo"]) for x in self.rows() if x["source"] == "PrizePicks"], [("3.5", "1")])

    def test_a_starter_swap_takes_the_first_goalies_line_off(self):
        self.pull(0, dk_saves=[dk("Sergei Bobrovsky", 8475683, 25.5, -110, -110, 0), dk("Joseph Woll", 8479361, 27.5, -115, -105, 0, team="TOR")])
        # DraftKings pulls Bobrovsky's line and posts the backup's: the game was pulled (Woll is there), so he is off
        self.pull(15, dk_saves=[dk("Spencer Knight", 8481519, 24.5, -110, -110, 15), dk("Joseph Woll", 8479361, 27.5, -115, -105, 15, team="TOR")])
        r = self.rows()
        off = [x for x in r if x["line"] == ""]
        self.assertEqual([(x["name"], x["snap"], x["team"], x["teams"]) for x in off], [("Sergei Bobrovsky", at(15), "FLA", "TOR/FLA")])
        # the next pull has nothing for that game (its request failed): nobody is taken off on that evidence
        self.pull(30, dk_saves=[dk("Jeremy Swayman", 8480280, 26.5, -110, -110, 30, team="BOS", teams=("BOS", "LAK"))])
        self.assertEqual(len([x for x in self.rows() if x["line"] == ""]), 1)
        h = lm.for_page(["2026-11-17"], base=self.d)
        self.assertEqual(h["2026-11-17|saves|8475683"]["DraftKings"][-1][1:], [None, None, None])
        self.assertEqual(len(h["2026-11-17|saves|8481519"]["DraftKings"]), 1)          # every goalie's saves line is sent

    def test_pick6_off_only_when_its_page_listed_the_market_in_full(self):
        self.pull(0, pick6=[app("Auston Matthews", 8479318, 2.5, 1.0, 0.9, 0), app("Mitch Marner", 8478483, 3.5, 1.0, 0.9, 0)])
        self.pull(15, pick6=[app("Auston Matthews", 8479318, 2.5, 1.0, 0.9, 15)])            # featured picks only
        self.assertFalse([x for x in self.rows() if x["line"] == ""])
        self.pull(30, pick6_full=("sog",), pick6=[app("Auston Matthews", 8479318, 2.5, 1.0, 0.9, 30)])   # the full category
        self.assertEqual([(x["name"], x["snap"]) for x in self.rows() if x["line"] == ""], [("Mitch Marner", at(30))])

    def test_a_blip_off_the_board_is_not_a_move(self):
        s = lambda t, line=25.5: dk("Sergei Bobrovsky", 8475683, line, -110, -110, t)
        w = lambda t: dk("Joseph Woll", 8479361, 27.5, -115, -105, t, team="TOR")
        self.pull(0, dk_saves=[s(0), w(0)])
        self.pull(15, dk_saves=[w(15)])                      # gone for one pull...
        self.pull(30, dk_saves=[s(30), w(30)])               # ...back unchanged 15 minutes later
        self.assertEqual(len(self.rows()), 4)                # the log keeps all of it
        h = lm.for_page(["2026-11-17"], base=self.d)["2026-11-17|saves|8475683"]["DraftKings"]
        self.assertEqual([p[1] for p in h], [25.5])          # the page sees one unbroken line
        self.pull(45, dk_saves=[w(45)])
        self.pull(90, dk_saves=[s(90), w(90)])               # off for 45 minutes: a real spell off the board
        h = lm.for_page(["2026-11-17"], base=self.d)["2026-11-17|saves|8475683"]["DraftKings"]
        self.assertEqual([p[1] for p in h], [25.5, None, 25.5])

    def test_page_sends_saves_always_and_other_props_only_when_the_line_moved(self):
        self.pull(0, dk_sog=[{**book("Auston Matthews", 8479318, 3.5, -115, -105, 0), "team": "TOR"},
                              {**book("Mitch Marner", 8478483, 2.5, -120, 100, 0), "team": "TOR"}],
                  pp=[app("Joseph Woll", 8479361, 26.5, 1.0, 1.0, 0, market="saves")],
                  dk_saves=[dk("Joseph Woll", 8479361, 26.5, -110, -110, 0, team="TOR")])
        self.pull(15, dk_sog=[{**book("Auston Matthews", 8479318, 4.5, 120, -150, 15), "team": "TOR"},
                               {**book("Mitch Marner", 8478483, 2.5, -135, 110, 15), "team": "TOR"}],   # Marner: price only
                  pp=[app("Joseph Woll", 8479361, 26.5, 1.0, 1.0, 15, market="saves")],
                  dk_saves=[dk("Joseph Woll", 8479361, 26.5, -125, 105, 15, team="TOR")])          # saves: price only
        h = lm.for_page(["2026-11-17"], base=self.d)
        self.assertEqual(sorted(h), ["2026-11-17|saves|8479361", "2026-11-17|sog|8479318"])
        self.assertEqual(h["2026-11-17|sog|8479318"]["DraftKings"][1][1:], [4.5, 120, -150])
        self.assertEqual(h["2026-11-17|saves|8479361"]["PrizePicks"][0][1:], [26.5, 1.0, 1.0])   # an app: multipliers
        self.assertEqual([p[2] for p in h["2026-11-17|saves|8479361"]["DraftKings"]], [-110, -125])   # every saves price
        self.assertEqual(len([r for r in self.rows() if r["name"] == "Mitch Marner"]), 1)      # a skater's price move: not a move
        self.assertEqual(len([r for r in self.rows() if r["name"] == "Joseph Woll" and r["source"] == "DraftKings"]), 2)   # saves: kept

    def test_rows_are_filed_by_game_day_and_unknown_players_by_name(self):
        self.pull(0, dk_saves=[dk("Sergei Bobrovsky", 8475683, 26.5, -110, -110, 0, day="2026-11-18")],
                  dk_sog=[{**book("Some Callup", None, 1.5, -110, -110, 0), "team": ""}])
        self.assertEqual([x["name"] for x in self.rows("2026-11-18")], ["Sergei Bobrovsky"])
        self.assertEqual([x["name"] for x in self.rows("2026-11-17")], ["Some Callup"])
        self.pull(15, dk_sog=[{**book("Some Callup", None, 2.5, -110, -110, 15), "team": ""}])
        self.assertIn("2026-11-17|sog|n:some callup", lm.for_page(["2026-11-17"], base=self.d))

    def test_csv_columns(self):
        self.pull(0, dk_saves=[dk("Sergei Bobrovsky", 8475683, 25.5, -110, -110, 0)])
        with open(lm.path("2026-11-17", self.d)) as f:
            self.assertEqual(next(csv.reader(f)), lm.COLS)


class Backfill(unittest.TestCase):
    """Days before the log: rebuilt from dk_prices.csv / book_prices.csv (DraftKings, and the books' saves lines)."""
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.keep = lm.PRICES, lm.BOOK_PRICES, lm.LEGS
        lm.PRICES, lm.BOOK_PRICES, lm.LEGS = (os.path.join(self.d, f) for f in ("dk.csv", "bk.csv", "legs.csv"))
        with open(lm.PRICES, "w") as f:
            f.write("market,date,name,team,teams,line,over,under,snap,start\n"
                    f"saves,2026-11-17,Sergei Bobrovsky,FLA,TOR/FLA,25.5,-110,-110,{at(0)},2026-11-18T00:00:00Z\n"
                    f"saves,2026-11-17,Sergei Bobrovsky,FLA,TOR/FLA,24.5,-105,-125,{at(30)},2026-11-18T00:00:00Z\n"
                    f"sog,2026-11-17,Auston Matthews,,TOR/FLA,3.5,-115,-105,{at(0)},2026-11-18T00:00:00Z\n")
        with open(lm.BOOK_PRICES, "w") as f:
            f.write("market,date,name,player_id,teams,book,line,over,under,snap,start\n"
                    f"saves,2026-11-17,Sergei Bobrovsky,8475683.0,TOR/FLA,FanDuel,24.5,-120,-110,{at(5)},2026-11-18T00:00:00Z\n"
                    f"sog,2026-11-17,Auston Matthews,8479318.0,TOR/FLA,ESPN BET,2.5,-200,150,{at(5)},2026-11-18T00:00:00Z\n"
                    f"sog,2026-11-17,Auston Matthews,8479318.0,TOR/FLA,ESPN BET,3.5,-115,-105,{at(5)},2026-11-18T00:00:00Z\n")
        with open(lm.LEGS, "w") as f:
            f.write("date,player_id,name,market\n2026-11-03,8479318,Auston Matthews,sog\n")
        self.base = os.path.join(self.d, "lines")

    def tearDown(self):
        lm.PRICES, lm.BOOK_PRICES, lm.LEGS = self.keep
        shutil.rmtree(self.d)

    def test_rebuilt_from_the_price_history(self):
        n = lm.backfill_day("2026-11-17", lm._price_history(), base=self.base)
        r = lm.read("2026-11-17", self.base)
        self.assertEqual(n, 4)
        got = [(x["source"], x["market"], x["player_id"], x["line"]) for x in r]
        self.assertEqual(got, [("DraftKings", "saves", "8475683", "25.5"), ("DraftKings", "sog", "8479318", "3.5"),
                               ("FanDuel", "saves", "8475683", "24.5"), ("DraftKings", "saves", "8475683", "24.5")])
        # the books' shots lines are not rebuilt (several lines at once: which one was the main line is not known)
        self.assertFalse([x for x in r if x["source"] == "ESPN BET"])
        self.assertEqual(lm.backfill_day("2026-11-17", lm._price_history(), base=self.base), 0)   # never overwritten

    def test_ensure_only_for_a_day_the_history_saw_before_this_pull(self):
        self.assertEqual(lm.ensure(["2026-11-17"], before=at(45), base=self.base), {"2026-11-17": 4})
        self.assertEqual(lm.ensure(["2026-11-17"], before=at(60), base=self.base), {})   # has a log now
        # a day whose only snapshots are from this very pull starts its log from the pull itself
        shutil.rmtree(self.base)
        self.assertEqual(lm.ensure(["2026-11-17"], before=at(0), base=self.base), {})
        self.assertEqual(lm.ensure(["2026-11-17"], now=T0 + dt.timedelta(seconds=30), base=self.base), {})   # no pull time: now
        # the live log then continues from the rebuilt rows without repeating them
        lm.ensure(["2026-11-17"], before=at(45), base=self.base)
        obs = lm.observations(SLATE, at(45), dk_saves=[dk("Sergei Bobrovsky", 8475683, 24.5, -105, -125, 45)])
        self.assertEqual(lm.record(obs, lm.covered(obs), now=T0 + dt.timedelta(minutes=45), base=self.base), 0)


if __name__ == "__main__":
    unittest.main()


MV_HARNESS = r"""
const fs = require("fs");
__PAGE__
const cases = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const out = {
  names: cases.names.map(mvName),
  keys: cases.keys.map(k => mvKeyOf(...k)),
  sums: cases.seqs.map(s => { const x = mvSum(s); return x && [x.open, x.now, x.off, x.d, x.lineMoves, x.changes, x.at]; }),
  inv: cases.inv.map(mvInvN),
  fair: cases.fair.map(([p, sd]) => mvFair(p, sd)),
  cons: cases.cons.map(([b, sd]) => mvConsensus(b, sd)),
  events: cases.events.map(b => mvEvents(b).map(e => [e.t, e.src, e.kind])),
};
process.stdout.write(JSON.stringify(out));
"""


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class PageMirror(unittest.TestCase):
    """The page's own movement helpers (cut out of template.html, run under node) against Python."""

    def run_page(self, cases):
        import json
        import subprocess
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(here, "template.html"), encoding="utf-8") as f:
            src = f.read()
        a = src.index("// ---------- line movement: pure helpers")
        b = src.index("// ---------- line movement: on the page")
        d = tempfile.mkdtemp()
        try:
            js, cf = os.path.join(d, "mv.js"), os.path.join(d, "cases.json")
            with open(js, "w") as f:
                f.write(MV_HARNESS.replace("__PAGE__", src[a:b]))
            with open(cf, "w") as f:
                json.dump(cases, f)
            r = subprocess.run(["node", js, cf], capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0, r.stderr)
            return json.loads(r.stdout)
        finally:
            shutil.rmtree(d)

    def test_page_matches_python(self):
        import statistics
        names = ["J.T. Miller", "Jean-Gabriel Pageau", "Ryan O'Reilly", "  Alex   Ovechkin ", "Pierre-Luc Dubois", "T.J. Oshie"]
        seqs = [[[100, 25.5, -110, -110]], [[100, 25.5, -110, -110], [130, 25.5, -125, 105], [160, 24.5, -110, -110]],
                [[100, 22.5, 100, -135], [115, 21.5, -135, 100], [130, 22.5, 100, -135]], [[100, 2.5, 1.0, 0.9], [160, None, None, None]],
                [[100, 3.5, -115, -105], [115, None, None, None], [200, 4.5, 120, -150]]]
        books = {"DraftKings": [[100, 22.5, 100, -135], [115, 21.5, -135, 100]], "FanDuel": [[105, 22.5, -110, -110]],
                 "ESPN BET": [[110, 23.5, -110, -120], [140, 22.5, -115, -115]], "PrizePicks": [[100, 22.5, 1.0, 1.0], [150, 21.5, 1.0, 1.0]]}
        cases = {"names": names, "keys": [["2026-11-17", "saves", 8475683, "x"], ["2026-11-17", "sog", None, "J.T. Miller"]],
                 "seqs": seqs, "inv": [1e-6, 0.01, 0.02425, 0.3, 0.5, 0.5345, 0.97, 0.999999],
                 "fair": [[[0, 22.5, 100, -135], 6.5], [[0, 21.5, -135, 100], 6.5], [[0, 25.5, -110, -110], 6.5],
                          [[0, 25.5, None, -110], 6.5], [[0, None, None, None], 6.5]],
                 "cons": [[books, 6.5], [{"PrizePicks": books["PrizePicks"]}, 6.5]], "events": [books]}
        out = self.run_page(cases)
        self.assertEqual(out["names"], [lm.norm_name(n) for n in names])                       # the log's name key
        self.assertEqual(out["keys"], ["2026-11-17|saves|8475683", "2026-11-17|sog|n:" + lm.norm_name("J.T. Miller")])
        # open, now, off, line move to the last posted line, line moves (off counts), changes of any kind, last change
        self.assertEqual(out["sums"], [
            [seqs[0][0], seqs[0][0], False, 0, 0, 0, 100],
            [seqs[1][0], seqs[1][2], False, -1, 1, 2, 160],
            [seqs[2][0], seqs[2][2], False, 0, 2, 2, 130],
            [seqs[3][0], seqs[3][1], True, 0, 1, 1, 160],
            [seqs[4][0], seqs[4][2], False, 1, 2, 2, 200]])
        for p, got in zip(cases["inv"], out["inv"]):
            self.assertAlmostEqual(got, statistics.NormalDist().inv_cdf(p), places=7)
        def fair(line, over, under, sd):
            imp = lambda o: 100 / (o + 100) if o > 0 else -o / (-o + 100)
            po, pu = imp(over), imp(under)
            return line + sd * statistics.NormalDist().inv_cdf(po / (po + pu))
        self.assertAlmostEqual(out["fair"][0], fair(22.5, 100, -135, 6.5), places=7)
        self.assertLess(abs(out["fair"][0] - out["fair"][1]), 0.15)                           # a flip is (almost) no move
        self.assertAlmostEqual(out["fair"][1], fair(21.5, -135, 100, 6.5), places=7)
        self.assertLess(abs(out["fair"][0] - 22.0), 0.1)
        self.assertAlmostEqual(out["fair"][2], 25.5, places=9)                                # even money: the line itself
        self.assertEqual(out["fair"][3:], [None, None])
        c = out["cons"][0]
        opens = [fair(22.5, 100, -135, 6.5), fair(22.5, -110, -110, 6.5), fair(23.5, -110, -120, 6.5)]
        nows = [fair(21.5, -135, 100, 6.5), fair(22.5, -110, -110, 6.5), fair(22.5, -115, -115, 6.5)]
        self.assertAlmostEqual(c["open"], sum(opens) / 3, places=7)                           # the books' mean (no apps)
        self.assertAlmostEqual(c["now"], sum(nows) / 3, places=7)
        self.assertAlmostEqual(c["d"], sum(b - a for a, b in zip(opens, nows)) / 3, places=7)   # their average move
        self.assertEqual(c["n"], 3)
        self.assertIsNone(out["cons"][1])                                                     # an app alone has no prices
        self.assertEqual(out["events"][0], [[100, "DraftKings", "open"], [100, "PrizePicks", "open"], [105, "FanDuel", "open"],
                                            [110, "ESPN BET", "open"], [115, "DraftKings", "line"], [140, "ESPN BET", "line"],
                                            [150, "PrizePicks", "line"]])


class OddsPulled(unittest.TestCase):
    """The other books and PrizePicks post the next day's lines overnight, before DraftKings. That pull falls back to
    the last good pull for the board (DraftKings had nothing), but its own rows are new and the line log takes them."""
    def setUp(self):
        import json
        import odds
        from tests.test_pick6 import NOW, R, SLATE
        self.odds, self.R, self.slate, self.now = odds, R, SLATE, NOW
        self.d = tempfile.mkdtemp()
        self.keep = odds.CACHE, odds._get, odds.fetch_moneylines, os.environ.get("ODDS_API_KEY")
        odds.CACHE = os.path.join(self.d, "odds.json")
        odds.fetch_moneylines = lambda key: []
        os.environ["ODDS_API_KEY"] = "test-key-not-real"
        with open(odds.CACHE, "w") as f:      # the last good pull, two hours old
            json.dump({"at": (NOW - dt.timedelta(hours=2)).isoformat(timespec="seconds"), "remaining": "1", "ml": [],
                       "sog": [], "points": [], "pp": [], "books": [],
                       "saves": [{"name": "Joseph Woll", "line": 27.5, "date": "2026-11-03", "teams": ["TOR", "FLA"], "source": "DK",
                                  "over": -110, "under": -110, "start": "2026-11-04T00:00:00Z"}]}, f)
        ev = {"id": "e1", "home_team": "Florida Panthers", "away_team": "Toronto Maple Leafs", "commence_time": "2026-11-04T00:00:00Z"}
        out = lambda side, price: {"name": side, "description": "Joseph Woll", "point": 26.5, "price": price}
        js = {"bookmakers": [{"key": "fanduel", "markets": [{"key": "player_total_saves", "outcomes": [out("Over", -120), out("Under", -110)]}]},
                             {"key": "prizepicks", "markets": [{"key": "player_total_saves", "outcomes": [out("Over", -137), out("Under", -137)]}]}]}
        odds._get = lambda url, params: [ev] if url.endswith("/events") else js

    def tearDown(self):
        o = self.odds
        o.CACHE, o._get, o.fetch_moneylines, key = self.keep
        if key is None:
            os.environ.pop("ODDS_API_KEY", None)
        else:
            os.environ["ODDS_API_KEY"] = key
        shutil.rmtree(self.d)

    def test_a_fallback_build_still_logs_its_own_new_rows(self):
        o = self.odds
        o.fetch([], self.now, self.R)
        self.assertEqual(o.status, "fallback")                              # DraftKings had nothing: the board reuses the cache
        self.assertEqual([r["line"] for r in o.book_rows], [])               # (the cache's books)
        at = self.now.isoformat(timespec="seconds")
        self.assertEqual(o.pulled["at"], at)
        self.assertEqual([(r["book"], r["line"], r["player_id"], r["fetched_at"]) for r in o.pulled["books"]],
                         [("FanDuel", 26.5, 8479361, at)])
        self.assertEqual([(r["line"], r["player_id"]) for r in o.pulled["pp"]], [(26.5, 8479361)])
        self.assertEqual(o.pulled["saves"], [])                              # nothing of the cached DraftKings line
        obs = lm.observations(self.slate, o.pulled["at"], dk_saves=o.pulled["saves"],
                              books=[r for r in o.pulled["books"] if r.get("match") == "MATCHED"],
                              pp=[r for r in o.pulled["pp"] if r.get("match") == "MATCHED"])
        self.assertEqual(sorted((x["source"], x["line"], x["mo"], x["mu"], x["snap"]) for x in obs),
                         [("FanDuel", 26.5, None, None, at), ("PrizePicks", 26.5, 1.0, 1.0, at)])
        base = os.path.join(self.d, "lines")
        self.assertEqual(lm.record(obs, lm.covered(obs), now=self.now, base=base), 2)

    def test_a_failed_pull_logs_nothing(self):
        o = self.odds
        o._get = lambda url, params: (_ for _ in ()).throw(OSError("HTTP 500"))
        o.fetch([], self.now, self.R)
        self.assertEqual(o.status, "fallback")
        self.assertEqual({k: v for k, v in o.pulled.items() if k != "at"}, {k: [] for k in ("saves", "sog", "points", "pp", "books")})
