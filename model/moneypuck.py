"""MoneyPuck data (moneypuck.com, free for non-commercial use with credit): goalie and team season
summaries and every team's game-by-game log, cached in model/data/moneypuck/ (gzipped CSV).

Used to check our shots / saves data game by game and as inputs the saves model is backtested with
(expected goals against, shot attempts, high-danger shots, goalie GSAx). Fetched at most once every
MAX_AGE_H hours; each file is best-effort and `status` lists what came back.

    python model/moneypuck.py          # refresh the cache now
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
# MoneyPuck team codes that differ from the NHL's
TO_MP = {"TBL": "T.B", "NJD": "N.J", "SJS": "S.J", "LAK": "L.A"}
FROM_MP = {v: k for k, v in TO_MP.items()}
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
MAX_FAILS = 3          # stop after this many failures in a row (blocked or down): the build must not stall


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
    except Exception as e:  # blocked, renamed, network
        status[name] = f"failed: {e}"[:120]
        _fails += 1
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
    for t in TEAMS:
        _save(f"team_games_{t}", f"{BASE}/careers/gameByGame/regular/teams/{TO_MP.get(t, t)}.csv", force)
    ok = sum(str(v).startswith(("ok", "cached")) for v in status.values())
    os.makedirs(DIR, exist_ok=True)
    with open(os.path.join(DIR, "status.json"), "w") as f:
        json.dump({"at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "files": status}, f, indent=1)
    print(f"  [moneypuck] {ok}/{len(status)} files ok or cached")
    return status


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


if __name__ == "__main__":
    fetch(force=True)
    print(json.dumps(status, indent=1))
