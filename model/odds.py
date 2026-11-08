"""Starting goalies + saves lines from DraftKings via The Odds API.

DraftKings only hangs a saves prop on the goalie it expects to start, so a
posted line doubles as a starter signal. Needs ODDS_API_KEY in the environment
(a GitHub Actions secret); without it this is a no-op.

Also pulls DraftKings player shots-on-goal lines in the same request (module
variable `sog_rows`) for the SOG props tab.

Also pulls DraftKings moneylines for every game in one request (module variable
`ml_rows`) for game-winner pricing and the saves model's game script.

Also pulls DraftKings player points lines (module variable `points_rows`).

Also pulls PrizePicks (bookmaker "prizepicks", The Odds API's us_dfs region) for the same three markets in
the same request (module variable `pp_rows`). PrizePicks refuses cloud servers on its own API, so this is
how the build gets its board. Up to 10 bookmakers named in `bookmakers=` count as one region, so adding
PrizePicks costs no extra credits. Its demons and goblins are in the *_alternate markets, which cost one
credit per market per game, so they are pulled only with ODDS_PP_ALT=1.

Quota: listing events is free on The Odds API; each game costs one credit per
market (3: saves + shots + points), and only games starting in the next 18 hours are pulled.
The moneyline request costs 1 credit for the whole slate.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

import prizepicks  # name matching helpers

BASE = "https://api.the-odds-api.com/v4/sports/icehockey_nhl"
MARKET = "player_total_saves"
SOG_MARKET = "player_shots_on_goal"
POINTS_MARKET = "player_points"
BOOK = "draftkings"
PP_BOOK = "prizepicks"
# Other sportsbooks pulled in the same request. The Odds API bills up to 10 bookmakers named in `bookmakers=` as
# one region, so these cost no extra credits (the build logs x-requests-last per request to prove it). Their
# prices are logged (model/data/book_prices.csv) so a multi-book consensus can be validated forward, and they
# give a market reference where DraftKings doesn't price a player's line (otherwise the model would be alone).
OTHER_BOOKS = ["fanduel", "betmgm", "williamhill_us", "espnbet", "fanatics", "betrivers", "pinnacle"]
BOOK_NAME = {"fanduel": "FanDuel", "betmgm": "BetMGM", "williamhill_us": "Caesars", "espnbet": "ESPN BET",
             "fanatics": "Fanatics", "betrivers": "BetRivers", "pinnacle": "Pinnacle"}
MARKET_OF = {MARKET: "saves", SOG_MARKET: "sog", POINTS_MARKET: "points"}
ALT_MARKETS = [m + "_alternate" for m in (MARKET, SOG_MARKET, POINTS_MARKET)]
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
last_costs: list = []             # credits each odds request cost (x-requests-last), for the build log
sog_rows: list[dict] = []
points_rows: list[dict] = []
pp_rows: list[dict] = []          # PrizePicks lines via The Odds API: saves, shots and points
book_rows: list[dict] = []        # the other sportsbooks' lines (OTHER_BOOKS): saves, shots and points
books_used: str = ""
ml_rows: list[dict] = []


def _get(url, params):
    global remaining
    q = urllib.parse.urlencode(params)
    req = urllib.request.Request(f"{url}?{q}", headers={"User-Agent": "qrob-goalie-model"})
    with urllib.request.urlopen(req, timeout=30) as r:
        remaining = r.headers.get("x-requests-remaining", remaining)
        if "/odds" in url:
            last_costs.append(r.headers.get("x-requests-last"))
        return json.load(r)


def parse_event(ev: dict, js: dict, market: str = MARKET, book: str = BOOK) -> list[dict]:
    """One row per player and line for `market` from `book` in this event (DraftKings posts one line
    per player; PrizePicks alternates (demons / goblins) can post several)."""
    home, away = TEAM_ABBR.get(ev["home_team"]), TEAM_ABBR.get(ev["away_team"])
    date = dt.datetime.fromisoformat(ev["commence_time"].replace("Z", "+00:00")).astimezone(ET).date().isoformat()
    by_player = {}
    for bm in js.get("bookmakers", []):
        if bm.get("key") != book:
            continue
        for m in bm.get("markets", []):
            if m.get("key") != market:
                continue
            for o in m.get("outcomes", []):
                name, side = o.get("description"), (o.get("name") or "").lower()
                if not name or o.get("point") is None:
                    continue
                key = name if book == BOOK else (name, float(o["point"]))
                row = by_player.setdefault(key, {"name": name, "line": float(o["point"]), "date": date,
                                                 "teams": [t for t in (away, home) if t], "source": "DK" if book == BOOK else "PP"})
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
match_counts: dict = {}
# every build pulls DraftKings fresh; the cache is the last-known-good pull, used ONLY when this pull fails
status: str = "not run"       # "fresh" | "fallback" (last good pull reused because this one failed) | "error"
fetched_at: str | None = None  # when the lines in use were really pulled (never the build time of a later build)


def _skater_ids(R):
    """playerId (and team) on every DK shots / points row: name within the game's two teams, never league-wide."""
    import players
    global match_counts
    for name, rows in (("sog", sog_rows), ("points", points_rows)):
        match_counts[name] = players.match_rows(rows, R, team_key="team_", game_key="teams")
    for name, src in (("prizepicks", pp_rows), ("books", book_rows)):
        sk = [r for r in src if r["market"] != "saves"]
        gl = [r for r in src if r["market"] == "saves"]
        match_counts[name] = players.match_rows(sk, R, team_key="team_", game_key="teams")
        for r in gl:          # saves: goalies only, within the game's two teams
            m = R.match(r["name"], None, r["teams"], "G")
            r["player_id"], r["match"], r["team"] = m["player_id"], m["status"], m.get("team")
            if m["status"] != "MATCHED":
                r["match_reason"] = m["reason"]
        match_counts[name + "_saves"] = {"matched": sum(r["match"] == "MATCHED" for r in gl),
                                         "unmatched": sum(r["match"] != "MATCHED" for r in gl)}


def _stamp(rows, at):
    for r in rows:
        r.setdefault("fetched_at", at)
    return rows


def fetch(goalies: list[dict], now: dt.datetime | None = None, R=None) -> list[dict]:
    """DraftKings saves / SOG / points lines, pulled fresh on every build. Each row carries `fetched_at`, the
    time of the pull it came from. If this pull fails (no key, API error, no lines at all), the last good pull
    in model/data/odds_cache.json is reused with its ORIGINAL fetched_at and status "fallback"; games that
    have started are dropped from it."""
    global last_error, sog_rows, points_rows, ml_rows, remaining, status, fetched_at, pp_rows, book_rows
    now = now or dt.datetime.now(dt.timezone.utc)
    at = now.isoformat(timespec="seconds")
    rows = _fetch(goalies, now, R)
    if rows or sog_rows or points_rows:
        status, fetched_at = "fresh", at
        for rs in (rows, sog_rows, points_rows, _raw_saves, pp_rows, book_rows):
            _stamp(rs, at)
        try:
            raw = {"at": at, "remaining": remaining, "ml": ml_rows, "sog": sog_rows, "points": points_rows, "pp": pp_rows,
                   "books": book_rows,
                   "saves": [{k: v for k, v in r.items() if k not in ("goalie_id", "player_id", "team", "match", "match_reason")}
                             for r in _raw_saves]}
            with open(CACHE, "w") as f:
                json.dump(raw, f, separators=(",", ":"))
        except OSError:
            pass
        return rows
    err = last_error or "no DraftKings lines returned"
    try:
        with open(CACHE) as f:
            c = json.load(f)
        c_at = c["at"]
        dt.datetime.fromisoformat(c_at)
    except (OSError, ValueError, KeyError, TypeError):
        status, fetched_at, last_error = "error", None, err
        print(f"  [odds] DraftKings pull failed ({err}) and there is no last good pull")
        return rows
    live = lambda r: r.get("start") is None or dt.datetime.fromisoformat(r["start"].replace("Z", "+00:00")) > now
    sog_rows = _stamp([r for r in c["sog"] if live(r)], c_at)
    points_rows = _stamp([r for r in c["points"] if live(r)], c_at)
    pp_rows = _stamp([r for r in c.get("pp") or [] if live(r)], c_at)
    book_rows = _stamp([r for r in c.get("books") or [] if live(r)], c_at)
    ml_rows, remaining = c.get("ml") or [], c.get("remaining", remaining)
    rows = _stamp([dict(r) for r in c["saves"] if live(r)], c_at)
    if R is not None:
        _skater_ids(R)
    rows = match(rows, goalies, R)
    status, fetched_at, last_error = "fallback", c_at, err
    print(f"  [odds] DraftKings pull failed ({err}); FALLBACK to the last good pull from {c_at}: "
          f"{len(rows)} saves, {len(sog_rows)} SOG, {len(points_rows)} points lines")
    return rows


_raw_saves: list[dict] = []


def _fetch(goalies: list[dict], now: dt.datetime | None = None, R=None) -> list[dict]:
    global last_error, sog_rows, points_rows, ml_rows, _raw_saves, pp_rows, book_rows, books_used
    last_error = None
    sog_rows = []
    points_rows = []
    pp_rows = []
    book_rows = []
    books_used = ""
    ml_rows = []
    last_costs.clear()
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
        # games that have started are skipped: their props are off the board, and pulling them cost credits and
        # stored in-game prices that later read as pre-game ones
        if not (now < start <= now + dt.timedelta(hours=WINDOW_H)):
            continue
        try:
            # DraftKings, PrizePicks and the other books in one request: up to 10 named bookmakers bill as one region.
            # If the API rejects a bookmaker key, fall back to DraftKings + PrizePicks for the rest of the build.
            mkts = [MARKET, SOG_MARKET, POINTS_MARKET] + (ALT_MARKETS if os.environ.get("ODDS_PP_ALT") == "1" else [])
            books = books_used or ",".join([BOOK, PP_BOOK] + OTHER_BOOKS)
            try:
                js = _get(f"{BASE}/events/{ev['id']}/odds", {"apiKey": key, "markets": ",".join(mkts),
                                                            "bookmakers": books, "oddsFormat": "american"})
            except urllib.error.HTTPError as e:
                if e.code not in (400, 422) or books == f"{BOOK},{PP_BOOK}":
                    raise
                print(f"  [odds] bookmaker list rejected (HTTP {e.code}); using DraftKings + PrizePicks only")
                books = f"{BOOK},{PP_BOOK}"
                js = _get(f"{BASE}/events/{ev['id']}/odds", {"apiKey": key, "markets": ",".join(mkts),
                                                            "bookmakers": books, "oddsFormat": "american"})
            books_used = books
        except Exception as e:
            last_error = str(e)
            print(f"  [odds] {ev['away_team']} @ {ev['home_team']}: {e}")
            continue
        for r in (x := parse_event(ev, js)) + (y := parse_event(ev, js, SOG_MARKET)) + (z := parse_event(ev, js, POINTS_MARKET)):
            r["start"] = ev["commence_time"]
        rows += x
        sog_rows += y
        points_rows += z
        for mk in [MARKET, SOG_MARKET, POINTS_MARKET] + (ALT_MARKETS if os.environ.get("ODDS_PP_ALT") == "1" else []):
            for r in parse_event(ev, js, mk, PP_BOOK):
                r.update(start=ev["commence_time"], market=MARKET_OF[mk.replace("_alternate", "")], alt=mk.endswith("_alternate"))
                pp_rows.append(r)
        for b in OTHER_BOOKS:
            for mk in (MARKET, SOG_MARKET, POINTS_MARKET):
                for r in parse_event(ev, js, mk, b):
                    if r.get("over") is None or r.get("under") is None:
                        continue                  # a market reference needs both sides to remove the vig
                    r.update(start=ev["commence_time"], market=MARKET_OF[mk], book=BOOK_NAME[b], source=BOOK_NAME[b])
                    book_rows.append(r)
    _raw_saves = [dict(r) for r in rows]
    if R is not None:
        _skater_ids(R)
    rows = match(rows, goalies, R)
    print(f"  [odds] {len(rows)} DraftKings saves lines, {len(sog_rows)} SOG lines, {len(points_rows)} points lines, "
          f"{len(ml_rows)} moneylines; PrizePicks {len(pp_rows)} lines; other books {len(book_rows)} lines "
          f"({sorted({r['book'] for r in book_rows})}); credits per request {last_costs[-12:]} "
          f"(requests remaining: {remaining})")
    return rows
