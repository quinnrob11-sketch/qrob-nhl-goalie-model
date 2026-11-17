"""Rebuild the line log (model/data/lines/<day>.csv) from the pulls in git history: the days before it went live, and
any day the builds missed pulls for.

Every build commits model/data/odds_cache.json (The Odds API's last fresh pull: DraftKings, PrizePicks from 2026-11-07,
the other books from 11-08; rewritten only by a fresh pull) and model/data/pick6_cache.json (Pick6's last fresh pull,
from 11-05), with index.html built from them. Replaying each distinct pull in time order through linemoves.record
writes the rows the live log would have written: every return to an earlier line and every take-down (on the same
proof: the pull carried that source's lines for the game, and for Pick6 a market its page listed in full, as that
build's page says), which the price logs (dk_prices.csv / book_prices.csv) cannot show.

* The cache keeps DraftKings' saves rows without the goalie's id: matched by name (the same pull's other books and
  PrizePicks first, then the names that have only ever had one id in the price and leg logs).
* A pull that fell back (DraftKings had nothing) was never cached, so the other books' overnight lines from those
  builds are missing here; the live log keeps them (odds.pulled).
* A day that already has a log is MERGED with the replay (linemoves.merge): in time order, a row kept only when it
  changes its prop, so the rows only the builds saw stay and the replay adds what they missed (the pulls before the
  log went live, or a build whose logging failed). Days before the caches start come from the price logs
  (linemoves.backfill_day: DraftKings, every market).

Needs the full cache history: in a shallow clone it stops (git fetch --unshallow origin first). From the repo root:
    python model/backfill_lines.py [--ref origin/main] [--until 2026-11-17] [--dry-run]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import tempfile

import linemoves as lm

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ODDS = "model/data/odds_cache.json"
PICK6 = "model/data/pick6_cache.json"
PAGE = "index.html"


def _git(*args) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout


def _cut(ref: str) -> str | None:
    """The shallow boundary the cache history stops at (its oldest commit is one), or None when it is whole."""
    p = _git("rev-parse", "--git-path", "shallow").strip()
    p = p if os.path.isabs(p) else os.path.join(ROOT, p)
    if not os.path.exists(p):
        return None
    with open(p) as f:
        cut = set(f.read().split())
    first = _git("log", "--reverse", "--format=%H", ref, "--", ODDS, PICK6).split()[:1]
    return first[0] if first and first[0] in cut else None


def pick6_full_of(page: str) -> list:
    """The markets Pick6's page listed in full, from a built page's data (pick6_stats.full; none before 11-10)."""
    i = page.find('"pick6_stats":')
    if i < 0:
        return []
    try:
        st, _ = json.JSONDecoder().raw_decode(page, i + len('"pick6_stats":'))
    except ValueError:
        return []
    return [m for m in (st.get("full") or []) if isinstance(m, str)] if isinstance(st, dict) else []


def _pick6_full(sha: str) -> list:
    """pick6_full_of the page built with the pull `sha` committed (the same build wrote both)."""
    try:
        return pick6_full_of(_git("show", f"{sha}:{PAGE}"))
    except subprocess.CalledProcessError:
        return []


def pulls(ref: str):
    """(time, kind, cache, pick6 full markets) for every distinct cached pull reachable from `ref`, oldest first."""
    log = _git("log", "--reverse", "--format=@%H", "--name-only", ref, "--", ODDS, PICK6)
    seen, out = set(), []
    sha = None
    for line in log.splitlines():
        if line.startswith("@"):
            sha = line[1:]
            continue
        if line not in (ODDS, PICK6):
            continue
        try:
            c = json.loads(_git("show", f"{sha}:{line}"))
        except (subprocess.CalledProcessError, ValueError):
            continue
        at = c.get("at")
        kind = "odds" if line == ODDS else "pick6"
        if not at or (kind, at) in seen:
            continue
        seen.add((kind, at))
        out.append((at, kind, c, _pick6_full(sha) if kind == "pick6" else ()))
    out.sort(key=lambda x: (lm._epoch(x[0]), x[1]))
    return out


def _ids_by_name():
    """Names that have only ever had one player id in the price and leg logs (linemoves._price_history's rule)."""
    import pandas as pd
    frames = []
    if os.path.exists(lm.BOOK_PRICES):
        frames.append(pd.read_csv(lm.BOOK_PRICES, usecols=["name", "player_id"]))
    if os.path.exists(lm.LEGS):
        frames.append(pd.read_csv(lm.LEGS, usecols=["name", "player_id"]))
    if not frames:
        return {}
    x = pd.concat(frames).dropna().drop_duplicates()
    one = x.groupby("name").player_id.nunique()
    x = x[x.name.isin(one[one == 1].index)].drop_duplicates("name")
    return {n: int(p) for n, p in zip(x.name, x.player_id)}


def replay(items, base: str, names: dict | None = None) -> int:
    """Every pull through linemoves.record into `base`, as the live build would have logged it."""
    names = dict(names or {})
    teams_of = {}                                    # (day, team) -> "AWY/HOM", from the odds pulls (Pick6 rows carry a game id only)
    n = 0
    for item in items:
        at, kind, c = item[:3]
        full = item[3] if len(item) > 3 else ()
        now = dt.datetime.fromisoformat(at)
        if kind == "odds":
            matched = lambda rs: [r for r in rs or [] if r.get("match") == "MATCHED"]
            books, pp = matched(c.get("books")), matched(c.get("pp"))
            for r in books + pp + matched(c.get("sog")) + matched(c.get("points")):
                if r.get("player_id") is not None:
                    names.setdefault(r["name"], int(r["player_id"]))
                for t in r.get("teams") or []:
                    teams_of[(r.get("date"), t)] = "/".join(r["teams"])
            own = {r["name"]: (int(r["player_id"]), r.get("team")) for r in books + pp
                   if r.get("market") == "saves" and r.get("player_id") is not None}
            saves = []
            for r in c.get("saves") or []:
                pid, team = own.get(r["name"], (names.get(r["name"]), None))
                saves.append({**r, "player_id": pid, "goalie_id": pid, "team": team or r.get("team") or ""})
            obs = lm.observations([], at, dk_saves=saves, dk_sog=c.get("sog"), dk_points=c.get("points"), books=books, pp=pp)
        else:
            rows = [{**r, "teams": teams_of.get((r.get("date"), r.get("team")), "")} for r in c.get("rows") or []]
            obs = lm.observations([], at, pick6=rows)
        n += lm.record(obs, lm.covered(obs, full), now=now, base=base)
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", default="origin/main")
    ap.add_argument("--until", default=None, help="last game day to write (default: every day the history has)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    c = _cut(a.ref)
    if c:
        raise SystemExit(f"the cache history is cut at {c[:8]} (a shallow clone): run `git fetch --unshallow origin` "
                         f"(or --shallow-since=2026-11-02) and try again")
    items = pulls(a.ref)
    print(f"{len(items)} cached pulls ({sum(x[1] == 'odds' for x in items)} Odds API, "
          f"{sum(x[1] == 'pick6' for x in items)} Pick6), {items[0][0] if items else '-'} to {items[-1][0] if items else '-'}")
    tmp = tempfile.mkdtemp()
    try:
        rows = replay(items, tmp, _ids_by_name())
        days = sorted(f[:-4] for f in os.listdir(tmp) if f.endswith(".csv"))
        first = days[0] if days else None
        # days before the caches start: DraftKings from the price log
        al = lm._price_history()
        early = sorted(d for d in set(al.date) if first and d < first) if al is not None else []
        for d in early:
            lm.backfill_day(d, al, base=tmp)
        wrote, merged, same = [], [], []
        for d in sorted(early + days):
            if a.until and d > a.until:
                continue
            new = lm.read(d, tmp)
            if os.path.exists(lm.path(d)):
                old = lm.read(d)
                out = lm.merge(old, new)             # the builds' own rows first: a pull both saw keeps its logged row
                if [tuple(r.get(k) or "" for k in lm.COLS) for r in out] == [tuple(r.get(k) or "" for k in lm.COLS) for r in old]:
                    same.append(d)
                    continue
                merged.append(f"{d} (+{len(out) - len(old)} rows; first row {old[0]['snap'] if old else '-'} -> {out[0]['snap'] if out else '-'})")
            else:
                out = lm.merge(new)
                wrote.append(d)
            if not a.dry_run:
                lm.write(d, out)
        verb = "would write" if a.dry_run else "wrote"
        print(f"replayed {rows} rows; {verb} {len(wrote)} new days ({wrote[0] if wrote else '-'} to {wrote[-1] if wrote else '-'}), "
              f"merged {len(merged)}, {len(same)} already complete, into {lm.DIR}")
        for m in merged:
            print(f"  merged {m}")
    finally:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    main()
