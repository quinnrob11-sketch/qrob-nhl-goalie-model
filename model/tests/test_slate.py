"""Item 7: today's slate (America/Chicago) stays up until all of today's games are FINAL."""
import datetime as dt
import unittest

import slate

UTC = dt.timezone.utc


def g(gid, start, state, date="2026-11-03"):
    return {"id": gid, "date": date, "start": start, "state": state, "home": "DAL", "away": "SEA"}


# Nov 3 2026 (CST, UTC-6): 7:00 PM CT = 01:00Z Nov 4, 9:10 PM CT = 03:10Z Nov 4
EARLY = "2026-11-04T01:00:00Z"
LATE = "2026-11-04T03:10:00Z"
TOMORROW = "2026-11-05T00:00:00Z"


class SlateDay(unittest.TestCase):
    def test_late_game_still_shows_at_1130pm_ct(self):
        now = dt.datetime(2026, 11, 4, 5, 30, tzinfo=UTC)          # 11:30 PM CT Nov 3
        self.assertEqual(slate.ct_today(now).isoformat(), "2026-11-03")
        games = [g(1, EARLY, "OFF"), g(2, LATE, "LIVE"), g(3, TOMORROW, "FUT", "2026-11-04")]
        self.assertEqual(slate.slate_day(games, now), "2026-11-03")

    def test_moves_on_when_all_final(self):
        now = dt.datetime(2026, 11, 4, 5, 30, tzinfo=UTC)
        games = [g(1, EARLY, "OFF"), g(2, LATE, "FINAL"), g(3, TOMORROW, "FUT", "2026-11-04")]
        self.assertEqual(slate.slate_day(games, now), "2026-11-04")

    def test_utc_midnight_is_not_a_new_day(self):
        # 6:30 PM CT = 00:30Z next day: a UTC clock would already say Nov 4
        now = dt.datetime(2026, 11, 4, 0, 30, tzinfo=UTC)
        games = [g(1, EARLY, "FUT"), g(2, LATE, "FUT"), g(3, TOMORROW, "FUT", "2026-11-04")]
        self.assertEqual(slate.slate_day(games, now), "2026-11-03")

    def test_game_past_midnight_ct(self):
        now = dt.datetime(2026, 11, 4, 6, 20, tzinfo=UTC)          # 12:20 AM CT Nov 4, OT still going
        games = [g(2, LATE, "LIVE"), g(3, TOMORROW, "FUT", "2026-11-04")]
        self.assertEqual(slate.slate_day(games, now), "2026-11-03")

    def test_started(self):
        now = dt.datetime(2026, 11, 4, 2, 0, tzinfo=UTC)
        self.assertTrue(slate.started(g(1, EARLY, "LIVE"), now))
        self.assertFalse(slate.started(g(2, LATE, "FUT"), now))
        self.assertTrue(slate.started({"start": EARLY}, now))      # no state: by start time


class LegStatus(unittest.TestCase):
    def test_over_decided_early(self):
        self.assertEqual(slate.leg_status("sog", "OVER", 2.5, 3, "LIVE"), "HIT")
        self.assertEqual(slate.leg_status("sog", "UNDER", 2.5, 3, "LIVE"), "MISS")
        self.assertEqual(slate.leg_status("sog", "UNDER", 2.5, 2, "LIVE"), "LIVE")
        self.assertEqual(slate.leg_status("sog", "UNDER", 2.5, 2, "FINAL"), "HIT")
        self.assertEqual(slate.leg_status("sog", "OVER", 2.5, 2, "OFF"), "MISS")
        self.assertEqual(slate.leg_status("saves", "OVER", 25.0, 25, "OFF"), "PUSH")
        self.assertEqual(slate.leg_status("sog", "OVER", 2.5, None, "FUT"), "")

    def test_parse_box(self):
        js = {"playerByGameStats": {"awayTeam": {"forwards": [{"playerId": 8478402, "sog": 4, "points": 2}],
                                                  "goalies": [{"playerId": 8476945, "saves": 31}]},
                                     "homeTeam": {"defense": [{"playerId": 8480800, "sog": 1, "goals": 0, "assists": 1}]}}}
        b = slate.parse_box(js)
        self.assertEqual(b[8478402], {"sog": 4, "points": 2, "saves": None})
        self.assertEqual(b[8476945]["saves"], 31)
        self.assertEqual(b[8480800]["points"], 1)


if __name__ == "__main__":
    unittest.main()
