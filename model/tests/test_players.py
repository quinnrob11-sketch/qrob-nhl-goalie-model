"""Item 1: (name, team, game) -> NHL playerId, never on name alone."""
import unittest

import players


def _api(fwd=(), dmen=(), goalies=()):
    mk = lambda pid, first, last: {"id": pid, "firstName": {"default": first}, "lastName": {"default": last}}
    return {"forwards": [mk(*p) for p in fwd], "defensemen": [mk(*p) for p in dmen], "goalies": [mk(*p) for p in goalies]}


# shaped like api-web.nhle.com/v1/roster/{team}/current (teams as of Nov 2026)
ROSTERS = players.Rosters({
    "UTA": players.parse_roster(_api(fwd=[(8475314, "Anders", "Lee"), (8478831, "Kevin", "Stenlund")])),
    "LAK": players.parse_roster(_api(fwd=[(8481732, "Andre", "Lee")])),
    "OTT": players.parse_roster(_api(fwd=[(8482116, "Tim", "Stützle")])),
    "VAN": players.parse_roster(_api(fwd=[(8480012, "Elias", "Pettersson")], dmen=[(8483678, "Elias", "Pettersson")])),
    "WSH": players.parse_roster(_api(fwd=[(8479385, "Jordan", "Kyrou")], dmen=[(8484873, "Cole", "Hutson")])),
    "MTL": players.parse_roster(_api(dmen=[(8483457, "Lane", "Hutson")])),
    "MIN": players.parse_roster(_api(dmen=[(8480800, "Quinn", "Hughes")])),
    "NJD": players.parse_roster(_api(fwd=[(8481559, "Jack", "Hughes")], dmen=[(8482684, "Luke", "Hughes")])),
    "NSH": players.parse_roster(_api(fwd=[(8484241, "Matthew", "Wood")])),
    "NYI": players.parse_roster(_api(fwd=[(8477500, "Bo", "Horvat")])),
    "BOS": players.parse_roster(_api(fwd=[(8482175, "JJ", "Peterka")])),
    "FLA": players.parse_roster(_api(fwd=[(8479314, "Matthew", "Tkachuk"), (8480801, "Brady", "Tkachuk")])),
    "TOR": players.parse_roster(_api(fwd=[(8478483, "Mitchell", "Marner")])),
    "NYR": players.parse_roster(_api(dmen=[(8476885, "Jacob", "Trouba")])),
})


def pid(name, team=None, game=None, pos=None):
    return ROSTERS.match(name, team, game, pos)["player_id"]


class TestMatching(unittest.TestCase):
    def test_lee_by_team(self):
        self.assertEqual(pid("A. Lee", "UTA"), 8475314)
        self.assertEqual(pid("Anders Lee", "UTA"), 8475314)
        self.assertEqual(pid("A. Lee", "LAK"), 8481732)
        # the right last name on the wrong team never crosses over
        self.assertIsNone(pid("Andre Lee", "UTA"))
        self.assertIsNone(pid("Anders Lee", "LAK"))

    def test_accents_and_transliteration(self):
        for n in ("Stuetzle", "Stützle", "Stutzle", "Tim Stuetzle", "T. Stützle", "TIM STUTZLE"):
            self.assertEqual(pid(n, "OTT"), 8482116, n)

    def test_two_elias_pettersson(self):
        a, b = ROSTERS.match("E. Pettersson", "VAN"), ROSTERS.match("Elias Pettersson", "VAN")
        self.assertEqual(a["status"], "UNMATCHED")       # both are named Elias Pettersson
        self.assertEqual(b["status"], "UNMATCHED")
        self.assertIn("2 VAN players", a["reason"])
        # a position on the board resolves both
        self.assertEqual(pid("E. Pettersson", "VAN", pos="C"), 8480012)
        self.assertEqual(pid("E. Pettersson", "VAN", pos="D"), 8483678)

    def test_live_teams(self):
        self.assertEqual(pid("Jordan Kyrou", "WSH"), 8479385)
        self.assertEqual(pid("L. Hutson", "MTL"), 8483457)
        self.assertEqual(pid("Cole Hutson", "WSH"), 8484873)
        self.assertEqual(pid("Q. Hughes", "MIN"), 8480800)
        self.assertEqual(pid("M. Wood", "NSH"), 8484241)
        self.assertIsNone(pid("Q. Hughes", "VAN"))       # old team: unmatched, not guessed
        self.assertIsNone(pid("Hughes", "NJD"))          # two Hughes in New Jersey

    def test_short_first_names(self):
        self.assertEqual(pid("Bo Horvat", "NYI"), 8477500)
        for n in ("JJ Peterka", "J.J. Peterka", "J. J. Peterka", "J. Peterka"):
            self.assertEqual(pid(n, "BOS"), 8482175, n)
        self.assertEqual(pid("Mitch Marner", "TOR"), 8478483)
        self.assertEqual(pid("Jake Trouba", "NYR"), 8476885)

    def test_tkachuks_by_initial_and_team(self):
        self.assertEqual(pid("Matthew Tkachuk", "FLA"), 8479314)
        self.assertEqual(pid("M. Tkachuk", "FLA"), 8479314)
        self.assertEqual(pid("Brady Tkachuk", "FLA"), 8480801)
        self.assertIsNone(pid("Tkachuk", "FLA"))

    def test_game_scope_not_league(self):
        self.assertEqual(pid("Anders Lee", game=["UTA", "BOS"]), 8475314)
        self.assertIsNone(pid("Anders Lee", game=["BOS", "NYI"]))
        self.assertIsNone(pid("Anders Lee"))              # no team, no game: never on name alone
        self.assertEqual(ROSTERS.match("Anders Lee")["reason"], "no team or game")

    def test_board_team_codes(self):
        self.assertEqual(pid("A. Lee", "LA"), 8481732)
        self.assertEqual(pid("A. Lee", "UTAH"), 8475314)

    def test_box_fallback_initials(self):
        import pandas as pd
        sk = pd.DataFrame({"player_id": [8475314, 8481732, 8482116], "player_name": ["A. Lee", "A. Lee", "T. Stützle"],
                           "team_abbrev": ["UTA", "LAK", "OTT"], "position": ["L", "L", "C"],
                           "game_date": ["2026-11-01"] * 3})
        R = players.Rosters(players.from_box(sk))
        self.assertEqual(R.match("Anders Lee", "UTA")["player_id"], 8475314)
        self.assertEqual(R.match("Andre Lee", "LAK")["player_id"], 8481732)
        self.assertEqual(R.match("Stuetzle", "OTT")["player_id"], 8482116)

    def test_match_rows_counts(self):
        rows = [{"name": "A. Lee", "team": "UTA"}, {"name": "E. Pettersson", "team": "VAN"}, {"name": "Nobody", "team": "BOS"}]
        c = players.match_rows(rows, ROSTERS)
        self.assertEqual((c["matched"], c["unmatched"]), (1, 2))
        self.assertEqual(rows[0]["player_id"], 8475314)
        self.assertEqual(rows[1]["match"], "UNMATCHED")


if __name__ == "__main__":
    unittest.main()
