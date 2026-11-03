"""Which day the page shows, and live / final results for that day's games (audit item 7).

The slate day is today in America/Chicago, and it stays today until every one of today's games is
FINAL, so a 9:10 PM CT game is still on the page at 11:30 PM CT. Once they are all final the page moves
to the next day with games. Props on games that have started are no longer plays: they show in a
"live & final" list with the stat so far and HIT / MISS once decided.

Live stats come from the NHL gamecenter boxscore (api-web.nhle.com), best-effort per game.
"""
from __future__ import annotations

import datetime as dt
import json
import urllib.request
from zoneinfo import ZoneInfo

CT = ZoneInfo("America/Chicago")
FINAL = {"FINAL", "OFF"}
LIVE = {"LIVE", "CRIT"}
BOX_API = "https://api-web.nhle.com/v1/gamecenter/{id}/boxscore"

status = "not run"


def ct_today(now: dt.datetime | None = None) -> dt.date:
    now = now or dt.datetime.now(dt.timezone.utc)
    return now.astimezone(CT).date()


def ct_date(start_iso: str | None) -> str | None:
    if not start_iso:
        return None
    return dt.datetime.fromisoformat(start_iso.replace("Z", "+00:00")).astimezone(CT).date().isoformat()


def started(g: dict, now: dt.datetime | None = None) -> bool:
    """A game has started once its state says so, or (state unknown) once its start time has passed."""
    if g.get("state") in FINAL | LIVE:
        return True
    if g.get("state") in ("FUT", "PRE"):
        return False
    now = now or dt.datetime.now(dt.timezone.utc)
    s = g.get("start")
    return bool(s) and dt.datetime.fromisoformat(s.replace("Z", "+00:00")) <= now


def slate_day(games: list[dict], now: dt.datetime | None = None) -> str | None:
    """Today (CT) while any of today's games is not FINAL; then the next day that has games."""
    today = ct_today(now).isoformat()
    days = sorted({ct_date(g.get("start")) or g.get("date") for g in games} - {None})
    if not days:
        return None
    # yesterday's late game still going after midnight CT keeps yesterday up
    late = [g for g in games if (ct_date(g.get("start")) or g.get("date")) < today and g.get("state") in LIVE]
    if late:
        return min(ct_date(g.get("start")) or g.get("date") for g in late)
    todays = [g for g in games if (ct_date(g.get("start")) or g.get("date")) == today]
    if todays and not all(g.get("state") in FINAL for g in todays):
        return today
    later = [d for d in days if d > today]
    return later[0] if later else today


def parse_box(js: dict) -> dict:
    """{player_id: {"sog", "points", "saves"}} from a gamecenter boxscore."""
    out = {}
    pg = js.get("playerByGameStats") or {}
    for side in ("awayTeam", "homeTeam"):
        t = pg.get(side) or {}
        for grp in ("forwards", "defense", "goalies"):
            for p in t.get(grp) or []:
                pid = p.get("playerId")
                if pid is None:
                    continue
                g, a = p.get("goals"), p.get("assists")
                pts = p.get("points", (g or 0) + (a or 0) if g is not None or a is not None else None)
                out[int(pid)] = {"sog": p.get("sog", p.get("shots")), "points": pts, "saves": p.get("saves")}
    return out


def fetch_live(games: list[dict], timeout: int = 20) -> dict:
    """{game_id: {"state", "away_score", "home_score", "players": {...}}} for started games."""
    global status
    out, err = {}, []
    for g in games:
        if g.get("state") not in FINAL | LIVE:
            continue
        try:
            req = urllib.request.Request(BOX_API.format(id=g["id"]), headers={"User-Agent": "qrob-goalie-model"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                js = json.load(r)
            out[str(g["id"])] = {"state": js.get("gameState", g.get("state")),
                                 "away_score": (js.get("awayTeam") or {}).get("score"),
                                 "home_score": (js.get("homeTeam") or {}).get("score"),
                                 "players": {str(k): v for k, v in parse_box(js).items()}}
        except Exception as e:
            err.append(f"{g.get('id')}: {e}")
    status = f"ok ({len(out)} games)" if not err else f"partial: {'; '.join(err)[:160]}"
    return out


def leg_status(market: str, side: str, line: float, stat, state: str) -> str:
    """HIT / MISS / PUSH once decided, else LIVE (or '' before the game). An over that has already
    cleared the line is a HIT even while the game is live; an under can only be decided at the final."""
    if stat is None or state not in FINAL | LIVE:
        return ""
    over = side.upper() in ("OVER", "MORE")
    if stat > line:
        return "HIT" if over else "MISS"      # counts only go up: decided as soon as the line is passed
    if state in FINAL:
        if stat == line:
            return "PUSH"
        return "MISS" if over else "HIT"
    return "LIVE"
