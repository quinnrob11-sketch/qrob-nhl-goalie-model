"""DraftKings Pick6 NHL board, pulled by the build (audit item 10).

The old `?_data=routes/_homeShared` JSON endpoint now returns the HTML page, so the board is read from
the loader data embedded in the page. Two embeddings are handled:
  * `window.__remixContext = {...};` (or `__reactRouterContext`) with `state.loaderData` as plain JSON;
  * Single Fetch / React Router: `...streamController.enqueue("<turbo-stream>")` chunks, decoded here.
The decoded tree is walked for prop-shaped objects (a player name, a stat / market, a numeric line,
More / Less multipliers, the player's team and the game) instead of one fixed path, so small layout
changes don't break it; field names that look like these are listed in NAME_KEYS etc. below.

Every row must carry playerId (players.match), team, game, market, line, More multiplier, Less
multiplier, source and fetched-at time. Rows missing any of these are dropped and counted by reason
(`stats`); the page shows the counts, and a 0-row parse is reported as a failure (banner), never as an
empty board. Props on games that have started are removed.

Best-effort: on any failure `status` says why and the build carries on. A 401/403 is DraftKings
refusing the request; it is reported as such and not retried around.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import urllib.parse
import urllib.request

import players

URL = "https://pick6.draftkings.com/?sport=NHL"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36", "Accept": "text/html"}
SOURCE = "Pick6"

NAME_KEYS = ("playerName", "displayName", "fullName", "name", "participantName")
LINE_KEYS = ("lineValue", "line", "targetValue", "statValue", "value", "points")
MARKET_KEYS = ("marketName", "statName", "statType", "stat", "market", "marketCategory", "category", "propType")
TEAM_KEYS = ("teamAbbreviation", "teamAbbr", "team", "abbreviation", "teamShortName")
POS_KEYS = ("position", "positionAbbreviation", "pos")
GAME_KEYS = ("eventId", "gameId", "competitionId", "matchupId", "event", "game", "competition")
START_KEYS = ("startTime", "startDate", "eventStartTime", "startTimeUtc", "scheduledTime")
MORE_KEYS = ("moreMultiplier", "overMultiplier", "higherMultiplier", "moreBoost", "overPayout")
LESS_KEYS = ("lessMultiplier", "underMultiplier", "lowerMultiplier", "lessBoost", "underPayout")
NEST_KEYS = ("player", "entity", "participant", "pickableEntity", "athlete", "competitor")
MARKETS = {"shots on goal": "sog", "shots": "sog", "sog": "sog", "player shots on goal": "sog",
           "points": "points", "pts": "points", "player points": "points",
           "saves": "saves", "goalie saves": "saves", "goaltender saves": "saves",
           "blocked shots": "blocks", "blocks": "blocks", "assists": "assists", "goals": "goals",
           "power play points": "ppp", "hits": "hits", "goals against": "goals_against"}
REQUIRED = ("player_id", "team", "game", "market", "line", "mo", "mu", "source", "fetched_at")

status = "not run"
stats: dict = {}


# ---------- loader data ----------
NEG = {-1: None, -2: float("nan"), -3: float("-inf"), -4: -0.0, -5: None, -6: float("inf"), -7: None}


def turbo_decode(text: str):
    """Decode a turbo-stream payload (Remix / React Router single fetch). The first line is the flattened
    value table; later "P<id>:..." lines resolve promises and are decoded the same way and attached."""
    lines = [ln for ln in text.split("\n") if ln.strip()]
    if not lines:
        return None
    values = json.loads(lines[0])
    if not isinstance(values, list):
        return values
    memo = {}

    def hyd(i, vals, memo):
        if isinstance(i, int) and i < 0:
            return NEG.get(i)
        if i in memo:
            return memo[i]
        v = vals[i]
        if isinstance(v, dict):
            out = {}
            memo[i] = out
            for k, vi in v.items():
                key = vals[int(k[1:])] if k.startswith("_") and k[1:].isdigit() else k
                out[str(key)] = hyd(vi, vals, memo)
            return out
        if isinstance(v, list):
            if v and isinstance(v[0], str):          # typed value: ["D", ms], ["P", id], ["S", ...], ["M", ...]
                t = v[0]
                if t == "D":
                    return v[1]
                if t in ("S", "Y"):
                    return [hyd(x, vals, memo) for x in v[1:]]
                if t == "M":
                    return {str(hyd(v[j], vals, memo)): hyd(v[j + 1], vals, memo) for j in range(1, len(v) - 1, 2)}
                if t == "P":
                    return {"__promise__": v[1]}
                if t == "N" and len(v) > 1 and isinstance(v[1], dict):
                    return hyd_obj(v[1], vals, memo)
                if t == "U":
                    return v[1]
                return [hyd(x, vals, memo) if isinstance(x, int) else x for x in v[1:]]
            out = []
            memo[i] = out
            out.extend(hyd(x, vals, memo) if isinstance(x, int) else x for x in v)
            return out
        return v

    def hyd_obj(o, vals, memo):
        return {str(vals[int(k[1:])] if k.startswith("_") else k): hyd(vi, vals, memo) for k, vi in o.items()}

    root = hyd(0, values, memo)
    resolved = {}
    for ln in lines[1:]:
        m = re.match(r"^[PE](\d+):(.*)$", ln)
        if not m:
            continue
        try:
            vals = json.loads(m.group(2))
            resolved[int(m.group(1))] = hyd(0, vals, {}) if isinstance(vals, list) else vals
        except (ValueError, IndexError, KeyError):
            continue
    if resolved:
        return {"root": root, "resolved": list(resolved.values())}
    return root


def _js_string(lit: str) -> str:
    """The value of a JS string literal (double-quoted, JSON-style escapes)."""
    return json.loads(lit)


def loader_data(page: str):
    """Every embedded loader-data tree in the page: plain context JSON and/or decoded turbo-stream."""
    out = []
    for m in re.finditer(r"window\.__(?:remix|reactRouter)Context\s*=\s*(\{.*?\});\s*(?:</script>|window\.|__)", page, re.S):
        try:
            out.append(json.loads(m.group(1)))
        except ValueError:
            pass
    chunks = [_js_string(m.group(1)) for m in re.finditer(r'\.enqueue\(\s*("(?:[^"\\]|\\.)*")\s*\)', page, re.S)]
    if chunks:
        try:
            out.append(turbo_decode("".join(chunks)))
        except (ValueError, IndexError, KeyError, TypeError):
            pass
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', page, re.S)
    if m:
        try:
            out.append(json.loads(m.group(1)))
        except ValueError:
            pass
    # the old endpoint's JSON, in case it is served again
    s = page.lstrip()
    if s.startswith("{") or s.startswith("["):
        try:
            out.append(json.loads(s))
        except ValueError:
            pass
    return out


# ---------- prop extraction ----------
def _num(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        m = re.fullmatch(r"\s*([0-9]+(?:\.[0-9]+)?)\s*x?\s*", v)
        return float(m.group(1)) if m else None
    if isinstance(v, dict):
        for k in ("value", "multiplier", "amount"):
            if k in v:
                return _num(v[k])
    return None


def _str(v):
    if isinstance(v, str) and v.strip():
        return v.strip()
    if isinstance(v, dict):
        for k in ("name", "displayName", "abbreviation", "label", "shortName"):
            if isinstance(v.get(k), str) and v[k].strip():
                return v[k].strip()
    return None


def _first(d, keys, conv):
    for k in keys:
        if k in d:
            v = conv(d[k])
            if v is not None:
                return v
    return None


def _nested(d):
    for k in NEST_KEYS + ("pickableEntities", "entities", "participants", "players"):
        v = d.get(k)
        if isinstance(v, dict):
            yield v
        elif isinstance(v, list):
            for x in v[:1]:
                if isinstance(x, dict):
                    yield x


def _deep_first(d, keys, conv, depth=3):
    v = _first(d, keys, conv)
    if v is not None or depth == 0:
        return v
    for n in _nested(d):
        v = _deep_first(n, keys, conv, depth - 1)
        if v is not None:
            return v
    for k in ("team", "competitor", "pickableCompetitors", "competitors"):
        x = d.get(k)
        x = x[0] if isinstance(x, list) and x and isinstance(x[0], dict) else x
        if isinstance(x, dict):
            v = _first(x, keys, conv) or _deep_first(x, keys, conv, depth - 1)
            if v is not None:
                return v
    return None


def _market(v):
    s = _str(v)
    if not s:
        return None
    k = re.sub(r"\s+", " ", s.lower().replace("_", " ")).strip()
    return MARKETS.get(k) or ("other:" + k if len(k) <= 40 else None)


def _side_mults(d):
    mo, mu = _first(d, MORE_KEYS, _num), _first(d, LESS_KEYS, _num)
    for k in ("options", "selections", "outcomes", "pickOptions", "sides", "multipliers"):
        lst = d.get(k)
        if not isinstance(lst, list):
            continue
        for o in lst:
            if not isinstance(o, dict):
                continue
            side = (_str(o.get("side")) or _str(o.get("label")) or _str(o.get("name")) or _str(o.get("direction")) or "").lower()
            m = _first(o, ("multiplier", "payoutMultiplier", "boost", "value"), _num)
            if m is None:
                continue
            if side in ("more", "over", "higher"):
                mo = m
            elif side in ("less", "under", "lower"):
                mu = m
    return mo, mu


def _walk(node, out, seen):
    if isinstance(node, dict):
        if id(node) in seen:
            return
        seen.add(id(node))
        name = _deep_first(node, NAME_KEYS, _str, 2)
        line = _first(node, LINE_KEYS, _num)
        market = _deep_first(node, MARKET_KEYS, _market, 1)
        if name and line is not None and market and 0 <= line <= 80 and line * 2 == round(line * 2):
            mo, mu = _side_mults(node)
            team = _deep_first(node, TEAM_KEYS, lambda v: (s := _str(v)) and (s.upper() if 2 <= len(s) <= 4 else None))
            game = _deep_first(node, GAME_KEYS, lambda v: str(v) if isinstance(v, (int, str)) and str(v) else None, 2)
            start = _deep_first(node, START_KEYS, _str, 2)
            out.append({"name": name, "market": market, "line": line, "mo": mo, "mu": mu,
                        "team": players.team_code(team) if team else None, "pos": _deep_first(node, POS_KEYS, _str, 2),
                        "game_ref": game, "start": start})
        for v in node.values():
            _walk(v, out, seen)
    elif isinstance(node, list):
        for v in node:
            _walk(v, out, seen)


# ---------- the real format (Nov 2026): routes/_homeShared -> pickCardsResponse ----------
MORE_ID, LESS_ID = 1, 2          # pickSixMarketById[...]["propositionNameById"]: {"1": "More", "2": "Less"}


def _find_key(node, key, depth=0):
    if depth > 6:
        return None
    if isinstance(node, dict):
        if key in node and isinstance(node[key], dict):
            return node[key]
        for v in node.values():
            r = _find_key(v, key, depth + 1)
            if r is not None:
                return r
    elif isinstance(node, list):
        for v in node[:20]:
            r = _find_key(v, key, depth + 1)
            if r is not None:
                return r
    return None


def pick_cards(tree) -> tuple[list[dict], dict]:
    """Rows from Pick6's normalized pick cards: card -> entity (player) + competition (game, his team and
    position) + one row per active market line, with the More / Less multipliers. A side the line doesn't
    offer (alt lines are More only) gets multiplier 0 ("not offered"); paused lines are skipped."""
    pc = _find_key(tree, "pickCardsResponse")
    if not pc or "pickCardByPickableId" not in pc:
        return [], {}
    ents, comps = pc.get("entityInfoByDkId") or {}, pc.get("competitionById") or {}
    teams, mkts = pc.get("displayTeamById") or {}, pc.get("pickSixMarketById") or {}
    rows, info = [], {"category": pc.get("pickCategoryId"), "paused": 0,
                      "categories": {str(k): [x for x in (v.get("filterKey"), v.get("categoryName"), str(k)) if x]
                                     for k, v in (pc.get("pickCategoryById") or {}).items()}}
    for card in (pc.get("pickCardByPickableId") or {}).values():
        es = card.get("entities") or []
        if len(es) != 1:          # multi-player cards (matchups) are not single-player props
            continue
        dk = str(es[0].get("dkId")); ent = ents.get(dk) or ents.get(int(dk) if dk.isdigit() else dk) or {}
        comp = comps.get(str((es[0].get("compIds") or [None])[0])) or {}
        ec = (comp.get("entityCompByDkId") or {}).get(dk) or {}
        team = (teams.get(str(ec.get("teamId"))) or {}).get("name")
        for m in card.get("activePickableMarkets") or []:
            if m.get("isPaused"):
                info["paused"] += 1
                continue
            mk = _market((mkts.get(str(m.get("pickSixMarketId"))) or {}).get("name"))
            sel = {s.get("statLinePropositionId"): _num(s.get("standingsMultiplier")) for s in m.get("activeSelections") or []}
            if not sel or m.get("targetValue") is None:
                continue
            rows.append({"name": ent.get("fullName") or ent.get("name"), "market": mk, "line": float(m["targetValue"]),
                         "mo": sel.get(MORE_ID, 0.0), "mu": sel.get(LESS_ID, 0.0), "team": players.team_code(team) if team else None,
                         "pos": ec.get("position"), "game_ref": comp.get("compId"), "start": comp.get("startTime"),
                         "pick6_market": m.get("pickSixMarketId"), "live": bool(m.get("isLive"))})
    return rows, info


last_info: dict = {}


def extract(page: str) -> list[dict]:
    global last_info
    raw = []
    for tree in loader_data(page):
        rows, info = pick_cards(tree)
        if rows:
            raw += rows
            last_info = info
            continue
        _walk(tree, raw, set())
    # one row per player + market + line (the same prop can appear in several lists on the page)
    best = {}
    for r in raw:
        k = (players.fold(r["name"]), r["team"], r["market"], r["line"])
        score = sum(r.get(f) is not None for f in ("mo", "mu", "team", "game_ref", "start"))
        if k not in best or score > best[k][0]:
            best[k] = (score, r)
    return [r for _, r in best.values()]


def _game_for(r, slate):
    """Our game id for a row: the slate game with its team (and the start time when both teams play twice)."""
    if not r.get("team"):
        return None
    cands = [g for g in slate if r["team"] in (g["home"], g["away"])]
    if r.get("start") and len(cands) > 1:
        day = str(r["start"])[:10]
        cands = [g for g in cands if (g.get("start") or "")[:10] == day] or cands
    return cands[0] if len(cands) == 1 else (sorted(cands, key=lambda g: g.get("start") or "")[0] if cands else None)


def build_rows(page: str, slate: list[dict], R: players.Rosters, fetched_at: str, now: dt.datetime | None = None):
    """Board rows with every required field, and the drop counts by reason."""
    import slate as slate_mod
    rows, drops, n_raw, review = [], {}, 0, []
    for r in extract(page):
        n_raw += 1
        g = _game_for(r, slate)
        m = R.match(r["name"], r.get("team"), [g["home"], g["away"]] if g else None, r.get("pos"))
        row = {"name": r["name"], "player_id": m["player_id"], "team": m.get("team") or r.get("team"),
               "game": g["id"] if g else None, "date": g["date"] if g else None, "market": r["market"],
               "line": r["line"], "mo": r["mo"], "mu": r["mu"], "source": SOURCE, "fetched_at": fetched_at,
               "pos": m.get("pos") or r.get("pos")}
        missing = [f for f in REQUIRED if row.get(f) in (None, "")]
        if m["status"] != "MATCHED":
            why = "unmatched player"
            review.append({"name": r["name"], "team": r.get("team"), "market": r["market"], "line": r["line"],
                           "reason": m.get("reason") or "unmatched"})
        elif missing:
            why = "missing " + ", ".join(missing)
        elif g and slate_mod.started(g, now):
            why = "game started"
        else:
            rows.append(row)
            continue
        drops[why] = drops.get(why, 0) + 1
    return rows, {"raw": n_raw, "kept": len(rows), "dropped": drops, "review": review[:100]}


FAILED = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "pick6_failed.html")


def save_failed(page: str, limit: int = 3_000_000):
    """Keep the page that parsed to 0 rows (its scripts, where the loader data lives) so the parser can be
    fixed against the real format. Overwritten each time; removed once a parse succeeds."""
    scripts = re.findall(r"<script[^>]*>.*?</script>", page, re.S)
    body = "\n".join(scripts) if scripts else page
    try:
        with open(FAILED, "w", encoding="utf-8") as f:
            f.write(body[:limit])
    except OSError:
        pass


def _pull(slate: list[dict], R: players.Rosters, timeout: int = 30):
    """(rows, stats). Never raises; `status` is "ok", "parse failed: 0 rows", "blocked (HTTP 403)", etc."""
    global status, stats
    fetched_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    def get(url):
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", "replace")
    try:
        page = get(URL)
    except urllib.error.HTTPError as e:
        status, stats = (f"blocked (HTTP {e.code})" if e.code in (401, 403) else f"HTTP {e.code}"), {}
        print(f"  [pick6] {status}")
        return [], stats
    except Exception as e:
        status, stats = f"unavailable ({e})", {}
        print(f"  [pick6] {status}")
        return [], stats
    # The page serves one category (Shots on Goal). Its other categories (Points, Assists, ...) load client-side:
    # ?category=<filterKey | name | id> all returned Shots on Goal again on 2026-11-03, so only this page is
    # pulled; points and saves come from DraftKings (or your pasted board) until a working source is found.
    pages = [page]
    rows, stats, seen = [], {"raw": 0, "kept": 0, "dropped": {}}, set()
    for pg in pages:
        r_, st = build_rows(pg, slate, R, fetched_at)
        for r in r_:
            k = (r["player_id"], r["market"], r["line"])
            if k not in seen:
                seen.add(k); rows.append(r)
        stats["raw"] += st["raw"]
        stats.setdefault("review", []).extend(st.get("review") or [])
        for k, v in st["dropped"].items():
            stats["dropped"][k] = stats["dropped"].get(k, 0) + v
    stats["kept"] = len(rows)
    stats["category"] = last_info.get("category")
    stats["bytes"] = len(page)
    status = "ok" if rows else ("parse failed: 0 rows" if not stats["raw"] else "0 usable rows")
    if not stats["raw"]:
        save_failed(page)
    if rows and os.path.exists(FAILED):
        os.remove(FAILED)
    print(f"  [pick6] {status}: {stats}")
    return rows, stats


# ---------- the day's board: lines an earlier pull saw that this pull's page does not show ----------
REUSE_MAX_H = 12.0                       # an earlier pull's line is kept at most this long


def day_path() -> str:
    """model/data/pick6_day.json: beside the last-good-board cache (tests point CACHE at a temp directory)."""
    return os.path.join(os.path.dirname(CACHE), "pick6_day.json")

KEEP_MARKETS = ("sog", "points", "saves")


def category_name(info: dict) -> str | None:
    """The name of the category the page served ("Shots On Goal", "Points", ...), or None for its mixed landing page."""
    names = (info.get("categories") or {}).get(str(info.get("category"))) or []
    return next((n for n in names[1:2] if n), names[0] if names else None)


def full_markets(rows: list[dict], info: dict) -> set:
    """Markets this pull lists in full. The page serves one category per request: a stat's own category (Shots On
    Goal) lists every player's lines for it; the mixed landing page lists a handful of featured players across
    stats, so it is complete for none."""
    for n in (info.get("categories") or {}).get(str(info.get("category"))) or []:
        mk = MARKETS.get(str(n).lower().replace("-", " ").strip())
        if mk and rows and sum(r["market"] == mk for r in rows) >= 0.9 * len(rows):
            return {mk}
    return set()


def merge_day(rows: list[dict], info: dict, slate: list[dict], now: dt.datetime | None = None, path: str | None = None):
    """(rows + the earlier lines worth keeping, stats). A featured-picks pull says nothing about the players it
    leaves out (on 2026-11-10 the page went from 105 shooters to 7 between two builds), so the lines an earlier
    pull today saw for them are kept with their own fetch time and reused=True: shown with their age, never a
    play or a lean (props_board._cached_reason). A stat's full category replaces everything known about that stat,
    and a player's card replaces his own lines in that stat. Kept at most REUSE_MAX_H hours, for games that are
    still on the slate and have not started."""
    import slate as slate_mod
    now = now or dt.datetime.now(dt.timezone.utc)
    path = path or day_path()
    try:
        with open(path) as f:
            old = json.load(f)["rows"]
    except (OSError, ValueError, KeyError, TypeError):
        old = []
    full = full_markets(rows, info)
    have = {(r["player_id"], r["market"]) for r in rows}
    games = {g["id"]: g for g in slate}
    keep = []
    for r in old:
        g = games.get(r.get("game"))
        if r.get("market") not in KEEP_MARKETS or r["market"] in full or (r.get("player_id"), r["market"]) in have \
                or g is None or slate_mod.started(g, now):
            continue
        try:
            age_h = (now - dt.datetime.fromisoformat(r["fetched_at"])).total_seconds() / 3600
        except (KeyError, TypeError, ValueError):
            continue
        if 0 <= age_h <= REUSE_MAX_H:
            keep.append({k: v for k, v in r.items() if k != "reused"})
    try:
        with open(path, "w") as f:
            json.dump({"rows": [r for r in rows if r["market"] in KEEP_MARKETS] + keep}, f, separators=(",", ":"))
    except OSError:
        pass
    return rows + [{**r, "reused": True} for r in keep], {"category_name": category_name(info), "full": sorted(full), "reused": len(keep)}


CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "pick6_cache.json")
fetch_status = "not run"     # "fresh" | "fallback" (last good board reused because this pull failed) | "error"
fetched_at: str | None = None  # when the rows in use were really pulled


def fetch(slate: list[dict], R: players.Rosters, timeout: int = 30, now: dt.datetime | None = None):
    """Every build pulls the board fresh (_pull). If the pull fails (blocked, unreachable, 0 usable rows), the
    last good board in model/data/pick6_cache.json is reused with its ORIGINAL fetched_at and fetch_status
    "fallback" (started games are dropped downstream). `status` keeps the existing failure text for the banner."""
    global fetch_status, fetched_at
    rows, st = _pull(slate, R, timeout)
    if rows:
        fetch_status, fetched_at = "fresh", rows[0]["fetched_at"]
        try:
            with open(CACHE, "w") as f:
                json.dump({"at": fetched_at, "rows": rows}, f, separators=(",", ":"))
        except OSError:
            pass
        rows, day = merge_day(rows, dict(last_info), slate, now)
        if day["reused"]:
            print(f"  [pick6] page served {day['category_name'] or 'its featured picks'} only; kept {day['reused']} lines an earlier pull saw (marked reused)")
        return rows, {**st, **day}
    try:
        with open(CACHE) as f:
            c = json.load(f)
        c_at, c_rows = c["at"], c["rows"]
    except (OSError, ValueError, KeyError, TypeError):
        fetch_status, fetched_at = "error", None
        return rows, st
    games = {g["id"] for g in slate}
    keep = [{**r, "fetched_at": r.get("fetched_at") or c_at} for r in c_rows if r.get("game") in games]
    # ... plus the day's other lines (merge_day with nothing new: every line it still holds, each with its own time)
    seen = {(r["player_id"], r["market"], r["line"]) for r in keep}
    keep += [r for r in merge_day([], {}, slate, now)[0] if (r["player_id"], r["market"], r["line"]) not in seen]
    fetch_status, fetched_at = "fallback", c_at
    print(f"  [pick6] pull failed ({status}); FALLBACK to the last good board from {c_at}: {len(keep)} rows")
    return keep, {**st, "fallback_rows": len(keep)}


import urllib.error  # noqa: E402  (used in fetch)
