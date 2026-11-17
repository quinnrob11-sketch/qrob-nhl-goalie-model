"""Opening lines and line movement: model/data/lines/<game day>.csv.

Every build pulls each source fresh (DraftKings and the other sportsbooks through The Odds API, PrizePicks, Pick6)
about every 15 minutes through board hours. A prop -- one game day, market, player and source -- gets a row here
only when its line or price changed since its last row, or it came off the board. So a prop's first row is its
OPENING line (the first line a build saw), and its last row before puck drop is its CLOSING line.

* Only fresh pulls are recorded. A pull served from a cache (status "fallback") and a Pick6 line kept from an
  earlier pull (reused) are old news: never written again as a new observation.
* Saves (the goalies) keep every price move; the skaters' props (shots, points) a row only when the LINE moves:
  their prices move on almost every pull (58% of the rows when every move was kept) and are all in the price logs.
* One line per prop. When a source lists several at once (sportsbook alternates, the Pick6 ladder), its MAIN line
  is kept: the line priced nearest even at a sportsbook, the line Pick6 takes both ways (More and Less) on,
  PrizePicks' standard line (never a demon or goblin).
* Off the board: a prop missing from a pull is written with an empty line only when the same pull carries that
  source's lines for the same game and market (a failed request for one game is never read as every line in it
  coming down), and, for Pick6, only for a market its page listed in full.

dk_prices.csv / book_prices.csv (prices.py) keep every price of every line for grading; this log keeps the story of
each prop for the page. Days before this log were rebuilt from those two files (`python model/linemoves.py
--backfill`): DraftKings in every market and the other books' saves lines, which post one line per player at a time;
those days carry no off-the-board rows, and a line that went back to an earlier line at the same price is missing.
"""
from __future__ import annotations

import csv
import datetime as dt
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
DIR = os.path.join(HERE, "data", "lines")
COLS = ["snap", "market", "source", "player_id", "name", "team", "teams", "line", "over", "under", "mo", "mu"]
APPS = ("PrizePicks", "Pick6")          # pick'em apps: multipliers (mo / mu), not American odds
FLICKER_MIN = 20                       # an off-the-board spell this short that comes back unchanged is a feed blip
PRICED = ("saves",)                    # markets whose every price move is a move; elsewhere only the line is


def path(day: str, base: str | None = None) -> str:
    return os.path.join(base or DIR, f"{day}.csv")


def _num(x):
    """'' / None / nan -> None; numbers (or numeric strings) -> float."""
    if x is None or x == "":
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) else v


def _pid(x):
    v = _num(x)
    return None if v is None else int(v)


def norm_name(name) -> str:
    return " ".join(str(name or "").lower().replace(".", " ").replace("-", " ").replace("'", "").split())


def key_of(r: dict) -> tuple:
    """(market, source, player): the player id when known, else his name."""
    pid = _pid(r.get("player_id"))
    return (r["market"], r["source"], pid if pid is not None else "n:" + norm_name(r.get("name")))


def state_of(r: dict) -> tuple:
    """What a move is: the line and (saves) its price, both sides. An empty line is off the board."""
    if r.get("market") in PRICED:
        return tuple(_num(r.get(c)) for c in ("line", "over", "under", "mo", "mu"))
    return (_num(r.get("line")),)


def _novig_over(over, under):
    """The over's no-vig probability from two American prices (None when a side is missing)."""
    def imp(a):
        a = _num(a)
        if a is None or a == 0:
            return None
        return 100 / (a + 100) if a > 0 else -a / (-a + 100)
    po, pu = imp(over), imp(under)
    return None if po is None or pu is None or po + pu <= 0 else po / (po + pu)


def main_line(rows: list[dict]) -> dict | None:
    """The one line a source is really dealing for a prop when it lists several at once (see the module notes)."""
    if not rows:
        return None
    if len(rows) == 1:
        return rows[0]
    def score(r):
        p = _novig_over(r.get("over"), r.get("under"))
        if p is not None:
            return abs(p - 0.5)
        mo, mu = _num(r.get("mo")), _num(r.get("mu"))
        if mo and mu:
            return abs(mo - mu)
        return 9.0
    return min(rows, key=lambda r: (score(r), _num(r.get("line")) or 0.0))


# ---------- observations: one per prop and pull, from each source's rows ----------

def _teams_of(r: dict, games: dict) -> str:
    t = r.get("teams")
    if isinstance(t, (list, tuple)):
        return "/".join(t)
    if t:
        return str(t)
    g = games.get(r.get("game"))
    return f"{g['away']}/{g['home']}" if g else ""


def _obs(r: dict, source: str, market: str, games: dict, snap: str | None, mo=None, mu=None, priced=True) -> dict:
    return {"day": r.get("date"), "snap": r.get("fetched_at") or snap, "market": market, "source": source,
            "player_id": _pid(r.get("player_id") if r.get("player_id") is not None else r.get("goalie_id")),
            "name": r.get("name"), "team": r.get("team") or "", "teams": _teams_of(r, games),
            "line": _num(r.get("line")), "over": _num(r.get("over")) if priced else None,
            "under": _num(r.get("under")) if priced else None, "mo": mo, "mu": mu}


def observations(slate: list[dict], snap: str | None = None, dk_saves=None, dk_sog=None, dk_points=None,
                 books=None, pp=None, pick6=None) -> list[dict]:
    """Every source's rows from THIS build's fresh pulls (the caller passes None for a source whose pull was not
    fresh) as observations: day, snap, market, source, player, line, prices."""
    games = {g["id"]: g for g in slate or []}
    out = []
    for rows, market in ((dk_saves, "saves"), (dk_sog, "sog"), (dk_points, "points")):
        out += [_obs(r, "DraftKings", market, games, snap) for r in rows or [] if r.get("line") is not None]
    for r in books or []:
        if r.get("line") is None or r.get("over") is None or r.get("under") is None:
            continue
        out.append(_obs(r, r.get("book") or r.get("source"), r["market"], games, snap))
    for r in pp or []:
        if r.get("alt") or r.get("line") is None:
            continue                     # demons and goblins are not the line PrizePicks is dealing
        # a board row carries its multipliers; a raw Odds API row its two sides (a side not listed is not offered)
        mo = _num(r.get("mo")) if "mo" in r else (1.0 if r.get("over") is not None else 0.0)
        mu = _num(r.get("mu")) if "mu" in r else (1.0 if r.get("under") is not None else 0.0)
        out.append(_obs(r, "PrizePicks", r["market"], games, snap, mo=mo, mu=mu, priced=False))
    for r in pick6 or []:
        if r.get("reused") or r.get("line") is None:
            continue                     # kept from an earlier pull: not seen again now
        promo = r.get("promo")
        mo = _num(r.get("mo_reg")) if promo else _num(r.get("mo"))
        mu = _num(r.get("mu_reg")) if promo else _num(r.get("mu"))
        if promo and r.get("mo_reg") is None and r.get("mu_reg") is None:
            continue                     # a promo card alone (no ordinary card at that line)
        if not (mo and mu):
            continue                     # the Pick6 ladder: only the line it takes both ways on is its main line
        out.append(_obs(r, "Pick6", r["market"], games, snap, mo=mo, mu=mu, priced=False))
    return [o for o in out if o["day"] and o["market"]]


def covered(obs: list[dict], pick6_full=()) -> set:
    """(day, source, market, teams) this pull saw lines for: a prop of that day, source, market and game that is
    missing from the pull is off the board. Pick6 counts only for a market its page served in full (a featured-picks
    page says nothing about the players it leaves out)."""
    out = set()
    for o in obs:
        if o["source"] == "Pick6" and o["market"] not in set(pick6_full or ()):
            continue
        if o["teams"]:
            out.add((o["day"], o["source"], o["market"], o["teams"]))
    return out


# ---------- the log ----------

def read(day: str, base: str | None = None) -> list[dict]:
    p = path(day, base)
    if not os.path.exists(p):
        return []
    with open(p, newline="") as f:
        rows = list(csv.DictReader(f))
    for i, r in enumerate(rows):
        r["_i"] = i
    return rows


def last_states(rows: list[dict]) -> dict:
    """Each prop's latest row (by snap, then file order)."""
    out = {}
    for r in sorted(rows, key=lambda r: (r.get("snap") or "", r.get("_i", 0))):
        out[key_of(r)] = r
    return out


def _fmt(v):
    if v is None:
        return ""
    return f"{v:g}" if isinstance(v, float) else str(v)


def record(obs: list[dict], cover: set | None = None, now: dt.datetime | None = None, base: str | None = None) -> int:
    """Append each prop whose main line or price changed since its last row (its first row is its opening line),
    and each prop that came off the board (see the module notes). Returns the rows written."""
    now = now or dt.datetime.now(dt.timezone.utc)
    cover = cover or set()
    by_day: dict = {}
    for o in obs:
        by_day.setdefault(o["day"], {}).setdefault(key_of(o), []).append(o)
    snap_now = now.isoformat(timespec="seconds")
    snap_of = {}
    for o in obs:
        snap_of.setdefault((o["day"], o["source"], o["market"], o["teams"]), o["snap"] or snap_now)
    days = set(by_day)
    written = 0
    for day in sorted(days):
        seen = by_day.get(day, {})
        last = last_states(read(day, base))
        new = []
        for k, rows in seen.items():
            o = main_line(rows)
            prev = last.get(k)
            if prev is not None and (prev.get("snap") or "") >= (o["snap"] or ""):
                continue                 # not newer than what is stored (a pull read twice)
            if prev is None or state_of(prev) != state_of(o):
                new.append({c: o.get(c) for c in COLS})
        for k, prev in last.items():
            if k in seen or _num(prev.get("line")) is None:
                continue
            c = (day, prev["source"], prev["market"], prev.get("teams") or "")
            if c in cover:
                new.append({**{c_: prev.get(c_) for c_ in ("market", "source", "player_id", "name", "team", "teams")},
                            "snap": snap_of.get(c, snap_now), "line": None, "over": None, "under": None, "mo": None, "mu": None})
        if not new:
            continue
        p = path(day, base)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        fresh = not os.path.exists(p)
        with open(p, "a", newline="") as f:
            w = csv.writer(f)
            if fresh:
                w.writerow(COLS)
            for r in sorted(new, key=lambda r: (str(r["snap"]), r["market"], str(r["source"]), str(r["name"]))):
                w.writerow([_fmt(r.get(c)) for c in COLS])
        written += len(new)
    return written


# ---------- for the page ----------

def _minutes(snap: str) -> int | None:
    try:
        return int(dt.datetime.fromisoformat(str(snap).replace("Z", "+00:00")).timestamp() // 60)
    except (TypeError, ValueError):
        return None


def history(day: str, base: str | None = None) -> dict:
    """{prop key: [row, ...]} in time order, with an off-the-board blip (shorter than FLICKER_MIN, back on the very
    same line and price) and any repeated state removed."""
    by = {}
    for r in sorted(read(day, base), key=lambda r: (r.get("snap") or "", r.get("_i", 0))):
        by.setdefault(key_of(r), []).append(r)
    out = {}
    for k, rs in by.items():
        seq = []
        for r in rs:
            if seq and state_of(seq[-1]) == state_of(r):
                continue
            if len(seq) >= 2 and _num(seq[-1].get("line")) is None and state_of(seq[-2]) == state_of(r):
                t_off, t_back = _minutes(seq[-1]["snap"]), _minutes(r["snap"])
                if t_off is not None and t_back is not None and t_back - t_off < FLICKER_MIN:
                    seq.pop()            # off for a moment, back exactly as before: one unbroken spell
                    continue
            seq.append(r)
        out[k] = seq
    return out


def for_page(days, base: str | None = None, all_markets=("saves",)) -> dict:
    """The page's line movement: {"<day>|<market>|<player id or n:name>": {"<source>": [[minute, line, a, b], ...]}}
    with minute = minutes since 1970 (UTC), line None = off the board, a / b = over / under American odds at a
    sportsbook, More / Less multipliers on an app. Every prop of `all_markets` (the goalies' saves lines, every
    price); another prop only when its LINE moved or it came off the board: skater prices move on nearly every pull
    (436 of 481 DraftKings props on 2026-11-14, against 33 line moves), which would add hundreds of KB to a page
    every phone reloads, so price-only moves stay in the log."""
    out = {}
    for day in days:
        for (market, source, who), seq in history(day, base).items():
            if market not in all_markets and len({_num(r.get("line")) for r in seq}) < 2:
                continue
            app = source in APPS
            pts = []
            for r in seq:
                t = _minutes(r["snap"])
                if t is None:
                    continue
                a, b = (_num(r.get("mo")), _num(r.get("mu"))) if app else (_num(r.get("over")), _num(r.get("under")))
                pts.append([t, _num(r.get("line")), a if not app or a is None else round(a, 2),
                            b if not app or b is None else round(b, 2)])
            if pts:
                out.setdefault(f"{day}|{market}|{who}", {})[source] = [[p[0], p[1],
                                                                       None if p[2] is None else (int(p[2]) if not app else p[2]),
                                                                       None if p[3] is None else (int(p[3]) if not app else p[3])] for p in pts]
    return out


# ---------- days before this log: rebuilt from the price history ----------

PRICES = os.path.join(HERE, "data", "dk_prices.csv")
BOOK_PRICES = os.path.join(HERE, "data", "book_prices.csv")
LEGS = os.path.join(HERE, "data", "legs.csv")


def _price_history(days=None):
    """DraftKings (every market) and the other books' saves lines from the price history, with player ids by name
    (DraftKings' rows carry none: taken from the books' and the leg log's rows, where a name has only ever had one)."""
    import pandas as pd
    frames = []
    if os.path.exists(PRICES):
        dk = pd.read_csv(PRICES)
        frames.append(dk.assign(source="DraftKings"))
    if os.path.exists(BOOK_PRICES):
        bk = pd.read_csv(BOOK_PRICES)
        ids = [bk[["name", "player_id"]]]
        frames.append(bk[bk.market == "saves"].assign(source=lambda x: x.book))
    else:
        ids = []
    if not frames:
        return None
    if os.path.exists(LEGS):
        ids.append(pd.read_csv(LEGS, usecols=["name", "player_id"]))
    al = pd.concat(frames, ignore_index=True)
    if days is not None:
        al = al[al.date.isin(list(days))]
    if ids:
        idf = pd.concat(ids).dropna().drop_duplicates()
        one = idf.groupby("name").player_id.nunique()
        idf = idf[idf.name.isin(one[one == 1].index)].drop_duplicates("name").set_index("name").player_id
        have = al["player_id"] if "player_id" in al else pd.Series(index=al.index, dtype=float)
        al["player_id"] = have.fillna(al.name.map(idf))
    al["_o"] = range(len(al))
    return al


def backfill_day(day: str, al, base: str | None = None) -> int:
    """Write `day`'s log from the price history `al` (_price_history): each prop's rows in time order, a row only
    when its line or price changed. Never touches a day that already has a log."""
    p = path(day, base)
    if os.path.exists(p):
        return 0
    x = al[al.date == day]
    if not len(x):
        return 0
    out = []
    for (market, source, name), g in x.sort_values(["snap", "_o"]).groupby(["market", "source", "name"], sort=False):
        prev = None
        for r in g.itertuples(index=False):
            team = getattr(r, "team", "")
            row = {"snap": r.snap, "market": market, "source": source, "player_id": _pid(getattr(r, "player_id", None)),
                   "name": name, "team": "" if team is None or (isinstance(team, float) and math.isnan(team)) else team,
                   "teams": r.teams if isinstance(r.teams, str) else "", "line": _num(r.line), "over": _num(r.over),
                   "under": _num(r.under), "mo": None, "mu": None}
            if prev is None or state_of(prev) != state_of(row):
                out.append(row)
                prev = row
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(COLS)
        for r in sorted(out, key=lambda r: (str(r["snap"]), r["market"], r["source"], str(r["name"]))):
            w.writerow([_fmt(r.get(c)) for c in COLS])
    return len(out)


def ensure(days, before: str | None = None, now: dt.datetime | None = None, base: str | None = None) -> dict:
    """Before a build records its pulls: a day on the page that has no log yet but whose lines the price history
    already holds from EARLIER pulls (taken before `before`, this build's pull time: the first build after this log
    went live) is rebuilt from that history, so its opening lines are the real ones and not this build's. A day
    first seen by this very pull starts its log from the pull itself."""
    now = now or dt.datetime.now(dt.timezone.utc)
    todo = [d for d in days if d and not os.path.exists(path(d, base))]
    if not todo:
        return {}
    al = _price_history(todo)
    if al is None or not len(al):
        return {}
    cut = before or (now - dt.timedelta(minutes=1)).isoformat(timespec="seconds")
    out = {}
    for d in todo:
        x = al[al.date == d]
        if len(x) and str(x.snap.min()) < cut:
            out[d] = backfill_day(d, x, base)
    return out


if __name__ == "__main__":
    import sys
    if "--backfill" in sys.argv:
        # every day before today (Central) that has no log yet; today and later are left to the next build (ensure)
        import zoneinfo
        today = dt.datetime.now(zoneinfo.ZoneInfo("America/Chicago")).date().isoformat()
        al = _price_history()
        n = {d: backfill_day(d, al) for d in sorted(set(al.date)) if d < today}
        print(f"backfilled {sum(1 for v in n.values() if v)} days, {sum(n.values())} rows into {DIR}")
