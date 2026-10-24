"""Starting-goalie confirmations from DailyFaceoff's public starting-goalies page.

A goalie DailyFaceoff marks "Confirmed" counts as a confirmed starter even when no DraftKings
line or PrizePicks prop is posted for him, so he can be a play. "Likely" picks the goalie but
stays unconfirmed. Each row carries the source and the time the confirmation was posted.

The page embeds its data as Next.js JSON (__NEXT_DATA__). The parser walks that JSON for game
objects with home/away goalie names and news strengths instead of relying on one exact path, so
small layout changes don't break it. Best-effort: on any failure, `status` says why and the
build carries on without it. (The NHL API publishes no pre-game starter confirmation; its
boxscore starter flag only appears once the game is under way.)
"""
from __future__ import annotations

import datetime as dt
import json
import re
import urllib.request

import prizepicks

URL = "https://www.dailyfaceoff.com/starting-goalies/{date}"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
           "Accept": "text/html"}

# full team names and DailyFaceoff slugs -> NHL abbreviations
TEAMS = {
    "anaheim ducks": "ANA", "boston bruins": "BOS", "buffalo sabres": "BUF", "calgary flames": "CGY",
    "carolina hurricanes": "CAR", "chicago blackhawks": "CHI", "colorado avalanche": "COL",
    "columbus blue jackets": "CBJ", "dallas stars": "DAL", "detroit red wings": "DET",
    "edmonton oilers": "EDM", "florida panthers": "FLA", "los angeles kings": "LAK", "minnesota wild": "MIN",
    "montreal canadiens": "MTL", "nashville predators": "NSH", "new jersey devils": "NJD",
    "new york islanders": "NYI", "new york rangers": "NYR", "ottawa senators": "OTT",
    "philadelphia flyers": "PHI", "pittsburgh penguins": "PIT", "san jose sharks": "SJS",
    "seattle kraken": "SEA", "st louis blues": "STL", "tampa bay lightning": "TBL",
    "toronto maple leafs": "TOR", "utah mammoth": "UTA", "utah hockey club": "UTA", "vancouver canucks": "VAN",
    "vegas golden knights": "VGK", "washington capitals": "WSH", "winnipeg jets": "WPG",
}

status = "not run"


def _team(v) -> str | None:
    if not v:
        return None
    s = re.sub(r"[^a-z ]", "", str(v).lower().replace("-", " ").replace(".", "")).strip()
    if s.upper() in TEAMS.values():
        return s.upper()
    return TEAMS.get(s) or next((a for n, a in TEAMS.items() if n.endswith(" " + s) or s.endswith(n)), None)


def _games(node):
    """Every dict in the JSON tree that looks like a starting-goalies game."""
    if isinstance(node, dict):
        if any(k in node for k in ("homeGoalieName", "awayGoalieName")):
            yield node
        for v in node.values():
            yield from _games(v)
    elif isinstance(node, list):
        for v in node:
            yield from _games(v)


def parse(html: str, date: str) -> list[dict]:
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        raise ValueError("no __NEXT_DATA__ on the page")
    out = []
    for g in _games(json.loads(m.group(1))):
        for side in ("home", "away"):
            name = g.get(f"{side}GoalieName")
            team = _team(g.get(f"{side}TeamSlug") or g.get(f"{side}TeamName"))
            strength = (g.get(f"{side}NewsStrengthName") or "").strip()
            if not name or not team:
                continue
            out.append({"date": date, "team": team, "name": name, "status": strength or "Unconfirmed",
                        "source": "DailyFaceoff", "at": g.get(f"{side}NewsCreatedAt") or g.get(f"{side}NewsUpdatedAt")})
    return out


def fetch(goalies: list[dict], dates: list[str], timeout: int = 30) -> list[dict]:
    """Starter rows for the given dates, matched to goalie ids by name (and team when ambiguous)."""
    global status
    by_key = {}
    for g in goalies:
        by_key.setdefault(prizepicks.name_key(g["name"]), []).append(g)
    rows, errs = [], []
    for d in dates:
        try:
            req = urllib.request.Request(URL.format(date=d), headers=HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                html = r.read().decode("utf-8", "replace")
            rows += parse(html, d)
        except Exception as e:  # blocked, layout change, network
            errs.append(f"{d}: {e}")
    for r in rows:
        c = by_key.get(prizepicks.name_key(r["name"]), [])
        c = [g for g in c if g.get("team") == r["team"]] or c
        r["goalie_id"] = c[0]["id"] if c else None
    status = "ok" if rows else ("unavailable: " + "; ".join(errs)[:200] if errs else "no starters posted yet")
    return rows


def confirmed(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r.get("status", "").lower() == "confirmed" and r.get("goalie_id") is not None]


if __name__ == "__main__":
    today = dt.date.today().isoformat()
    print(json.dumps(fetch([], [today])[:6], indent=1), status)
