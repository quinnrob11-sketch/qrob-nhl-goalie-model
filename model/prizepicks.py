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


def fetch(goalies: list[dict]) -> list[dict]:
    global last_error
    last_error = None
    try:
        rows = parse(fetch_raw())
    except Exception as e:
        last_error = str(e)
        print(f"  [prizepicks] board unavailable: {e}")
        return []
    rows = match(rows, goalies)
    print(f"  [prizepicks] {len(rows)} goalie saves lines "
          f"({sum(r['goalie_id'] is None for r in rows)} unmatched)")
    return rows
