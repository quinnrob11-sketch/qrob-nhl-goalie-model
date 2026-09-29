"""Data loading for the goalie saves model.

Source: sportsdataverse/fastRhockey-nhl-data (public GitHub repo, rebuilt daily
from the NHL API). Files are keyed by the year the season ENDS, so
2026 = the 2025-26 season, 2027 = the 2026-27 season.

Parquet files are cached under model/cache/ (gitignored).
"""
from __future__ import annotations

import os
import urllib.request

import numpy as np
import pandas as pd

RAW = "https://raw.githubusercontent.com/sportsdataverse/fastRhockey-nhl-data/main/nhl"
HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache")

FILES = {
    "goalie": "goalie_box/parquet/goalie_box_{y}.parquet",
    "team": "team_box/parquet/team_box_{y}.parquet",
    "sched": "schedules/parquet/nhl_schedule_{y}.parquet",
    "pbp": "pbp_lite/parquet/play_by_play_lite_{y}.parquet",
    "skater": "skater_box/parquet/skater_box_{y}.parquet",
}

SHOT_EVENTS = ["SHOT", "GOAL", "MISSED_SHOT", "BLOCKED_SHOT"]
PBP_COLS = ["event_type", "event_team_abbr", "home_abbr", "away_abbr", "event_goalie_id",
            "empty_net", "period", "game_seconds", "xg", "game_id"]


def _path(kind: str, year: int) -> str:
    return os.path.join(CACHE, FILES[kind].format(y=year))


def fetch(kind: str, year: int, refresh: bool = False) -> str | None:
    """Download one parquet file into the cache. Returns local path, or None if unavailable."""
    path = _path(kind, year)
    if os.path.exists(path) and not refresh:
        return path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    url = f"{RAW}/{FILES[kind].format(y=year)}"
    try:
        with urllib.request.urlopen(url, timeout=120) as r, open(path + ".tmp", "wb") as f:
            f.write(r.read())
        os.replace(path + ".tmp", path)
        return path
    except Exception as e:  # season not published yet, network down, etc.
        print(f"  [data] {kind} {year} unavailable: {e}")
        return path if os.path.exists(path) else None


def _minutes(toi: pd.Series) -> pd.Series:
    parts = toi.fillna("0:00").str.split(":", expand=True).astype(float)
    return parts[0] + parts[1] / 60.0


def load_season(year: int, refresh: bool = False, with_pbp: bool = True) -> dict | None:
    gp, tp = fetch("goalie", year, refresh), fetch("team", year, refresh)
    if not gp or not tp:
        return None
    g = pd.read_parquet(gp)
    t = pd.read_parquet(tp)

    # ---- team-games: one row per team per game, with opponent attached ----
    t = t[["game_id", "game_date", "team_abbrev", "home_away", "goals", "shots_on_goal",
           "blocked_shots", "pim", "power_play_goals"]].copy()
    opp = t.rename(columns={c: "opp_" + c for c in t.columns if c not in ("game_id",)})
    tg = t.merge(opp, on="game_id")
    tg = tg[tg.team_abbrev != tg.opp_team_abbrev].copy()
    tg["season"] = year
    tg["game_type"] = tg.game_id.astype(str).str[4:6].map({"02": "R", "03": "P"})
    tg = tg[tg.game_type.notna()]
    tg["is_home"] = tg.home_away == "home"

    # ---- starting goalies ----
    g = g[g.starter == True].copy()  # noqa: E712
    g["toi_min"] = _minutes(g.toi)
    g = g[["game_id", "game_date", "team_abbrev", "player_id", "player_name", "saves",
           "shots_against", "goals_against", "toi_min"]]

    # ---- play-by-play derived metrics (optional) ----
    pbp_team = pbp_goalie = None
    pp = fetch("pbp", year, refresh) if with_pbp else None
    if pp:
        pbp_team, pbp_goalie = _pbp_metrics(pd.read_parquet(pp, columns=PBP_COLS))
        tg = tg.merge(pbp_team, on=["game_id", "team_abbrev"], how="left")
        opp_pbp = pbp_team.rename(columns={"team_abbrev": "opp_team_abbrev", "cf": "opp_cf",
                                           "xgf": "opp_xgf", "blocks_made": "opp_blocks_made"})
        tg = tg.merge(opp_pbp, on=["game_id", "opp_team_abbrev"], how="left")
        g = g.merge(pbp_goalie, on=["game_id", "player_id"], how="left")
    return {"team_games": tg, "starts": g}


def _pbp_metrics(p: pd.DataFrame):
    """Per team-game: shot attempts (Corsi) for, xG for, own blocks.
    Per goalie-game: xG faced on unblocked shots, rebounds allowed."""
    s = p[p.event_type.isin(SHOT_EVENTS) & ~p.empty_net.fillna(False)].copy()
    other = np.where(s.event_team_abbr == s.home_abbr, s.away_abbr, s.home_abbr)
    # BLOCKED_SHOT is credited to the blocking team; everything else to the shooting team.
    s["shoot_team"] = np.where(s.event_type == "BLOCKED_SHOT", other, s.event_team_abbr)
    s["def_team"] = np.where(s.shoot_team == s.home_abbr, s.away_abbr, s.home_abbr)
    s["xg"] = s.xg.fillna(0.0)

    cf = s.groupby(["game_id", "shoot_team"]).size().rename("cf")
    xgf = s.groupby(["game_id", "shoot_team"]).xg.sum().rename("xgf")
    blk = s[s.event_type == "BLOCKED_SHOT"].groupby(["game_id", "def_team"]).size().rename("blocks_made")
    team = pd.concat([cf, xgf], axis=1).reset_index().rename(columns={"shoot_team": "team_abbrev"})
    blk = blk.reset_index().rename(columns={"def_team": "team_abbrev"})
    team = team.merge(blk, on=["game_id", "team_abbrev"], how="left").fillna({"blocks_made": 0})

    # Rebounds: a shot on goal / goal within 3s of a prior shot on goal by the same team, same period.
    on_goal = s[s.event_type.isin(["SHOT", "GOAL"])].sort_values(["game_id", "period", "game_seconds"]).copy()
    prev_team = on_goal.groupby(["game_id", "period"]).shoot_team.shift()
    prev_t = on_goal.groupby(["game_id", "period"]).game_seconds.shift()
    prev_type = on_goal.groupby(["game_id", "period"]).event_type.shift()
    on_goal["rebound"] = (prev_team == on_goal.shoot_team) & (on_goal.game_seconds - prev_t <= 3) & (prev_type == "SHOT")
    goalie = on_goal[on_goal.event_goalie_id.notna()].groupby(["game_id", "event_goalie_id"]).agg(
        xga=("xg", "sum"), rebounds=("rebound", "sum")).reset_index()
    goalie = goalie.rename(columns={"event_goalie_id": "player_id"})
    goalie["player_id"] = goalie.player_id.astype("int64")
    return team, goalie


def load_all(years, refresh: bool = False, with_pbp: bool = True):
    tgs, sts = [], []
    for y in years:
        d = load_season(y, refresh=refresh, with_pbp=with_pbp)
        if d is None:
            continue
        tgs.append(d["team_games"])
        d["starts"]["season"] = y
        sts.append(d["starts"])
    tg = pd.concat(tgs, ignore_index=True).sort_values(["game_date", "game_id"])
    st = pd.concat(sts, ignore_index=True)
    return tg, st
