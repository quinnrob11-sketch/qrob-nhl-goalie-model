"""MoneyPuck team data (moneypuck.com, credited to MoneyPuck.com): goalie and team season summaries
and every team's game-by-game log, cached in model/data/moneypuck/ (gzipped CSV, team_games_*.csv.gz).

The saves model's shots-against term uses the score-adjusted unblocked attempts (Fenwick) from these
logs (with_attempts; engine.mp_mode). moneypuck.py is the separate goalie game-log cross-check that
stops the build when MoneyPuck and the NHL box scores disagree. Fetched at most once every MAX_AGE_H
hours in its own capped workflow step; each file is best-effort and `status` lists what came back.

    python model/moneypuck_teams.py          # refresh the cache now (--force ignores the cache age)
"""
from __future__ import annotations

import datetime as dt
import gzip
import io
import json
import os
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DIR = os.path.join(HERE, "data", "moneypuck")
BASE = "https://moneypuck.com/moneypuck/playerData"
HEADERS = {"User-Agent": "Mozilla/5.0 (qrob goalie model; personal, non-commercial)", "Accept": "text/csv,*/*"}
MAX_AGE_H = 20.0
# MoneyPuck used dotted codes for these teams up to 2020 (its old T.B / N.J / S.J / L.A files stop there);
# current files use the NHL codes. Reading maps any dotted code back.
FROM_MP = {"T.B": "TBL", "N.J": "NJD", "S.J": "SJS", "L.A": "LAK"}
TEAMS = ["ANA", "BOS", "BUF", "CGY", "CAR", "CHI", "COL", "CBJ", "DAL", "DET", "EDM", "FLA", "LAK", "MIN", "MTL",
         "NSH", "NJD", "NYI", "NYR", "OTT", "PHI", "PIT", "SJS", "SEA", "STL", "TBL", "TOR", "UTA", "VAN", "VGK",
         "WSH", "WPG"]

status: dict = {}


def path(name: str) -> str:
    return os.path.join(DIR, name + ".csv.gz")


def _fresh(name: str) -> bool:
    p = path(name)
    return os.path.exists(p) and (time.time() - os.path.getmtime(p)) < MAX_AGE_H * 3600


def _get(url: str, timeout: int = 20) -> bytes:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


_fails = 0
MAX_FAILS = 6          # stop after this many failures in a row (blocked or down): the build must not stall


def _save(name: str, url: str, force: bool = False):
    global _fails
    if not force and _fresh(name):
        status[name] = "cached"
        return
    if _fails >= MAX_FAILS:
        status[name] = "skipped (source failing)"
        return
    try:
        body = _get(url)
        if not body.lstrip()[:200].decode("utf-8", "replace").count(","):
            raise ValueError("not a CSV")
        os.makedirs(DIR, exist_ok=True)
        with gzip.open(path(name) + ".tmp", "wb") as f:
            f.write(body)
        os.replace(path(name) + ".tmp", path(name))
        status[name] = f"ok ({len(body) // 1024} KB)"
        _fails = 0
        print(f"  [moneypuck] {name}: {status[name]}", flush=True)
        _write_status()
    except Exception as e:  # blocked, renamed, network
        status[name] = f"failed: {e}"[:120]
        _fails += 1
        print(f"  [moneypuck] {name}: {status[name]}", flush=True)
        _write_status()
    time.sleep(0.5)          # be gentle


def season_start(today: dt.date) -> int:
    """MoneyPuck names a season by the year it starts: 2026 = the 2026-27 season."""
    return today.year if today.month >= 8 else today.year - 1


def fetch(today: dt.date | None = None, force: bool = False) -> dict:
    today = today or dt.date.today()
    s = season_start(today)
    for y in (s - 2, s - 1, s):
        for kind in ("goalies", "teams"):
            # finished seasons never change: fetch once
            done = y < s and os.path.exists(path(f"{kind}_{y}"))
            if done:
                status[f"{kind}_{y}"] = "cached"
                continue
            _save(f"{kind}_{y}", f"{BASE}/seasonSummary/{y}/regular/{kind}.csv", force)
    # team game logs are ~3.7 MB each and arrive slowly: 4 at a time
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(4) as ex:
        list(ex.map(lambda t: _save(f"team_games_{t}", f"{BASE}/careers/gameByGame/regular/teams/{t}.csv", force), TEAMS))
    ok = sum(str(v).startswith(("ok", "cached")) for v in status.values())
    _write_status()
    print(f"  [moneypuck] {ok}/{len(status)} files ok or cached")
    return status


def _write_status():
    os.makedirs(DIR, exist_ok=True)
    with open(os.path.join(DIR, "status.json"), "w") as f:
        json.dump({"at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "files": status}, f, indent=1)


def read(name: str):
    import pandas as pd
    p = path(name)
    if not os.path.exists(p):
        return None
    with gzip.open(p, "rb") as f:
        return pd.read_csv(io.BytesIO(f.read()))


def team_games(teams=TEAMS):
    """Every team's game-by-game rows (all situations), NHL team codes."""
    import pandas as pd
    frames = [d for t in teams if (d := read(f"team_games_{t}")) is not None]
    if not frames:
        return None
    x = pd.concat(frames, ignore_index=True)
    for c in ("team", "playerTeam", "opposingTeam"):
        if c in x:
            x[c] = x[c].map(lambda v: FROM_MP.get(v, v))
    return x


def attempts():
    """Score-adjusted unblocked shot attempts (Fenwick) for / against per team-game, all situations:
    DataFrame(game_id, team_abbrev, mp_ff, mp_fa), or None without the cache."""
    x = team_games()
    if x is None:
        return None
    x = x[x.situation == "all"]
    return x.assign(game_id=x.gameId.astype(int), team_abbrev=x.playerTeam)[
        ["game_id", "team_abbrev", "scoreAdjustedUnblockedShotAttemptsFor", "scoreAdjustedUnblockedShotAttemptsAgainst"]
    ].rename(columns={"scoreAdjustedUnblockedShotAttemptsFor": "mp_ff", "scoreAdjustedUnblockedShotAttemptsAgainst": "mp_fa"}
             ).drop_duplicates(["game_id", "team_abbrev"])


def with_attempts(tg):
    """tg with MoneyPuck mp_ff / mp_fa merged in (NaN where MoneyPuck has no row)."""
    a = attempts()
    if a is None:
        return tg.assign(mp_ff=float("nan"), mp_fa=float("nan"))
    return tg.drop(columns=[c for c in ("mp_ff", "mp_fa") if c in tg]).merge(a, on=["game_id", "team_abbrev"], how="left")


if __name__ == "__main__":
    import sys
    fetch(force="--force" in sys.argv)
