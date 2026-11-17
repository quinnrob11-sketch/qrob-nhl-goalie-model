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
        self.pull(15, dk_sog=[{**book("Auston Matthews", 8479318, 4.5, -110, -110, 15), "team": "TOR"},
                               {**book("Mitch Marner", 8478483, 2.5, -135, 110, 15), "team": "TOR"}],   # Marner: price only
                  pp=[app("Joseph Woll", 8479361, 26.5, 1.0, 1.0, 15, market="saves")],
                  dk_saves=[dk("Joseph Woll", 8479361, 26.5, -125, 105, 15, team="TOR")])          # saves: price only
        h = lm.for_page(["2026-11-17"], base=self.d)
        self.assertEqual(sorted(h), ["2026-11-17|saves|8479361", "2026-11-17|sog|8479318"])
        self.assertEqual(h["2026-11-17|sog|8479318"]["DraftKings"][1][1:], [4.5, -110, -110])
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
  top: cases.top.map(([b, skip]) => { const x = mvTop(b, skip); return x && [x.src, x.s.d]; }),
  at: cases.at.map(([line, seq]) => mvAt(line, mvSum(seq))),
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
        ev = lambda t, line: [t, line, -110, -110] if line is not None else [t, None, None, None]   # even money: fair = line
        linked = [
            # ESPN BET alone at 27.5 drops to 24.5 in the very pull DraftKings and FanDuel open at 24.5: a 3-save move
            {"ESPN BET": [ev(0, 27.5), ev(10, 24.5)], "DraftKings": [ev(10, 24.5)], "FanDuel": [ev(10, 24.5)]},
            # FanDuel alone moves 25.5 -> 27.5, then three books open at 27.5 (A. Stolarz, 11-08): still the full 2
            {"FanDuel": [ev(0, 25.5), ev(20, 27.5)], "DraftKings": [ev(30, 27.5)], "ESPN BET": [ev(40, 27.5)], "Pinnacle": [ev(50, 27.5)]},
            # every book off, then back at a new line: a move
            {"DraftKings": [ev(0, 25.5), ev(10, None), ev(20, 27.5)], "FanDuel": [ev(0, 25.5), ev(10, None), ev(20, 27.5)]},
            # a spike that ends through off and back where it started: no move
            {"DraftKings": [ev(0, 25.5), ev(10, 27.5), ev(20, None), ev(30, 25.5)]},
            # a book off for good leaves the average
            {"DraftKings": [ev(0, 25.5), ev(10, None)], "FanDuel": [ev(0, 25.5), ev(20, 26.5)]},
        ]
        cases = {"names": names, "keys": [["2026-11-17", "saves", 8475683, "x"], ["2026-11-17", "sog", None, "J.T. Miller"]],
                 "seqs": seqs, "inv": [1e-6, 0.01, 0.02425, 0.3, 0.5, 0.5345, 0.97, 0.999999],
                 "fair": [[[0, 22.5, 100, -135], 6.5], [[0, 21.5, -135, 100], 6.5], [[0, 25.5, -110, -110], 6.5],
                          [[0, 25.5, None, -110], 6.5], [[0, None, None, None], 6.5]],
                 "cons": [[books, 6.5], [{"PrizePicks": books["PrizePicks"]}, 6.5]] + [[b, 6.5] for b in linked], "events": [books],
                 "top": [[books, None], [books, "PrizePicks"], [{"DraftKings": [ev(0, 25.5), ev(10, None)]}, None],
                         [books, ["DraftKings", None, "ESPN BET"]]],
                 "at": [[21.5, books["DraftKings"]], [22.5, books["DraftKings"]], [None, books["DraftKings"]],
                        [25.5, [ev(0, 25.5), ev(10, None)]], [21.5, books["PrizePicks"]]]}
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
        got = [(round(x["open"], 9), round(x["now"], 9), round(x["d"], 9), x["n"]) for x in out["cons"][2:]]
        self.assertEqual(got, [(27.5, 24.5, -3, 3), (25.5, 27.5, 2, 4), (25.5, 27.5, 2, 2), (25.5, 25.5, 0, 1), (25.5, 26.5, 1, 1)])
        # the biggest line move on the board now (named), skipping the row's own source; off the board is not a move here
        self.assertEqual(out["top"], [["DraftKings", -1], ["DraftKings", -1], None, ["PrizePicks", -1]])
        # a row's line is the source's latest posted line (not its open, not a line it has taken down)
        self.assertEqual(out["at"], [True, False, False, False, True])
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


class Robust(unittest.TestCase):
    """Pull times are compared as instants, never as text."""
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.d)

    def test_times_in_another_offset_still_order_right(self):
        s = dk("Sergei Bobrovsky", 8475683, 25.5, -110, -110, 0)
        lm.record(lm.observations(SLATE, at(0), dk_saves=[s]), now=T0, base=self.d)
        # 9:30 Central is 15:30 UTC: later, though "09:30" sorts before "15:00" as text
        later = dict(s, line=24.5, fetched_at="2026-11-17T09:30:00-06:00")
        self.assertEqual(lm.record(lm.observations(SLATE, None, dk_saves=[later]), now=T0 + dt.timedelta(minutes=30), base=self.d), 1)
        earlier = dict(s, line=26.5, fetched_at="2026-11-17T08:45:00-06:00")            # 14:45 UTC: older than the open
        self.assertEqual(lm.record(lm.observations(SLATE, None, dk_saves=[earlier]), now=T0 + dt.timedelta(minutes=45), base=self.d), 0)
        h = lm.for_page(["2026-11-17"], base=self.d)["2026-11-17|saves|8475683"]["DraftKings"]
        self.assertEqual([(p[0] - h[0][0], p[1]) for p in h], [(0, 25.5), (30, 24.5)])

    def test_a_row_without_a_pull_time_takes_the_builds(self):
        s = {k: v for k, v in dk("Sergei Bobrovsky", 8475683, 25.5, -110, -110, 0).items() if k != "fetched_at"}
        lm.record(lm.observations(SLATE, None, dk_saves=[s]), now=T0 + dt.timedelta(minutes=5), base=self.d)
        self.assertEqual([r["snap"] for r in lm.read("2026-11-17", self.d)], [at(5)])


class Rungs(unittest.TestCase):
    """A sportsbook moving a skater's main line between rungs of an all but unchanged market is not a line move."""
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.d)

    def test_implied_count(self):
        import math
        self.assertAlmostEqual(lm.implied_mean(0.5, -110, -110), math.log(2), places=6)    # P(X >= 1) = 1/2
        self.assertIsNone(lm.implied_mean(0.5, None, -110))
        # ESPN BET's two rungs of one points market: about the same count (1.10 and 1.19)
        a, b = lm.implied_mean(0.5, -250, 180), lm.implied_mean(1.5, 180, -250)
        self.assertLess(abs(a - b) / max(a, b), lm.RUNG_TOL)

    def test_page_leaves_out_a_book_that_only_changed_rungs(self):
        def pull(t, line, over, under, book_="ESPN BET", pid=8477404, market="points", teams=("TOR", "FLA")):
            obs = lm.observations(SLATE, at(t), books=[book("Nick Paul", pid, line, over, under, t, book_=book_, market=market, teams=teams)])
            lm.record(obs, lm.covered(obs), now=T0 + dt.timedelta(minutes=t), base=self.d)
        # ESPN BET flipping rungs: 0.5 at -250, 1.5 at +180, 0.5 at -260, 1.5 at +175
        for t, line, o, u in ((0, 0.5, -250, 180), (15, 1.5, 180, -250), (30, 0.5, -260, 190), (45, 1.5, 175, -240)):
            pull(t, line, o, u)
        # DraftKings' threshold move: 1.5 at -185 to 2.5 at +145 (the count goes 2.04 -> 2.22)
        pull(0, 1.5, -185, 135, book_="DraftKings", pid=8478402, market="sog")
        pull(15, 2.5, 145, -195, book_="DraftKings", pid=8478402, market="sog")
        # a real move: 2.5 even to 1.5 even (2.67 -> 1.68)
        pull(0, 2.5, -110, -110, book_="FanDuel", pid=8478403, market="sog")
        pull(15, 1.5, -110, -110, book_="FanDuel", pid=8478403, market="sog")
        # taken down: always news
        pull(0, 3.5, -110, -110, book_="BetMGM", pid=8478404, market="sog")
        obs = lm.observations(SLATE, at(30), books=[book("Other Player", 8478405, 1.5, -110, -110, 30, book_="BetMGM", market="sog")])
        lm.record(obs, lm.covered(obs), now=T0 + dt.timedelta(minutes=30), base=self.d)
        # the other game: DraftKings flip-flopping around a price threshold all evening (G. Vilardi, 11-05), the count
        # 2.37 / 2.07 (12.5%)
        bl_ = ("BOS", "LAK")
        for t, line, o, u in ((0, 2.5, 120, -165), (60, 1.5, -195, 145), (120, 2.5, 145, -195), (150, 1.5, -195, 140)):
            pull(t, line, o, u, book_="DraftKings", pid=8480014, market="sog", teams=bl_)
        # ... and taken down for 30 minutes, back at the same line (A. Wennberg, 11-09): news, even back where it opened
        pull(0, 1.5, -155, 120, book_="ESPN BET", pid=8477505, market="sog", teams=bl_)
        obs = lm.observations(SLATE, at(15), books=[book("Other Player", 8478406, 1.5, -110, -110, 15, book_="ESPN BET", market="sog", teams=bl_)])
        lm.record(obs, lm.covered(obs), now=T0 + dt.timedelta(minutes=15), base=self.d)
        obs = lm.observations(SLATE, at(45), books=[book("Nick Paul", 8477505, 1.5, 140, -190, 45, book_="ESPN BET", market="sog", teams=bl_),
                                                    book("Other Player", 8478406, 1.5, -110, -110, 45, book_="ESPN BET", market="sog", teams=bl_)])
        lm.record(obs, lm.covered(obs), now=T0 + dt.timedelta(minutes=45), base=self.d)
        h = lm.for_page(["2026-11-17"], base=self.d)
        self.assertEqual(sorted((k, sorted(v)) for k, v in h.items()),
                         [("2026-11-17|sog|8477505", ["ESPN BET"]), ("2026-11-17|sog|8478403", ["FanDuel"]),
                          ("2026-11-17|sog|8478404", ["BetMGM"])])
        self.assertEqual(len([r for r in lm.read("2026-11-17", self.d) if r["player_id"] == "8477404"]), 4)   # the log keeps them all


class Merge(unittest.TestCase):
    """backfill_lines: the replayed pulls folded into a day the builds already logged."""
    def test_merge_keeps_each_change_once(self):
        row = lambda t, line, src="DraftKings", over=-110: {"snap": at(t), "market": "saves", "source": src, "player_id": "8475683",
                                                            "name": "Sergei Bobrovsky", "team": "FLA", "teams": "TOR/FLA",
                                                            "line": "" if line is None else str(line), "over": "" if line is None else str(over),
                                                            "under": "" if line is None else "-110", "mo": "", "mu": ""}
        replay = [row(0, 25.5), row(30, 24.5), row(45, 25.5)]               # the pulls in git history, from the open
        live = [row(45, 25.5, over=-110), row(60, 25.5, over=-120)]          # the first build after go-live started at 45
        out = lm.merge(live, replay)
        self.assertEqual([(r["snap"], r["line"], r["over"]) for r in out],
                         [(at(0), "25.5", "-110"), (at(30), "24.5", "-110"), (at(45), "25.5", "-110"), (at(60), "25.5", "-120")])
        self.assertEqual(lm.merge([row(0, None)], [row(5, 25.5)])[0]["snap"], at(5))   # never opens off the board
        d = tempfile.mkdtemp()
        try:
            lm.write("2026-11-17", out, base=d)
            self.assertEqual([(r["snap"], r["line"]) for r in lm.read("2026-11-17", d)], [(r["snap"], r["line"]) for r in out])
            self.assertEqual(lm.merge(lm.read("2026-11-17", d), replay), lm.merge(out))   # merging again changes nothing
        finally:
            shutil.rmtree(d)


class BackfillLines(unittest.TestCase):
    def test_combine_adds_only_what_came_before_a_props_first_logged_row(self):
        import backfill_lines as bl
        row = lambda t, line, src="FanDuel": {"snap": at(t), "market": "saves", "source": src, "player_id": "8479361",
                                             "name": "Joseph Woll", "team": "TOR", "teams": "TOR/FLA", "line": str(line),
                                             "over": "-110", "under": "-110", "mo": "", "mu": ""}
        # the builds logged him from 22:00 (26.5): a fallback build at 22:45 saw 26.5 again, which writes no row
        live = [row(0, 26.5)]
        # the replay has a pull at 22:30 (25.5) that the builds failed to log, and his open at 21:00 (27.5)
        replay = [row(-60, 27.5), row(0, 26.5), row(30, 25.5)]
        out = bl.combine(live, replay)
        self.assertEqual([(r["snap"], r["line"]) for r in out], [(at(-60), "27.5"), (at(0), "26.5")])   # never ends on 25.5
        # a prop the builds never logged comes from the replay whole
        other = [row(-60, 30.5, src="DraftKings"), row(30, 29.5, src="DraftKings")]
        self.assertEqual(len(bl.combine(live, replay + other)), 4)
        self.assertEqual(bl.combine(out, replay), out)                                       # run again: nothing new

    def test_pick6_full_markets_from_the_built_page(self):
        import backfill_lines as bl
        page = 'const D = {"x":1,"pick6_stats":{"raw":9,"dropped":{},"full":["sog"],"category_name":"Shots On Goal"},"y":[1]};'
        self.assertEqual(bl.pick6_full_of(page), ["sog"])
        self.assertEqual(bl.pick6_full_of('const D = {"pick6_stats":{"raw":9}};'), [])
        self.assertEqual(bl.pick6_full_of("<html></html>"), [])

    def test_replay_takes_pick6_off_only_after_a_full_page(self):
        import backfill_lines as bl
        d = tempfile.mkdtemp()
        try:
            odds_ = {"saves": [], "sog": [{"name": "Auston Matthews", "player_id": 8479318, "team": "TOR", "teams": ["TOR", "FLA"],
                                          "date": "2026-11-17", "line": 3.5, "over": -115, "under": -105, "match": "MATCHED"}]}
            p6 = lambda *names: {"rows": [{"name": n, "player_id": pid, "team": "TOR", "date": "2026-11-17", "market": "sog",
                                          "line": 2.5, "mo": 1.0, "mu": 0.9} for n, pid in names]}
            mm, am = ("Mitch Marner", 8478483), ("Auston Matthews", 8479318)
            items = [(at(0), "odds", odds_), (at(1), "pick6", p6(mm, am), ["sog"]),
                     (at(15), "pick6", p6(am), []),             # featured picks only: proves nothing
                     (at(30), "pick6", p6(am), ["sog"])]        # the full shots page without Marner: off
            bl.replay(items, d)
            off = [(r["name"], r["snap"]) for r in lm.read("2026-11-17", d) if r["source"] == "Pick6" and r["line"] == ""]
            self.assertEqual(off, [("Mitch Marner", at(30))])
        finally:
            shutil.rmtree(d)

    @unittest.skipUnless(shutil.which("git"), "git is not installed")
    def test_a_shallow_clone_is_refused(self):
        import subprocess
        import backfill_lines as bl
        d = tempfile.mkdtemp()
        g = lambda cwd, *a: subprocess.run(["git", "-c", "user.email=t@example.com", "-c", "user.name=t", *a], cwd=cwd,
                                           check=True, capture_output=True, text=True)
        try:
            src = os.path.join(d, "src")
            os.makedirs(os.path.join(src, "model", "data"))
            g(src, "init", "-q")
            for i in range(3):
                with open(os.path.join(src, "model", "data", "odds_cache.json"), "w") as f:
                    f.write('{"at": "%s"}' % at(15 * i))
                g(src, "add", "-A")
                g(src, "commit", "-q", "-m", f"pull {i}")
            g(d, "clone", "-q", "--depth", "1", "file://" + src, "shallow")
            g(d, "clone", "-q", "file://" + src, "full")
            keep = bl.ROOT
            try:
                bl.ROOT = os.path.join(d, "shallow")
                self.assertIsNotNone(bl._cut("HEAD"))
                bl.ROOT = os.path.join(d, "full")
                self.assertIsNone(bl._cut("HEAD"))
                self.assertEqual([x[0] for x in bl.pulls("HEAD")], [at(0), at(15), at(30)])
            finally:
                bl.ROOT = keep
        finally:
            shutil.rmtree(d)


class RecordLines(unittest.TestCase):
    """The build's step (build_site.record_lines): what it logs from this build's pulls."""
    def setUp(self):
        import build_site, odds, pick6, prizepicks
        self.bs, self.odds, self.pick6, self.pp = build_site, odds, pick6, prizepicks
        self.d = tempfile.mkdtemp()
        self.keep = (lm.DIR, odds.pulled, prizepicks.last_js, prizepicks.props_status, pick6.fetch_status, lm.ensure,
                     lm.PRICES, lm.BOOK_PRICES, lm.LEGS)
        lm.DIR = self.d
        lm.PRICES, lm.BOOK_PRICES, lm.LEGS = (os.path.join(self.d, "none", f) for f in ("dk.csv", "bk.csv", "legs.csv"))
        pp_saves = {"name": "Joseph Woll", "player_id": 8479361, "team": "TOR", "teams": ["TOR", "FLA"], "date": "2026-11-17",
                    "market": "saves", "line": 26.5, "over": -137, "under": -137, "match": "MATCHED", "fetched_at": at(0)}
        odds.pulled = {"at": at(0), "saves": [dk("Joseph Woll", 8479361, 26.5, -110, -110, 0, team="TOR")], "sog": [], "points": [],
                       "pp": [pp_saves], "books": []}
        pick6.fetch_status = "error"

    def tearDown(self):
        (lm.DIR, self.odds.pulled, self.pp.last_js, self.pp.props_status, self.pick6.fetch_status, lm.ensure,
         lm.PRICES, lm.BOOK_PRICES, lm.LEGS) = self.keep
        shutil.rmtree(self.d)

    def test_prizepicks_saves_are_logged_when_its_own_feed_answers(self):
        self.pp.last_js, self.pp.props_status = {"data": []}, "fresh"       # PrizePicks let the build in: shots and points only
        own = [{"name": "Auston Matthews", "player_id": 8479318, "team": "TOR", "game": 2026020340, "date": "2026-11-17",
                "market": "sog", "line": 3.5, "mo": 1.0, "mu": 1.0, "fetched_at": at(0)}]
        self.bs.record_lines(own, [], {}, SLATE, now=T0)
        got = sorted((r["source"], r["market"], r["line"]) for r in lm.read("2026-11-17"))
        self.assertEqual(got, [("DraftKings", "saves", "26.5"), ("PrizePicks", "saves", "26.5"), ("PrizePicks", "sog", "3.5")])

    def test_a_failed_rebuild_never_stops_the_log(self):
        self.pp.last_js, self.pp.props_status = None, "fresh"
        seen = []
        def boom(days, **kw):
            seen.append(list(days))
            raise ValueError("bad price log")
        lm.ensure = boom
        moves = self.bs.record_lines([], [], {}, SLATE, now=T0)
        self.assertEqual(seen, [["2026-11-17"]])                              # only the days this pull has lines for
        self.assertEqual(len(lm.read("2026-11-17")), 2)
        self.assertIn("2026-11-17|saves|8479361", moves)


if __name__ == "__main__":
    unittest.main()
