"""Market-line freshness: every build pulls fresh, the cache is only a labelled fallback, real fetch times
survive caching and board building, lines older than 20 minutes are flagged, every build publishes, and
the calls themselves are unchanged."""
import copy
import datetime as dt
import json
import os
import shutil
import subprocess
import tempfile
import unittest

import odds
import pick6
import props_board as pb
import sources
from tests.test_board import PLAYERS, p6, payload

NOW = dt.datetime(2026, 11, 5, 17, 0, tzinfo=dt.timezone.utc)
ISO = lambda t: t.isoformat(timespec="seconds")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DK_ROW = {"name": "M. Marner", "line": 2.5, "date": "2026-11-03", "teams": ["FLA", "TOR"], "source": "DK",
          "over": -120, "under": 100, "start": "2099-01-01T00:00:00Z", "player_id": 10, "team": "TOR"}


class Tmp(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self._odds, self._p6 = odds.CACHE, pick6.CACHE
        odds.CACHE, pick6.CACHE = os.path.join(self.d, "odds.json"), os.path.join(self.d, "p6.json")
        self._of, self._pp = odds._fetch, pick6._pull

    def tearDown(self):
        odds.CACHE, pick6.CACHE, odds._fetch, pick6._pull = self._odds, self._p6, self._of, self._pp
        shutil.rmtree(self.d)

    def cache(self, at, sog):
        json.dump({"at": ISO(at), "remaining": "1", "ml": [], "sog": sog, "points": [], "saves": []}, open(odds.CACHE, "w"))

    def fake_dk(self, sog=None, err=None):
        calls = []
        def f(goalies, now=None, R=None):
            calls.append(now)
            odds.sog_rows, odds.points_rows, odds.ml_rows, odds._raw_saves = [dict(r) for r in (sog or [])], [], [], []
            odds.last_error = err
            return []
        odds._fetch = f
        return calls


class DraftKings(Tmp):
    def test_a_young_cache_is_not_reused_when_the_pull_works(self):
        self.cache(NOW - dt.timedelta(minutes=5), [{**DK_ROW, "line": 9.5}])     # the old 55-minute rule reused this
        calls = self.fake_dk(sog=[DK_ROW])
        odds.fetch([], NOW)
        self.assertEqual(len(calls), 1)
        self.assertEqual((odds.status, odds.fetched_at), ("fresh", ISO(NOW)))
        self.assertEqual([r["line"] for r in odds.sog_rows], [2.5])
        self.assertTrue(all(r["fetched_at"] == ISO(NOW) for r in odds.sog_rows))
        self.assertEqual(json.load(open(odds.CACHE))["at"], ISO(NOW))             # becomes the new last good pull

    def test_failed_pull_falls_back_with_the_original_fetch_time(self):
        old = NOW - dt.timedelta(minutes=46)
        self.cache(old, [{**DK_ROW, "fetched_at": ISO(old)}, {**DK_ROW, "line": 3.5}])
        self.fake_dk(err="HTTP 429")
        odds.fetch([], NOW)
        self.assertEqual(odds.status, "fallback")
        self.assertEqual(odds.fetched_at, ISO(old))
        self.assertEqual({r["fetched_at"] for r in odds.sog_rows}, {ISO(old)})    # never the build time
        self.assertEqual(odds.last_error, "HTTP 429")
        inf = sources.info(odds.status, odds.fetched_at, NOW, odds.last_error)
        self.assertEqual((inf["status"], inf["age_min"], inf["stale"]), ("fallback", 46.0, True))

    def test_failed_pull_and_no_cache_is_an_error(self):
        self.fake_dk(err="ODDS_API_KEY not set")
        self.assertEqual(odds.fetch([], NOW), [])
        self.assertEqual((odds.status, odds.fetched_at), ("error", None))
        self.assertTrue(sources.info(odds.status, None, NOW, odds.last_error)["stale"])


class Pick6(Tmp):
    def test_fresh_pull_is_cached_and_failure_falls_back_labelled(self):
        at = ISO(NOW - dt.timedelta(minutes=30))
        row = {**p6(10, "Mitch Marner", "TOR", 2.5), "fetched_at": at}
        pick6._pull = lambda slate, R, timeout=30: ([row], {"raw": 1, "kept": 1, "dropped": {}})
        rows, _ = pick6.fetch([{"id": 1}], None)
        self.assertEqual((pick6.fetch_status, pick6.fetched_at), ("fresh", at))
        def blocked(slate, R, timeout=30):
            pick6.status = "blocked (HTTP 403)"
            return [], {}
        pick6._pull = blocked
        rows, st = pick6.fetch([{"id": 1}], None)
        self.assertEqual((pick6.fetch_status, pick6.fetched_at), ("fallback", at))
        self.assertEqual([r["fetched_at"] for r in rows], [at])
        self.assertEqual(pick6.status, "blocked (HTTP 403)")                    # the existing banner text is kept
        self.assertEqual(st["fallback_rows"], 1)
        os.remove(pick6.CACHE)
        rows, _ = pick6.fetch([{"id": 1}], None)
        self.assertEqual((rows, pick6.fetch_status), ([], "error"))


class Board(unittest.TestCase):
    def board(self, p6_at, dk_at, src=None):
        pl = payload(PLAYERS, [{**DK_ROW, "name": "W. Nylander", "player_id": 11, "fetched_at": dk_at}])
        pl["built_iso"] = ISO(NOW)
        pl["sources_at"] = ISO(NOW)
        pl["sources"] = src or {}
        rows = [{**p6(10, "Mitch Marner", "TOR", 2.5), "fetched_at": p6_at}, {**p6(20, "Sam Reinhart", "FLA", 1.5), "fetched_at": p6_at}]
        return pb.build(pl, rows, NOW - dt.timedelta(hours=1))

    def test_fetch_times_survive_and_old_lines_are_flagged(self):
        fresh, old = ISO(NOW - dt.timedelta(minutes=3)), ISO(NOW - dt.timedelta(minutes=46))
        b = self.board(fresh, old, {"dk": {"status": "fallback"}, "pick6": {"status": "fresh"}})
        by = {r["source"]: r for r in b["rows"]}
        self.assertEqual(by["DraftKings"]["fetched_at"], old)                    # not the build time
        self.assertTrue(by["DraftKings"]["stale"]); self.assertTrue(by["DraftKings"]["fallback"])
        self.assertEqual(by["DraftKings"]["age_min"], 46.0)
        self.assertFalse(by["Pick6"]["stale"]); self.assertFalse(by["Pick6"]["fallback"])
        self.assertEqual({r["fetched_at"] for r in b["rows"] if r["source"] == "Pick6"}, {fresh})
        self.assertTrue(all("stale" in p for p in b["plays"]))
        edge = ISO(NOW - dt.timedelta(minutes=20))                                 # exactly 20 min is not stale
        self.assertFalse(self.board(edge, edge)["rows"][0]["stale"])
        self.assertTrue(sources.info("fresh", ISO(NOW - dt.timedelta(minutes=21)), NOW)["stale"])
        self.assertFalse(sources.info("fresh", edge, NOW)["stale"])

    def test_calls_identical_for_identical_lines_whatever_their_age(self):
        a = self.board(ISO(NOW), ISO(NOW))
        b = self.board(ISO(NOW - dt.timedelta(hours=3)), ISO(NOW - dt.timedelta(hours=3)), {"dk": {"status": "fallback"}})
        strip = lambda rows: [{k: v for k, v in r.items() if k not in ("fetched_at", "age_min", "stale", "fallback")} for r in rows]
        self.assertEqual(strip(a["rows"]), strip(b["rows"]))
        self.assertEqual(a["counts"], b["counts"])
        self.assertEqual(strip(a["plays"]), strip(b["plays"]))


class Publish(unittest.TestCase):
    def git(self, *a):
        return subprocess.run(["git", *a], cwd=self.d, check=True, capture_output=True, text=True).stdout.strip()

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.git("init", "-q"); self.git("config", "user.email", "t@t"); self.git("config", "user.name", "t")
        os.makedirs(os.path.join(self.d, "model"))
        shutil.copy(os.path.join(HERE, "publish.sh"), os.path.join(self.d, "model", "publish.sh"))
        open(os.path.join(self.d, "index.html"), "w").write('<script>const D = {"built":"17:00","sources":{"dk":{"fetched_at":"17:00"}}}</script>')
        self.git("add", "-A"); self.git("commit", "-qm", "init")

    def tearDown(self):
        shutil.rmtree(self.d)

    def publish(self):
        env = {**os.environ, "PUBLISH_NO_PUSH": "1"}
        return subprocess.run(["bash", "model/publish.sh"], cwd=self.d, env=env, capture_output=True, text=True)

    def test_timestamp_only_change_commits(self):
        open(os.path.join(self.d, "index.html"), "w").write('<script>const D = {"built":"17:15","sources":{"dk":{"fetched_at":"17:15"}}}</script>')
        r = self.publish()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.git("rev-list", "--count", "HEAD"), "2")
        self.assertIn("17:15", self.git("show", "HEAD:index.html"))
        self.assertTrue(self.git("log", "-1", "--format=%s").startswith("auto: rebuild"))

    def test_identical_build_still_commits(self):
        self.assertEqual(self.publish().returncode, 0)
        self.assertEqual(self.git("rev-list", "--count", "HEAD"), "2")


if __name__ == "__main__":
    unittest.main()
