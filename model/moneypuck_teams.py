"""MoneyPuck team data (moneypuck.com, credited to MoneyPuck.com) for the saves model's shots-against term: the
score-adjusted unblocked shot attempts (Fenwick) for and against, per team-game (with_attempts; engine.mp_mode).
moneypuck.py is the separate goalie game-log cross-check that stops the build when MoneyPuck and the NHL box
scores disagree.

Two committed pieces in model/data/moneypuck/:
  team_games_<TEAM>.csv.gz   every team's full game log as of the last full snapshot (2026-11-03, about 0.9 MB
                             each). The build never refreshes these: 30 MB of new binaries a day would swamp the
                             repository.
  attempts_recent.csv        game_id, team_abbrev, mp_ff, mp_fa for the current season: the four numbers the model
                             needs from each game, refreshed about once a day by refresh() (about 30 new rows a day).
attempts() reads both; the recent file wins where they overlap.

refresh() runs in its own capped workflow step. A team's log is pulled at most once every MAX_AGE_H hours, judged
by the time of that team's last good pull in status.json, which is committed. (A fresh CI checkout gives every file
the checkout's time, so the old file-age test called everything fresh: nothing was refreshed after 2026-11-03, and
from about 11-06 MoneyPuck covered under 90% of the season and the saves model ran on its own attempt counts.)

    python model/moneypuck_teams.py              # refresh what is due
    python model/moneypuck_teams.py --force      # refresh every team now
    python model/moneypuck_teams.py --snapshot   # re-download the full logs and season summaries (by hand, then commit)
"""
from __future__ import annotations

import datetime as dt
import gzip
import io
import json
import os
import threading
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
COLS = ["game_id", "team_abbrev", "mp_ff", "mp_fa"]
FF, FA = "scoreAdjustedUnblockedShotAttemptsFor", "scoreAdjustedUnblockedShotAttemptsAgainst"
MAX_FAILS = 6          # stop after this many failures in a row (blocked or down): the build must not stall
GENTLE_S = 0.5         # pause after each download
MAX_PER_RUN = 8        # team logs pulled per build, longest-waiting first: MoneyPuck answered HTTP 429 after 25 in a
                       # row (2026-11-16), and with builds every 15 minutes all 32 still refresh within the hour

status: dict = {}
_lock = threading.Lock()


def path(name: str) -> str:
    return os.path.join(DIR, name + ".csv.gz")


def recent_path() -> str:
    return os.path.join(DIR, "attempts_recent.csv")


def status_path() -> str:
    return os.path.join(DIR, "status.json")


def _get(url: str, timeout: int = 20) -> bytes:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def season_start(today: dt.date) -> int:
    """MoneyPuck names a season by the year it starts: 2026 = the 2026-27 season."""
    return today.year if today.month >= 8 else today.year - 1


def _load_status() -> dict:
    try:
        with open(status_path()) as f:
            js = json.load(f)
        return js if isinstance(js, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_status(teams_at: dict | None = None, rows: int | None = None):
    os.makedirs(DIR, exist_ok=True)
    out = {"at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "files": dict(status)}
    prev = _load_status()
    out["teams_at"] = dict(teams_at) if teams_at is not None else (prev.get("teams_at") or {})
    out["recent_rows"] = rows if rows is not None else prev.get("recent_rows")
    with open(status_path() + ".tmp", "w") as f:
        json.dump(out, f, indent=1)
    os.replace(status_path() + ".tmp", status_path())


def due(teams_at: dict, team: str, now: dt.datetime) -> bool:
    """This team's log has not been pulled in the last MAX_AGE_H hours (or never, or its time cannot be read)."""
    try:
        return (now - dt.datetime.fromisoformat(teams_at[team])).total_seconds() >= MAX_AGE_H * 3600
    except (KeyError, TypeError, ValueError):
        return True


def parse_log(body: bytes, season: int):
    """The four numbers the model needs from one team's game log: its all-situations rows from `season` on."""
    import pandas as pd
    x = pd.read_csv(io.BytesIO(body), usecols=["gameId", "playerTeam", "situation", FF, FA])
    x = x[(x.situation == "all") & (x.gameId.astype(int) // 1_000_000 >= season)]
    return pd.DataFrame({"game_id": x.gameId.astype(int).values, "team_abbrev": [FROM_MP.get(v, v) for v in x.playerTeam],
                         "mp_ff": x[FF].astype(float).values, "mp_fa": x[FA].astype(float).values}, columns=COLS)


def read_recent():
    """attempts_recent.csv as a DataFrame, or None when it is missing or unreadable."""
    import pandas as pd
    try:
        x = pd.read_csv(recent_path())
        return x[COLS].astype({"game_id": int, "mp_ff": float, "mp_fa": float})
    except (OSError, ValueError, KeyError):
        return None


def _write_recent(x):
    os.makedirs(DIR, exist_ok=True)
    x.sort_values(["game_id", "team_abbrev"]).to_csv(recent_path() + ".tmp", index=False)
    os.replace(recent_path() + ".tmp", recent_path())


def refresh(today: dt.date | None = None, force: bool = False, now: dt.datetime | None = None) -> dict:
    """Pull the game log of every team that is due and fold its current-season rows into attempts_recent.csv.
    Each team is its own step: a failure or a stopped run keeps everything pulled so far, and the teams that were
    not reached are simply still due on the next build."""
    import pandas as pd
    from concurrent.futures import ThreadPoolExecutor
    now = now or dt.datetime.now(dt.timezone.utc)
    season = season_start(today or now.date())
    teams_at = dict(_load_status().get("teams_at") or {})
    cur = read_recent()
    box = {"cur": cur if cur is not None else pd.DataFrame(columns=COLS), "fails": 0, "pulled": 0}
    status.clear()

    def one(team):
        name = f"team_games_{team}"
        if box["fails"] >= MAX_FAILS:
            status[name] = "skipped (source failing)"
            return
        try:
            body = _get(f"{BASE}/careers/gameByGame/regular/teams/{team}.csv")
            rows = parse_log(body, season)
        except Exception as e:  # blocked, renamed, network, not a CSV
            with _lock:
                box["fails"] += 1
                status[name] = f"failed: {e}"[:120]
                _write_status(teams_at, len(box["cur"]))
            print(f"  [moneypuck] {name}: {status[name]}", flush=True)
            time.sleep(GENTLE_S)
            return
        with _lock:
            c = box["cur"]
            # this team's rows for the season are replaced by what MoneyPuck says now (it revises its numbers)
            mine = set(rows.team_abbrev) | {FROM_MP.get(team, team)}
            c = c[~(c.team_abbrev.isin(mine) & (c.game_id.astype(int) // 1_000_000 >= season))]
            box["cur"] = pd.concat([c, rows], ignore_index=True) if len(c) else rows.copy()
            box["fails"], box["pulled"] = 0, box["pulled"] + 1
            teams_at[team] = now.isoformat(timespec="seconds")
            status[name] = f"ok ({len(body) // 1024} KB, {len(rows)} games)"
            _write_recent(box["cur"])
            _write_status(teams_at, len(box["cur"]))
        print(f"  [moneypuck] {name}: {status[name]}", flush=True)
        time.sleep(GENTLE_S)

    # the teams that are due, longest-waiting first (never pulled before all others), at most MAX_PER_RUN per build
    want = [t for t in TEAMS if force or due(teams_at, t, now)]
    if not force:
        want = sorted(want, key=lambda t: (t in teams_at, str(teams_at.get(t) or "")))[:MAX_PER_RUN]
    for t in TEAMS:
        if t not in want:
            status[f"team_games_{t}"] = "fresh" if not due(teams_at, t, now) else "due (a later build)"
    # the logs are about 3.7 MB each and arrive slowly: 4 at a time
    with ThreadPoolExecutor(4) as ex:
        list(ex.map(one, want))
    _write_status(teams_at, len(box["cur"]))
    ok = sum(str(v).startswith(("ok", "fresh")) for v in status.values())
    print(f"  [moneypuck] {ok}/{len(status)} team logs fresh ({box['pulled']} pulled now, "
          f"{sum(str(v).startswith('due') for v in status.values())} waiting); {len(box['cur'])} team-games this season")
    return status


# ---------- the full snapshot (by hand): every log and the season summaries, into the committed copy ----------
_fails = 0


def _save(name: str, url: str, force: bool = False):
    global _fails
    if not force and os.path.exists(path(name)) and (time.time() - os.path.getmtime(path(name))) < MAX_AGE_H * 3600:
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
    print(f"  [moneypuck] {name}: {status[name]}", flush=True)
    time.sleep(GENTLE_S)


def snapshot(today: dt.date | None = None, force: bool = False) -> dict:
    """Re-download every team's full log and the season summaries into model/data/moneypuck (run by hand; commit
    the result). The build itself only runs refresh()."""
    from concurrent.futures import ThreadPoolExecutor
    today = today or dt.date.today()
    s = season_start(today)
    for y in (s - 2, s - 1, s):
        for kind in ("goalies", "teams"):
            if y < s and os.path.exists(path(f"{kind}_{y}")):     # finished seasons never change: fetch once
                status[f"{kind}_{y}"] = "cached"
                continue
            _save(f"{kind}_{y}", f"{BASE}/seasonSummary/{y}/regular/{kind}.csv", force)
    with ThreadPoolExecutor(4) as ex:
        list(ex.map(lambda t: _save(f"team_games_{t}", f"{BASE}/careers/gameByGame/regular/teams/{t}.csv", force), TEAMS))
    _write_status()
    return status


def read(name: str):
    import pandas as pd
    p = path(name)
    if not os.path.exists(p):
        return None
    with gzip.open(p, "rb") as f:
        return pd.read_csv(io.BytesIO(f.read()))


def team_games(teams=TEAMS):
    """Every team's game-by-game rows (all situations) from the committed snapshot, NHL team codes."""
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
    DataFrame(game_id, team_abbrev, mp_ff, mp_fa) from the snapshot logs plus the recent file (which wins where
    both have a game), or None with neither."""
    import pandas as pd
    parts = []
    x = team_games()
    if x is not None:
        x = x[x.situation == "all"]
        parts.append(pd.DataFrame({"game_id": x.gameId.astype(int).values, "team_abbrev": x.playerTeam.values,
                                   "mp_ff": x[FF].astype(float).values, "mp_fa": x[FA].astype(float).values}, columns=COLS))
    rec = read_recent()
    if rec is not None and len(rec):
        parts.append(rec)
    if not parts:
        return None
    return pd.concat(parts, ignore_index=True).drop_duplicates(["game_id", "team_abbrev"], keep="last").reset_index(drop=True)


def with_attempts(tg):
    """tg with MoneyPuck mp_ff / mp_fa merged in (NaN where MoneyPuck has no row)."""
    a = attempts()
    if a is None:
        return tg.assign(mp_ff=float("nan"), mp_fa=float("nan"))
    return tg.drop(columns=[c for c in ("mp_ff", "mp_fa") if c in tg]).merge(a, on=["game_id", "team_abbrev"], how="left")


if __name__ == "__main__":
    import sys
    if "--snapshot" in sys.argv:
        snapshot(force="--force" in sys.argv)
    else:
        refresh(force="--force" in sys.argv)
