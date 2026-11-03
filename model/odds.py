"""Starting goalies + saves lines from DraftKings via The Odds API.

DraftKings only hangs a saves prop on the goalie it expects to start, so a
posted line doubles as a starter signal. Needs ODDS_API_KEY in the environment
(a GitHub Actions secret); without it this is a no-op.

Also pulls DraftKings player shots-on-goal lines in the same request (module
variable `sog_rows`) for the SOG props tab.

Also pulls DraftKings moneylines for every game in one request (module variable
`ml_rows`) for game-winner pricing and the saves model's game script.

Also pulls DraftKings player points lines (module variable `points_rows`).

Quota: listing events is free on The Odds API; each game costs one credit per
market (3: saves + shots + points), and only games starting in the next 18 hours are pulled.
The moneyline request costs 1 credit for the whole slate.
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
POINTS_MARKET = "player_points"
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
points_rows: list[dict] = []
ml_rows: list[dict] = []


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


def match(rows: list[dict], goalies: list[dict], R=None) -> list[dict]:
    """Attach goalie id + team: name match restricted to the two teams in the game (players.Rosters when
    given, so a goalie resolves to one NHL playerId or is skipped as unmatched)."""
    if R is not None:
        out = []
        for r in rows:
            m = R.match(r["name"], None, r["teams"], "G")
            if m["status"] != "MATCHED":
                print(f"  [odds] can't place {r['name']} ({'/'.join(r['teams'])}): {m['reason']}, skipped")
                continue
            r.update(goalie_id=m["player_id"], player_id=m["player_id"], team=m["team"])
            out.append(r)
        return out
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


def fetch_moneylines(key: str) -> list[dict]:
    """DraftKings moneylines for every listed game (one request, 1 credit)."""
    rows = []
    try:
        js = _get(f"{BASE}/odds", {"apiKey": key, "regions": "us", "markets": "h2h", "bookmakers": BOOK,
                                   "oddsFormat": "american"})
    except Exception as e:
        print(f"  [odds] moneylines unavailable: {e}")
        return rows
    for ev in js:
        home, away = TEAM_ABBR.get(ev["home_team"]), TEAM_ABBR.get(ev["away_team"])
        date = dt.datetime.fromisoformat(ev["commence_time"].replace("Z", "+00:00")).astimezone(ET).date().isoformat()
        for bm in ev.get("bookmakers", []):
            for m in bm.get("markets", []):
                if bm.get("key") != BOOK or m.get("key") != "h2h":
                    continue
                prices = {TEAM_ABBR.get(o.get("name")): o.get("price") for o in m.get("outcomes", [])}
                if home in prices and away in prices:
                    rows.append({"date": date, "home": home, "away": away,
                                 "home_ml": prices[home], "away_ml": prices[away]})
    return rows


CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "odds_cache.json")
MIN_AGE_MIN = 55          # reuse the last pull if it is younger than this (the page rebuilds every 15 min)
match_counts: dict = {}


def _skater_ids(R):
    """playerId (and team) on every DK shots / points row: name within the game's two teams, never league-wide."""
    import players
    global match_counts
    for name, rows in (("sog", sog_rows), ("points", points_rows)):
        match_counts[name] = players.match_rows(rows, R, team_key="team_", game_key="teams")


def fetch(goalies: list[dict], now: dt.datetime | None = None, R=None) -> list[dict]:
    """DraftKings lines, at most one Odds API pull per MIN_AGE_MIN (cached in model/data/odds_cache.json);
    games that have started are dropped from a reused pull."""
    global last_error, sog_rows, points_rows, ml_rows, remaining
    now = now or dt.datetime.now(dt.timezone.utc)
    if os.path.exists(CACHE):
        try:
            c = json.load(open(CACHE))
            age = (now - dt.datetime.fromisoformat(c["at"])).total_seconds() / 60
        except (ValueError, KeyError):
            c, age = None, 1e9
        if c and 0 <= age < MIN_AGE_MIN:
            live = lambda r: r.get("start") is None or dt.datetime.fromisoformat(r["start"].replace("Z", "+00:00")) > now
            sog_rows = [r for r in c["sog"] if live(r)]
            points_rows = [r for r in c["points"] if live(r)]
            ml_rows, remaining, last_error = c["ml"], c.get("remaining"), None
            rows = [r for r in c["saves"] if live(r)]
            if R is not None:
                _skater_ids(R)
            rows = match(rows, goalies, R)
            print(f"  [odds] reused the pull from {age:.0f} min ago: {len(rows)} saves, {len(sog_rows)} SOG, {len(points_rows)} points lines")
            return rows
    rows = _fetch(goalies, now, R)
    if not last_error or rows or sog_rows:
        try:
            raw = {"at": now.isoformat(), "remaining": remaining, "ml": ml_rows, "sog": sog_rows, "points": points_rows,
                   "saves": [{k: v for k, v in r.items() if k not in ("goalie_id", "player_id", "team", "match", "match_reason")}
                             for r in _raw_saves]}
            json.dump(raw, open(CACHE, "w"), separators=(",", ":"))
        except OSError:
            pass
    return rows


_raw_saves: list[dict] = []


def _fetch(goalies: list[dict], now: dt.datetime | None = None, R=None) -> list[dict]:
    global last_error, sog_rows, points_rows, ml_rows, _raw_saves
    last_error = None
    sog_rows = []
    points_rows = []
    ml_rows = []
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
    ml_rows = fetch_moneylines(key)
    rows = []
    for ev in events:
        start = dt.datetime.fromisoformat(ev["commence_time"].replace("Z", "+00:00"))
        if not (now - dt.timedelta(hours=1) <= start <= now + dt.timedelta(hours=WINDOW_H)):
            continue
        try:
            js = _get(f"{BASE}/events/{ev['id']}/odds", {"apiKey": key, "regions": "us",
                                                        "markets": f"{MARKET},{SOG_MARKET},{POINTS_MARKET}",
                                                        "bookmakers": BOOK, "oddsFormat": "american"})
        except Exception as e:
            last_error = str(e)
            print(f"  [odds] {ev['away_team']} @ {ev['home_team']}: {e}")
            continue
        for r in (x := parse_event(ev, js)) + (y := parse_event(ev, js, SOG_MARKET)) + (z := parse_event(ev, js, POINTS_MARKET)):
            r["start"] = ev["commence_time"]
        rows += x
        sog_rows += y
        points_rows += z
    _raw_saves = [dict(r) for r in rows]
    if R is not None:
        _skater_ids(R)
    rows = match(rows, goalies, R)
    print(f"  [odds] {len(rows)} DraftKings saves lines, {len(sog_rows)} SOG lines, {len(points_rows)} points lines, "
          f"{len(ml_rows)} moneylines "
          f"(requests remaining: {remaining})")
    return rows
