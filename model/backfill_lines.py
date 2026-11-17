"""Rebuild the line log (model/data/lines/<day>.csv) for the days before it went live, from the pulls in git history.

Every build commits model/data/odds_cache.json (The Odds API's last fresh pull: DraftKings, PrizePicks from 2026-11-07,
the other books from 11-08; rewritten only by a fresh pull) and model/data/pick6_cache.json (Pick6's last fresh pull,
from 11-05). Replaying each distinct pull in time order through linemoves.record writes the rows the live log would
have written: every return to an earlier line and every take-down (on the same proof: the pull carried that source's
lines for the game), which the price logs (dk_prices.csv / book_prices.csv) cannot show.

* Pick6 take-downs are not rebuilt: whether its page listed a market in full is not in the cache.
* The cache keeps DraftKings' saves rows without the goalie's id: matched by name (the same pull's other books and
  PrizePicks first, then the names that have only ever had one id in the price and leg logs).
* A pull that fell back (DraftKings had nothing) was never cached, so the other books' overnight lines from those
  builds are missing here; the live log keeps them (odds.pulled).
* Days already in the log are never touched. Days before the caches start come from the price logs
  (linemoves.backfill_day: DraftKings, every market).

Offline only (the build's checkout is shallow). From the repo root:
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


def _git(*args) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout


def pulls(ref: str):
    """(time, kind, cache) for every distinct cached pull reachable from `ref`, oldest first."""
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
        out.append((at, kind, c))
    out.sort(key=lambda x: (dt.datetime.fromisoformat(x[0]), x[1]))
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
    for at, kind, c in items:
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
        n += lm.record(obs, lm.covered(obs), now=now, base=base)
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", default="origin/main")
    ap.add_argument("--until", default=None, help="last game day to write (default: every day the history has)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    items = pulls(a.ref)
    print(f"{len(items)} cached pulls ({sum(k == 'odds' for _, k, _ in items)} Odds API, "
          f"{sum(k == 'pick6' for _, k, _ in items)} Pick6), {items[0][0] if items else '-'} to {items[-1][0] if items else '-'}")
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
        written = []
        for d in sorted(early + days):
            if a.until and d > a.until:
                continue
            dst = lm.path(d)
            if os.path.exists(dst):
                continue                             # the live log's own day: never touched
            if not a.dry_run:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy(lm.path(d, tmp), dst)
            written.append(d)
        print(f"replayed {rows} rows; {'would write' if a.dry_run else 'wrote'} {len(written)} days "
              f"({written[0] if written else '-'} to {written[-1] if written else '-'}) into {lm.DIR}")
    finally:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    main()
