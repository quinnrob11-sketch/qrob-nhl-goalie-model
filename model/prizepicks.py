"""Starting goalies + saves lines from the PrizePicks NHL board.

PrizePicks only hangs a "Goalie Saves" prop on the goalie it expects to start,
so the board doubles as a starter feed. Public endpoint, no auth (same one the
nhl props repo scrapes). Best-effort: returns [] if the board can't be reached.
"""
from __future__ import annotations

import datetime as dt
import json
import unicodedata
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

PP_API = "https://api.prizepicks.com/projections"
NHL_LEAGUE_ID = 8
STAT = "Goalie Saves"
ET = ZoneInfo("America/New_York")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
    "Origin": "https://app.prizepicks.com",
    "Referer": "https://app.prizepicks.com/",
}

# PrizePicks team abbreviations that differ from the NHL's
TEAM_FIX = {"LA": "LAK", "NJ": "NJD", "SJ": "SJS", "TB": "TBL", "MON": "MTL", "WAS": "WSH",
            "CLB": "CBJ", "NAS": "NSH", "UTAH": "UTA", "VEG": "VGK", "CAL": "CGY"}


def fetch_raw(timeout=30):
    q = urllib.parse.urlencode({"league_id": NHL_LEAGUE_ID, "per_page": 1000, "single_stat": "true"})
    req = urllib.request.Request(f"{PP_API}?{q}", headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def parse(js) -> list[dict]:
    players = {}
    for inc in js.get("included", []):
        if inc.get("type") in ("new_player", "player"):
            a = inc.get("attributes") or {}
            players[inc["id"]] = a
    out = []
    for p in js.get("data", []):
        a = p.get("attributes") or {}
        if a.get("stat_type") != STAT:
            continue
        # standard lines only: goblins/demons/promos are shifted lines
        if (a.get("odds_type") or "standard").lower() != "standard" or a.get("is_promo") \
                or a.get("flash_sale_line_score") is not None:
            continue
        rel = p.get("relationships") or {}
        ref = ((rel.get("new_player") or rel.get("player") or {}).get("data")) or {}
        pl = players.get(ref.get("id"), {})
        name = pl.get("name") or pl.get("display_name")
        if not name or a.get("line_score") is None:
            continue
        team = (pl.get("team") or pl.get("team_abbreviation") or "").upper()
        date = None
        if a.get("start_time"):
            try:
                date = dt.datetime.fromisoformat(a["start_time"]).astimezone(ET).date().isoformat()
            except ValueError:
                pass
        out.append({
            "name": name, "team": TEAM_FIX.get(team, team), "line": float(a["line_score"]),
            "date": date, "opp": (a.get("description") or "").upper(),
            "url": f"https://app.prizepicks.com/projections/{p.get('id')}",
        })
    return out


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return s.lower().replace(".", "").replace("'", "").strip()


def name_key(full_or_short: str) -> str:
    """'Frederik Andersen' and 'F. Andersen' both -> 'f andersen'."""
    parts = _norm(full_or_short).split()
    if len(parts) < 2:
        return _norm(full_or_short)
    return f"{parts[0][0]} {' '.join(parts[1:])}"


def match(pp_rows: list[dict], goalies: list[dict]) -> list[dict]:
    """Attach our goalie id (by initial + last name, team as tiebreak)."""
    by_key = {}
    for g in goalies:
        by_key.setdefault(name_key(g["name"]), []).append(g)
    for r in pp_rows:
        cands = by_key.get(name_key(r["name"]), [])
        if len(cands) > 1:
            cands = [g for g in cands if g.get("team") == r["team"]] or cands
        r["goalie_id"] = cands[0]["id"] if cands else None
        if not r["team"] and cands:
            r["team"] = cands[0].get("team")
    return pp_rows


last_error: str | None = None
status: str = "not tried"      # "ok", "unavailable" (blocked), or "error"


# ---------- skater props for the board (SOG and points), from the same /projections response ----------
# Goalie saves keep their existing path above (starter feed + saves table). Standard lines only (no goblins,
# demons, promos or flash sales); a standard PrizePicks pick is a 1x DFS leg in this model's pricing.
PROP_STATS = {"Shots On Goal": "sog", "Shots": "sog", "Player Shots": "sog", "Points": "points"}
SOURCE = "PrizePicks"
import os  # noqa: E402
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "pp_cache.json")
last_js = None                    # the /projections response of this build's pull (one request serves both paths)
props_status = "not run"          # "fresh" | "fallback" (last good board reused because this pull failed) | "error"
props_fetched_at: str | None = None
props_review: list[dict] = []


def parse_props(js, slate: list[dict], R, fetched_at: str, now: dt.datetime | None = None):
    """(board rows, drop counts): shots and points lines matched to one NHL playerId within the row's team."""
    import pick6
    import slate as slate_mod
    global props_review
    players = {inc["id"]: inc.get("attributes") or {} for inc in js.get("included", [])
               if inc.get("type") in ("new_player", "player")}
    rows, drops, review, seen = [], {}, [], set()
    for p in js.get("data", []):
        a = p.get("attributes") or {}
        mk = PROP_STATS.get(a.get("stat_type"))
        if mk is None or a.get("line_score") is None:
            continue
        if (a.get("odds_type") or "standard").lower() != "standard" or a.get("is_promo") \
                or a.get("flash_sale_line_score") is not None:
            continue
        rel = p.get("relationships") or {}
        pl = players.get((((rel.get("new_player") or rel.get("player") or {}).get("data")) or {}).get("id"), {})
        name = pl.get("name") or pl.get("display_name")
        team = (pl.get("team") or pl.get("team_abbreviation") or "").upper()
        team = TEAM_FIX.get(team, team) or None
        if not name:
            continue
        g = pick6._game_for({"team": team, "start": a.get("start_time")}, slate)
        m = R.match(name, team, [g["home"], g["away"]] if g else None) if R is not None else {"status": "UNMATCHED", "reason": "no rosters"}
        why = None
        if m["status"] != "MATCHED":
            why = "unmatched player"
            review.append({"name": name, "team": team, "market": mk, "line": float(a["line_score"]), "reason": m.get("reason") or "unmatched"})
        elif g is None:
            why = "missing game"
        elif slate_mod.started(g, now):
            why = "game started"
        key = (m.get("player_id"), mk, float(a["line_score"]))
        if why is None and key in seen:
            why = "duplicate"
        if why:
            drops[why] = drops.get(why, 0) + 1
            continue
        seen.add(key)
        rows.append({"name": name, "player_id": m["player_id"], "team": m.get("team") or team, "game": g["id"],
                     "date": g["date"], "market": mk, "line": float(a["line_score"]), "mo": 1.0, "mu": 1.0,
                     "source": SOURCE, "fetched_at": fetched_at, "pos": m.get("pos"),
                     "url": f"https://app.prizepicks.com/projections/{p.get('id')}"})
    props_review = review[:100]
    return rows, drops


def from_odds(odds_rows, slate: list[dict], now: dt.datetime | None = None) -> list[dict]:
    """PrizePicks lines as The Odds API serves them (bookmaker "prizepicks") -> board rows. Standard lines
    are 1x DFS legs, More and Less (a side the API doesn't list is not offered: multiplier 0). Demons and
    goblins (*_alternate markets) pay differently, so they are priced at the odds the API gives them."""
    import pick6
    import slate as slate_mod
    global props_review
    out, review, seen = [], [], set()
    for r in odds_rows or []:
        if r.get("match") != "MATCHED" or r.get("player_id") is None:
            review.append({"name": r.get("name"), "team": "/".join(r.get("teams") or []), "market": r.get("market"),
                           "line": r.get("line"), "reason": r.get("match_reason") or "unmatched"})
            continue
        g = pick6._game_for({"team": r.get("team"), "start": r.get("start")}, slate)
        if g is None or slate_mod.started(g, now):
            continue
        alt = bool(r.get("alt"))
        key = (r["player_id"], r["market"], float(r["line"]), alt)
        if key in seen:
            continue
        seen.add(key)
        row = {"name": r["name"], "player_id": int(r["player_id"]), "team": r.get("team"), "game": g["id"], "date": g["date"],
               "market": r["market"], "line": float(r["line"]), "source": SOURCE, "fetched_at": r.get("fetched_at"), "via": "The Odds API"}
        if alt:
            row.update(mo=None, mu=None, over=r.get("over"), under=r.get("under"), priced=True, alt=True)
        else:
            row.update(mo=1.0 if r.get("over") is not None else 0.0, mu=1.0 if r.get("under") is not None else 0.0)
        out.append(row)
    props_review = review[:100]
    return out


def props(slate: list[dict], R, now: dt.datetime | None = None, odds_rows=None, odds_status: str | None = None,
          odds_at: str | None = None) -> list[dict]:
    """This build's PrizePicks lines for the board.
    1. PrizePicks' own API (fetch() already pulled it), when PrizePicks lets the build through.
    2. Otherwise the PrizePicks lines The Odds API carries (odds.pp_rows), with the Odds pull's status and fetch time.
    3. Otherwise the last good board in model/data/pp_cache.json, ORIGINAL fetch time, status "fallback"."""
    global props_status, props_fetched_at
    if last_js is None and odds_rows:
        rows = from_odds(odds_rows, slate, now)
        props_status, props_fetched_at = (odds_status or "fresh"), (odds_at or (rows[0]["fetched_at"] if rows else None))
        print(f"  [prizepicks] {len(rows)} lines via The Odds API ({props_status}; "
              f"{sum(r.get('alt', False) for r in rows)} demon / goblin, {len(props_review)} unmatched)")
        if rows and props_status == "fresh":
            try:
                with open(CACHE, "w") as f:
                    json.dump({"at": props_fetched_at, "rows": rows}, f, separators=(",", ":"))
            except OSError:
                pass
        return rows
    if last_js is not None:
        at = (now or dt.datetime.now(dt.timezone.utc)).isoformat(timespec="seconds")
        rows, drops = parse_props(last_js, slate, R, at, now)
        props_status, props_fetched_at = "fresh", at
        print(f"  [prizepicks] {len(rows)} shots / points lines for the board (dropped: {drops or 'none'})")
        try:
            with open(CACHE, "w") as f:
                json.dump({"at": at, "rows": rows}, f, separators=(",", ":"))
        except OSError:
            pass
        return rows
    try:
        with open(CACHE) as f:
            c = json.load(f)
        c_at, c_rows = c["at"], c["rows"]
    except (OSError, ValueError, KeyError, TypeError):
        props_status, props_fetched_at = "error", None
        return []
    import slate as slate_mod
    games = {g["id"]: g for g in slate}
    keep = [{**r, "fetched_at": r.get("fetched_at") or c_at} for r in c_rows
            if r.get("game") in games and not slate_mod.started(games[r["game"]], now)]
    props_status, props_fetched_at = "fallback", c_at
    print(f"  [prizepicks] pull failed ({last_error}); FALLBACK to the last good board from {c_at}: {len(keep)} rows")
    return keep


def fetch(goalies: list[dict], tries: int = 3) -> list[dict]:
    """Retry transient failures (timeouts, 5xx, 429) with backoff. A 401/403 is PrizePicks refusing
    requests from cloud servers, which retrying doesn't change, so the source is marked unavailable
    and the page falls back to the live pull from the user's own browser."""
    import time
    import urllib.error
    global last_error, status, last_js
    last_error, status, last_js = None, "error", None
    for i in range(tries):
        try:
            js = fetch_raw()
            rows = parse(js)
            last_js, status = js, "ok"
            break
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                status = "unavailable"
                last_error = f"HTTP {e.code}: PrizePicks blocks requests from cloud servers; using the live pull in your browser"
                print(f"  [prizepicks] {last_error}")
                return []
            last_error = f"HTTP {e.code}"
        except Exception as e:  # timeouts, connection resets
            last_error = str(e)
        if i < tries - 1:
            time.sleep(2 * (i + 1))
    else:
        print(f"  [prizepicks] board unavailable after {tries} tries: {last_error}")
        return []
    rows = match(rows, goalies)
    print(f"  [prizepicks] {len(rows)} goalie saves lines "
          f"({sum(r['goalie_id'] is None for r in rows)} unmatched)")
    return rows
