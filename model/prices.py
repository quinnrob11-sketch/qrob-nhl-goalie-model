"""DraftKings price history (model/data/dk_prices.csv): one place to read it the same way everywhere.

Every reader that grades, calibrates or backtests against a DraftKings price must use the LAST snapshot
taken BEFORE the game's scheduled start. The build used to pull events up to an hour after puck drop, and
readers took the last snapshot of any time, so about 5% of SOG lines (11% of points) were priced from an
in-game snapshot: look-ahead, small in effect but wrong in principle.

The start time comes from the `start` column when the build recorded it (2026-11-08 on), otherwise from
the NHL schedule (game_time, matched on the date and the away / home teams).
"""
from __future__ import annotations

import datetime as dt
import os

import pandas as pd

import data

KEY = ["market", "date", "name", "line"]


def _season(d: dt.date) -> int:
    """Season keyed by its end year (2027 = 2026-27)."""
    return d.year + 1 if d.month >= 8 else d.year


def schedule_starts(dates) -> pd.DataFrame:
    """(date, away, home, start) for every scheduled game in the seasons covering `dates`."""
    years = sorted({_season(pd.Timestamp(d).date()) for d in dates if isinstance(d, str) and d})
    frames = []
    for y in years:
        path = data.fetch("sched", y)
        if not path or not os.path.exists(path):
            continue
        s = pd.read_parquet(path, columns=["game_date", "game_time", "home_team_abbr", "away_team_abbr"])
        frames.append(s)
    if not frames:
        return pd.DataFrame(columns=["away", "home", "start", "gdate"])
    s = pd.concat(frames, ignore_index=True)
    s["start"] = pd.to_datetime(s.game_time, utc=True, errors="coerce")
    return s.rename(columns={"home_team_abbr": "home", "away_team_abbr": "away"})[["away", "home", "start"]].dropna()


def with_start(pr: pd.DataFrame) -> pd.DataFrame:
    """Add `start_ts` (UTC) to price rows: the recorded start, else the schedule's game whose teams match and
    whose start is within a day of the row's date."""
    pr = pr.copy()
    rec = pd.to_datetime(pr["start"], utc=True, errors="coerce") if "start" in pr \
        else pd.Series(pd.NaT, index=pr.index, dtype="datetime64[ns, UTC]")
    pr["start_ts"] = rec.astype("datetime64[ns, UTC]")
    need = pr.start_ts.isna() & pr.teams.astype(str).str.contains("/")
    if need.any():
        sch = schedule_starts(pr.loc[need, "date"].unique())
        if len(sch):
            t = pr.loc[need, "teams"].astype(str).str.split("/", n=1, expand=True)
            q = pd.DataFrame({"away": t[0], "home": t[1], "day": pd.to_datetime(pr.loc[need, "date"])}, index=t.index)
            q["i"] = q.index
            m = q.merge(sch, on=["away", "home"], how="left")
            m = m[(m.start - m.day.dt.tz_localize("UTC")).abs() <= pd.Timedelta(hours=36)]
            m = m.sort_values("start").drop_duplicates("i", keep="first").set_index("i")
            pr.loc[m.index, "start_ts"] = m.start.astype("datetime64[ns, UTC]")
    return pr


def last_pregame(pr: pd.DataFrame, keys=KEY) -> pd.DataFrame:
    """One row per key: the last snapshot taken before the scheduled start. Rows whose start can't be
    determined keep their last snapshot (flagged `start_known` False)."""
    if pr is None or not len(pr):
        return pr
    pr = with_start(pr)
    snap = pd.to_datetime(pr.snap, utc=True, errors="coerce")
    known = pr.start_ts.notna()
    pr = pr[~known | (snap < pr.start_ts)].copy()
    pr["start_known"] = pr.start_ts.notna()
    pr["_snap"] = pd.to_datetime(pr.snap, utc=True, errors="coerce")
    return pr.sort_values("_snap").drop_duplicates(keys, keep="last").drop(columns=["_snap"])


def append(path: str, rows: list[dict], key=KEY) -> int:
    """Append snapshots, keeping a row only when its price differs from that key's latest stored row (so a
    line that moves A -> B -> A keeps the latest A; the old dedup kept the first A). Returns rows added."""
    if not rows:
        return 0
    new = pd.DataFrame(rows)
    if os.path.exists(path):
        old = pd.read_csv(path)
        for c in new.columns:
            if c not in old.columns:
                old[c] = None
        last = old.assign(_o=range(len(old))).sort_values("_o").drop_duplicates(key, keep="last")
        last = last.set_index(key)[["over", "under"]]
        def changed(r):
            k = tuple(r[c] for c in key)
            if k not in last.index:
                return True
            o, u = last.loc[k, "over"], last.loc[k, "under"]
            same = lambda a, b: (pd.isna(a) and pd.isna(b)) or (not pd.isna(a) and not pd.isna(b) and float(a) == float(b))
            return not (same(o, r["over"]) and same(u, r["under"]))
        keep = new[[changed(r) for _, r in new.iterrows()]]
        out = pd.concat([old, keep], ignore_index=True)
    else:
        keep = new
        out = new
    out.to_csv(path, index=False)
    return int(len(keep))
