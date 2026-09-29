"""Starting goalies + saves lines from DraftKings via The Odds API.

DraftKings only hangs a saves prop on the goalie it expects to start, so a
posted line doubles as a starter signal. Needs ODDS_API_KEY in the environment
(a GitHub Actions secret); without it this is a no-op.

Also pulls DraftKings player shots-on-goal lines in the same request (module
variable `sog_rows`) for the SOG props tab.

Quota: listing events is free on The Odds API; each game costs one credit per
market (2: saves + shots), and only games starting in the next 18 hours are pulled.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

import prizepicks  # name matching helpers

BASE = "https://api.the-odds-api.com/v4/sports/icehockey_nhl"
MARKET = "player_total_saves"
SOG_MARKET = "player_shots_on_goal"
BOOK = "draftkings"
ET = ZoneInfo("America/New_York")
WINDOW_H = 18

TEAM_ABBR = {
    "Anaheim Ducks": "ANA", "Boston Bruins": "BOS", "Buffalo Sabres": "BUF", "Calgary Flames": "CGY",
    "Carolina Hurricanes": "CAR", "Chicago Blackhawks": "CHI", "Colorado Avalanche": "COL",
    "Columbus Blue Jackets": "CBJ", "Dallas Stars": "DAL", "Detroit Red Wings": "DET",
    "Edmonton Oilers": "EDM", "Florida Panthers": "FLA", "Los Angeles Kings": "LAK", "Minnesota Wild": "MIN",
    "Montreal Canadiens": "MTL", "Montréal Canadiens": "MTL", "Nashville Predators": "NSH",
    "New Jersey Devils": "NJD", "New York Islanders": "NYI", "New York Rangers": "NYR",
    "Ottawa Senators": "OTT", "Philadelphia Flyers": "PHI", "Pittsburgh Penguins": "PIT",
    "San Jose Sharks": "SJS", "Seattle Kraken": "SEA", "St. Louis Blues": "STL", "St Louis Blues": "STL",
    "Tampa Bay Lightning": "TBL", "Toronto Maple Leafs": "TOR", "Utah Mammoth": "UTA",
    "Utah Hockey Club": "UTA", "Vancouver Canucks": "VAN", "Vegas Golden Knights": "VGK",
    "Washington Capitals": "WSH", "Winnipeg Jets": "WPG",
}

last_error: str | None = None
remaining: str | None = None
sog_rows: list[dict] = []


def _get(url, params):
    global remaining
    q = urllib.parse.urlencode(params)
    req = urllib.request.Request(f"{url}?{q}", headers={"User-Agent": "qrob-goalie-model"})
    with urllib.request.urlopen(req, timeout=30) as r:
        remaining = r.headers.get("x-requests-remaining", remaining)
        return json.load(r)


def parse_event(ev: dict, js: dict, market: str = MARKET) -> list[dict]:
    """One row per player with a DraftKings line for `market` in this event."""
    home, away = TEAM_ABBR.get(ev["home_team"]), TEAM_ABBR.get(ev["away_team"])
    date = dt.datetime.fromisoformat(ev["commence_time"].replace("Z", "+00:00")).astimezone(ET).date().isoformat()
    by_player = {}
    for bm in js.get("bookmakers", []):
        if bm.get("key") != BOOK:
            continue
        for m in bm.get("markets", []):
            if m.get("key") != market:
                continue
            for o in m.get("outcomes", []):
                name, side = o.get("description"), (o.get("name") or "").lower()
                if not name or o.get("point") is None:
                    continue
                row = by_player.setdefault(name, {"name": name, "line": float(o["point"]), "date": date,
                                                  "teams": [t for t in (away, home) if t], "source": "DK"})
                if side == "over":
                    row["over"] = o.get("price")
                elif side == "under":
                    row["under"] = o.get("price")
    return list(by_player.values())


def match(rows: list[dict], goalies: list[dict]) -> list[dict]:
    """Attach goalie id + team: name match restricted to the two teams in the game."""
    by_key = {}
    for g in goalies:
        by_key.setdefault(prizepicks.name_key(g["name"]), []).append(g)
    out = []
    for r in rows:
        cands = by_key.get(prizepicks.name_key(r["name"]), [])
        in_game = [g for g in cands if g.get("team") in r["teams"]]
        g = (in_game or cands or [None])[0]
        if g is None or g.get("team") not in r["teams"]:
            print(f"  [odds] can't place {r['name']} ({'/'.join(r['teams'])}), skipped")
            continue
        r.update(goalie_id=g["id"], team=g["team"])
        out.append(r)
    return out


def fetch(goalies: list[dict], now: dt.datetime | None = None) -> list[dict]:
    global last_error, sog_rows
    last_error = None
    sog_rows = []
    key = os.environ.get("ODDS_API_KEY")
    if not key:
        last_error = "ODDS_API_KEY not set"
        print("  [odds] ODDS_API_KEY not set, skipping DraftKings lines")
        return []
    now = now or dt.datetime.now(dt.timezone.utc)
    try:
        events = _get(f"{BASE}/events", {"apiKey": key})
    except Exception as e:
        last_error = str(e)
        print(f"  [odds] events unavailable: {e}")
        return []
    rows = []
    for ev in events:
        start = dt.datetime.fromisoformat(ev["commence_time"].replace("Z", "+00:00"))
        if not (now - dt.timedelta(hours=1) <= start <= now + dt.timedelta(hours=WINDOW_H)):
            continue
        try:
            js = _get(f"{BASE}/events/{ev['id']}/odds", {"apiKey": key, "regions": "us",
                                                        "markets": f"{MARKET},{SOG_MARKET}",
                                                        "bookmakers": BOOK, "oddsFormat": "american"})
        except Exception as e:
            last_error = str(e)
            print(f"  [odds] {ev['away_team']} @ {ev['home_team']}: {e}")
            continue
        rows += parse_event(ev, js)
        sog_rows += parse_event(ev, js, SOG_MARKET)
    rows = match(rows, goalies)
    print(f"  [odds] {len(rows)} DraftKings saves lines, {len(sog_rows)} SOG lines "
          f"(requests remaining: {remaining})")
    return rows
