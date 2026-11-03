"""Current line combinations and power-play units from DailyFaceoff's public team pages.

For each team on the slate: which forward line (F1-F4) / defence pair (D1-D3) and which power-play
unit (PP1 / PP2) every skater is on. Used to:
  * tag rows with the player's role (e.g. "F2 · PP1");
  * flag role changes the box scores haven't caught up with yet: when a player's listed line is two or
    more slots from where his recent ice time puts him (e.g. a top-six forward moved to the fourth line)
    the row gets a role-change badge. The prop is never dropped. Expected TOI moves only when the
    combination was confirmed (DailyFaceoff updated the page) within CONFIRM_H hours: blended halfway
    toward the league-average TOI of the new slot, capped at +/- TOI_CAP (role_toi()). This overlay is
    not backtested (there is no history of pre-game line combos), so it is half-weight and capped.

The page embeds its data as Next.js JSON (__NEXT_DATA__); the parser walks it for player entries
with a group identifier instead of relying on one exact path. Best-effort: on failure `status`
says why and nothing changes.
"""
from __future__ import annotations

import json
import re
import urllib.request

import prizepicks
import starters

URL = "https://www.dailyfaceoff.com/teams/{slug}/line-combinations"
HEADERS = starters.HEADERS
SLUGS = {a: n.replace(" ", "-") for n, a in starters.TEAMS.items() if n != "utah hockey club"}
FWD = {"f1": 1, "f2": 2, "f3": 3, "f4": 4}
DEF = {"d1": 1, "d2": 2, "d3": 3}

status = "not run"
CONFIRM_H = 6.0       # a role change moves TOI only if the combination was updated this recently
TOI_CAP = 0.15        # ... and by at most this fraction of the player's expected TOI
UPDATED_KEYS = ("updatedAt", "lastUpdated", "updated_at", "modifiedAt", "lastModified", "publishedAt", "dateModified")


def _entries(node):
    if isinstance(node, dict):
        gid = node.get("groupIdentifier") or node.get("group_identifier")
        name = node.get("name") or node.get("playerName") or node.get("fullName")
        if gid and name and isinstance(name, str):
            yield str(gid).lower(), name
        for v in node.values():
            yield from _entries(v)
    elif isinstance(node, list):
        for v in node:
            yield from _entries(v)


def _updated(node, best=None):
    """Latest ISO timestamp under any updated-at style key in the page data."""
    if isinstance(node, dict):
        for k in UPDATED_KEYS:
            v = node.get(k)
            if isinstance(v, str) and re.match(r"\d{4}-\d{2}-\d{2}T", v) and (best is None or v > best):
                best = v
        for v in node.values():
            best = _updated(v, best)
    elif isinstance(node, list):
        for v in node:
            best = _updated(v, best)
    return best


def updated_at(html: str) -> str | None:
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    return _updated(json.loads(m.group(1))) if m else None


def parse(html: str) -> dict:
    """name -> {"line": "F2" / "D1" / None, "pp": "PP1" / "PP2" / None}"""
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        raise ValueError("no __NEXT_DATA__ on the page")
    out = {}
    for gid, name in _entries(json.loads(m.group(1))):
        r = out.setdefault(name, {"line": None, "pp": None})
        if gid in FWD:
            r["line"] = f"F{FWD[gid]}"
        elif gid in DEF:
            r["line"] = f"D{DEF[gid]}"
        elif gid in ("pp1", "pp2"):
            r["pp"] = gid.upper()
    return out


def fetch(teams, timeout: int = 20) -> dict:
    """team -> {name_key: {"name", "line", "pp", "updated"}} for the given teams ("updated" = when
    DailyFaceoff last changed the page, or None)."""
    global status
    out, errs = {}, []
    for t in sorted(teams):
        slug = SLUGS.get(t)
        if not slug:
            continue
        try:
            req = urllib.request.Request(URL.format(slug=slug), headers=HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                page = r.read().decode("utf-8", "replace")
            rows, upd = parse(page), updated_at(page)
            out[t] = {prizepicks.name_key(n): {"name": n, **v, "updated": upd} for n, v in rows.items() if v["line"] or v["pp"]}
        except Exception as e:  # blocked, layout change, network
            errs.append(f"{t}: {e}")
    status = f"ok ({len(out)} teams)" if out else ("unavailable: " + "; ".join(errs)[:200] if errs else "no teams")
    return out


def slot_toi(skater_df, season: int) -> dict:
    """League-average TOI by slot this season: forwards ranked by TOI within each team-game
    (ranks 1-3 = F1 ... 10-12 = F4), defencemen by pairs (1-2 = D1 ...)."""
    import numpy as np
    s = skater_df[skater_df.season == season].copy()
    out = {}
    for pos, size, n in (("F", 3, 4), ("D", 2, 3)):
        x = s[s.pos == pos].copy()
        x["rank"] = x.groupby(["game_id", "team_abbrev"]).toi_min.rank(ascending=False, method="first")
        for k in range(1, n + 1):
            m = (x["rank"] > (k - 1) * size) & (x["rank"] <= k * size)
            out[f"{pos}{k}"] = round(float(x[m].toi_min.mean()), 2) if m.any() else None
    return {k: v for k, v in out.items() if v is not None and not np.isnan(v)}


def recent_slot(rank: float, pos: str) -> str:
    size = 3 if pos == "F" else 2
    top = 4 if pos == "F" else 3
    return f"{pos}{min(top, int((rank - 1) // size) + 1)}"


def confirmed_recently(updated: str | None, now=None, hours: float = CONFIRM_H) -> bool:
    import datetime as dt
    if not updated:
        return False
    try:
        t = dt.datetime.fromisoformat(str(updated).replace("Z", "+00:00"))
    except ValueError:
        return False
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    now = now or dt.datetime.now(dt.timezone.utc)
    return dt.timedelta(0) <= now - t <= dt.timedelta(hours=hours)


def role_toi(exp_toi: float, listed: str | None, recent: str | None, slots: dict, updated: str | None = None,
             now=None) -> tuple[float, bool, bool]:
    """Role change = the listed line is two or more slots from the recent one (one-line shuffles happen all
    the time and are left to the recency-weighted TOI). Returns (toi, changed, adjusted): TOI is blended
    halfway to the new slot's average, capped at +/- TOI_CAP, only when the combination was updated within
    CONFIRM_H hours; otherwise the row is only badged."""
    if not listed or not recent or listed[0] != recent[0] or listed not in slots:
        return exp_toi, False, False
    if abs(int(listed[1:]) - int(recent[1:])) < 2:
        return exp_toi, False, False
    if not confirmed_recently(updated, now):
        return exp_toi, True, False
    toi = 0.5 * exp_toi + 0.5 * slots[listed]
    toi = min(max(toi, exp_toi * (1 - TOI_CAP)), exp_toi * (1 + TOI_CAP))
    return toi, True, True
