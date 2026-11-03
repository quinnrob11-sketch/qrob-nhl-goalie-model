"""MoneyPuck public data for the saves model.

Source: the season files linked from https://moneypuck.com/data.htm (credited to MoneyPuck.com).
Goalie game logs (one row per goalie per game, situation "all") carry shots on goal, goals,
saves, ice time, xGoals, unblocked shot attempts and high-danger counts. The shot file is the
same model at shot level; its game id is the NHL id without the season prefix
(`season * 1_000_000 + game_id`).

Download goes to model/cache/moneypuck/ (gitignored). If a download fails, the committed
snapshot in model/data/moneypuck/ is used. If neither can supply a requested season, this
module raises. It does not return an empty frame and continue.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
import zipfile

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache", "moneypuck")
SNAPSHOT = os.path.join(HERE, "data", "moneypuck", "goalies_game.csv.gz")
SNAPSHOT_META = os.path.join(HERE, "data", "moneypuck", "snapshot.json")

# season year is the year the season STARTS (2026 = 2026-27), matching MoneyPuck's URLs
GOALIE_ZIP = "https://peter-tanner.com/moneypuck/downloads/seasonPlayersSummary/goalies/{year}.zip"
SHOT_ZIP = "https://peter-tanner.com/moneypuck/downloads/shots_{year}.zip"
UA = "Mozilla/5.0 (compatible; qrob-goalie-model; +https://github.com/)"

# columns kept from the goalie game file. situation == "all" is the full appearance.
KEEP = ["playerId", "name", "gameId", "season", "playerTeam", "opposingTeam", "home_or_away",
        "gameDate", "icetime", "xGoals", "flurryAdjustedxGoals", "goals", "ongoal",
        "unblocked_shot_attempts", "highDangerShots", "highDangerxGoals",
        "mediumDangerShots", "lowDangerShots", "blocked_shot_attempts"]

# NHL box-score team abbrev vs MoneyPuck. Arizona's 2023-24 rows are ARI in the NHL file
# and UTA in MoneyPuck (the franchise moved). That label gap is not a stat mismatch.
TEAM_FIX = {"LA": "LAK", "NJ": "NJD", "SJ": "SJS", "TB": "TBL", "MON": "MTL", "WAS": "WSH",
            "CLB": "CBJ", "NAS": "NSH", "VEG": "VGK", "UTAH": "UTA", "L.A": "LAK", "N.J": "NJD",
            "S.J": "SJS", "T.B": "TBL"}
LABEL_OK = {("ARI", "UTA"), ("UTA", "ARI")}

# cross-check tolerances, on matched goalie-games. NHL and the goalie game file agree
# to well inside these; anything looser means one of the feeds is wrong.
SA_MAE_MAX = 0.25
SAVES_MAE_MAX = 0.25
TOI_MAE_MAX = 0.05
MATCH_RATE_MIN = 0.95


class MoneyPuckError(RuntimeError):
    """Raised when MoneyPuck data is missing or disagrees with the NHL box scores."""


def nhl_game_id(season_start: int, shot_game_id: int) -> int:
    """Shot-file game_id (game type + number, e.g. 20001) -> NHL game id (2026020001)."""
    return int(season_start) * 1_000_000 + int(shot_game_id)


def _team(t) -> str:
    t = str(t).upper().strip()
    return TEAM_FIX.get(t, t)


def _download(url: str, dest: str, timeout: int = 90) -> None:
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r, open(dest + ".tmp", "wb") as f:
            f.write(r.read())
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise MoneyPuckError(f"download failed: {url} ({e})") from e
    os.replace(dest + ".tmp", dest)


def _csv_from_zip(path: str) -> pd.DataFrame:
    try:
        z = zipfile.ZipFile(path)
    except zipfile.BadZipFile as e:
        raise MoneyPuckError(f"not a zip file: {path}") from e
    name = next((n for n in z.namelist() if n.lower().endswith(".csv")), None)
    if name is None:
        raise MoneyPuckError(f"no csv inside {path} (members: {z.namelist()[:4]})")
    return pd.read_csv(z.open(name))


def _goalie_cache(year: int) -> str:
    return os.path.join(CACHE, f"goalies_{year}.zip")


def _normalize(df: pd.DataFrame, year: int) -> pd.DataFrame:
    if "situation" not in df.columns:
        raise MoneyPuckError(f"goalie file for {year} has no situation column")
    df = df[df.situation == "all"].copy()
    if df.empty:
        raise MoneyPuckError(f"goalie file for {year} has no situation='all' rows")
    missing = [c for c in KEEP if c not in df.columns]
    if missing:
        raise MoneyPuckError(f"goalie file for {year} missing columns {missing}")
    out = df[KEEP].copy()
    out["season"] = out.season.astype(int)
    out["playerId"] = out.playerId.astype(int)
    out["gameId"] = out.gameId.astype(int)
    out["team"] = out.playerTeam.map(_team)
    out["opp"] = out.opposingTeam.map(_team)
    out["date"] = pd.to_datetime(out.gameDate.astype(str), format="%Y%m%d")
    out["saves"] = out.ongoal - out.goals
    out["toi_min"] = out.icetime / 60.0
    out["gsax"] = out.xGoals - out.goals
    return out


def _from_snapshot(years: list[int]) -> pd.DataFrame | None:
    if not os.path.exists(SNAPSHOT):
        return None
    df = pd.read_csv(SNAPSHOT)
    df = df[df.season.isin(years)].copy()
    if df.empty:
        return None
    return _normalize(df.assign(situation="all"), int(df.season.iloc[0]))


def load_goalie_games(years: list[int], refresh: bool = True) -> tuple[pd.DataFrame, dict]:
    """Goalie game rows for MoneyPuck season-start years.

    Returns (frame, source info). Raises MoneyPuckError if a year cannot be loaded from
    the network or the committed snapshot.
    """
    frames, sources, errors = [], {}, []
    for y in years:
        path = _goalie_cache(y)
        err = None
        if refresh or not os.path.exists(path):
            try:
                _download(GOALIE_ZIP.format(year=y), path)
            except MoneyPuckError as e:
                err = str(e)
                errors.append(f"{y}: {e}")
        if os.path.exists(path):
            try:
                frames.append(_normalize(_csv_from_zip(path), y))
                sources[y] = "download" if err is None else "cache"
                continue
            except MoneyPuckError as e:
                errors.append(f"{y}: cached zip unreadable ({e})")
        sources[y] = None
    got = {int(s) for f in frames for s in f.season.unique()} if frames else set()
    missing = [y for y in years if y not in got]
    snap = _from_snapshot(missing) if missing else None
    if snap is not None and len(snap):
        have = set(int(s) for s in snap.season.unique())
        frames.append(snap[snap.season.isin(missing)])
        for y in have:
            sources[y] = "snapshot"
        missing = [y for y in missing if y not in have]
    if missing:
        raise MoneyPuckError(
            "MoneyPuck goalie games unavailable for season(s) "
            + ", ".join(str(y) for y in missing)
            + ". Download failed and the committed snapshot does not cover them. "
            + " | ".join(errors))
    out = pd.concat(frames, ignore_index=True).drop_duplicates(["gameId", "playerId"])
    info = {"seasons": {str(y): sources.get(y) for y in years},
            "errors": errors, "rows": int(len(out)),
            "through": str(out.date.max().date()) if len(out) else None}
    if errors and all(sources.get(y) == "snapshot" for y in years):
        info["warning"] = "MoneyPuck download failed; using the committed snapshot. " + " | ".join(errors)
    elif errors:
        info["warning"] = "MoneyPuck download failed for some seasons; mixed snapshot/cache. " + " | ".join(errors)
    return out, info


def cross_check(nhl_starts: pd.DataFrame, mp: pd.DataFrame) -> dict:
    """Compare NHL starter box scores to MoneyPuck goalie game logs.

    `nhl_starts` is the starter frame from data.load (shots_against, saves, toi_min, player_id, game_id).
    Team-abbrev gaps are reported and do not fail the check; ARI vs UTA is the relocated franchise.
    """
    nhl = nhl_starts.copy()
    nhl["game_id"] = nhl.game_id.astype(int)
    nhl["player_id"] = nhl.player_id.astype(int)
    m = mp.copy()
    m["game_id"] = m.gameId.astype(int)
    m["player_id"] = m.playerId.astype(int)
    j = nhl.merge(m, on=["game_id", "player_id"], how="left", suffixes=("_nhl", ""))
    both = j[j.ongoal.notna()].copy()
    n = len(nhl)
    if n == 0:
        raise MoneyPuckError("no NHL starter rows to cross-check against MoneyPuck")
    if both.empty:
        raise MoneyPuckError("MoneyPuck matched 0 NHL starter rows (game id / player id join failed)")
    sa = (both.shots_against - both.ongoal).abs()
    sv = (both.saves_nhl - both.saves).abs()          # left = NHL, right = MoneyPuck
    toi = (both.toi_min_nhl - both.toi_min).abs()
    mism = []
    if "team_abbrev" in both.columns and "team" in both.columns:
        mism = [(a, b) for a, b in zip(both.team_abbrev, both.team) if a != b and (a, b) not in LABEL_OK]
    rep = {
        "nhl_starts": int(n),
        "matched": int(len(both)),
        "match_rate": round(len(both) / n, 4),
        "sa_mae": round(float(sa.mean()), 4),
        "saves_mae": round(float(sv.mean()), 4),
        "toi_mae": round(float(toi.mean()), 4),
        "sa_exact": round(float((sa < 0.05).mean()), 4),
        "team_mismatches": len(mism),
        "team_mismatch_pairs": sorted({f"{a}->{b}" for a, b in mism})[:12],
    }
    # The public goalie game zip is the regular season. Playoff starts are reported, not failed.
    gtype = nhl.game_id.astype(str).str.zfill(10).str[4:6]
    regular = (gtype == "02").values
    rep["regular_starts"] = int(regular.sum())
    rep["regular_match_rate"] = round(float(j.loc[regular, "ongoal"].notna().mean()), 4) if regular.any() else None
    rep["playoff_starts"] = int((~regular).sum())
    rep["playoff_matched"] = int(j.loc[~regular, "ongoal"].notna().sum())
    # coverage of regular-season games MoneyPuck should already have published
    if "game_date" in nhl.columns and "date" in m.columns:
        nhl_dates = pd.to_datetime(nhl.game_date)
        cutoff = m.date.max()
        due = regular & (nhl_dates <= cutoff).values
        due_match = j.loc[due, "ongoal"].notna().mean() if due.any() else 1.0
        rep["due_match_rate"] = round(float(due_match), 4)
        rep["mp_through"] = str(cutoff.date())
    else:
        rep["due_match_rate"] = rep["regular_match_rate"] if rep["regular_match_rate"] is not None else rep["match_rate"]
    problems = []
    if rep["sa_mae"] > SA_MAE_MAX:
        problems.append(f"shots against MAE {rep['sa_mae']} > {SA_MAE_MAX}")
    if rep["saves_mae"] > SAVES_MAE_MAX:
        problems.append(f"saves MAE {rep['saves_mae']} > {SAVES_MAE_MAX}")
    if rep["toi_mae"] > TOI_MAE_MAX:
        problems.append(f"TOI MAE {rep['toi_mae']} > {TOI_MAE_MAX}")
    if rep["due_match_rate"] < MATCH_RATE_MIN:
        problems.append(f"only {rep['due_match_rate']:.1%} of regular-season NHL starts through {rep.get('mp_through')} matched MoneyPuck")
    rep["ok"] = not problems
    rep["problems"] = problems
    return rep


def verify(nhl_starts: pd.DataFrame, years: list[int] | None = None, refresh: bool = True) -> dict:
    """Load MoneyPuck and cross-check it. Raises MoneyPuckError on a real disagreement or if both
    the download and the snapshot are missing. A failed download that falls back to a good snapshot
    is returned with a warning, and printed, so it is not silent."""
    if years is None:
        if "season" not in nhl_starts.columns:
            raise MoneyPuckError("NHL starts have no season column; pass years explicitly")
        # data.season is the year the season ENDS; MoneyPuck's year is the year it starts
        years = sorted({int(s) - 1 for s in nhl_starts.season.unique()})
    mp, info = load_goalie_games(years, refresh=refresh)
    rep = cross_check(nhl_starts, mp)
    rep["source"] = info
    if info.get("warning"):
        print(f"  [moneypuck] ERROR {info['warning']}")
    if not rep["ok"]:
        raise MoneyPuckError("MoneyPuck disagrees with the NHL box scores: " + "; ".join(rep["problems"])
                             + f" ({rep})")
    print(f"  [moneypuck] {rep['matched']}/{rep['nhl_starts']} starts match "
          f"(SA MAE {rep['sa_mae']}, saves MAE {rep['saves_mae']}, TOI MAE {rep['toi_mae']}); "
          f"through {info.get('through')}; source {info['seasons']}")
    return rep


def shot_check(year: int, mp_goalies: pd.DataFrame, refresh: bool = True) -> dict:
    """Sum the shot file for one season and compare to the goalie game log.

    The shot zip lags the game log by hours and omits a few shots (on-goal MAE around 0.2).
    xGoals on the game log matches the sum of shot-level xGoal over every unblocked attempt
    (shots, misses and goals) with a goalie in net. A join that matches nothing, or an on-goal
    MAE above 1.0, means the file or the id map is wrong and raises.
    """
    path = os.path.join(CACHE, f"shots_{year}.zip")
    err = None
    if refresh or not os.path.exists(path):
        try:
            _download(SHOT_ZIP.format(year=year), path, timeout=180)
        except MoneyPuckError as e:
            err = str(e)
    if not os.path.exists(path):
        raise MoneyPuckError(f"MoneyPuck shot file for {year} unavailable and not cached. {err or ''}")
    cols = ["game_id", "season", "goalieIdForShot", "shotWasOnGoal", "goal", "xGoal", "shotOnEmptyNet"]
    sh = pd.read_csv(path, usecols=cols)
    sh = sh[sh.goalieIdForShot.notna() & (sh.shotOnEmptyNet == 0)].copy()
    sh["game_nhl"] = [nhl_game_id(int(s), int(g)) for s, g in zip(sh.season, sh.game_id)]
    sh["player_id"] = sh.goalieIdForShot.astype(int)
    on = sh[sh.shotWasOnGoal == 1]
    agg = on.groupby(["game_nhl", "player_id"]).agg(ongoal=("goal", "size"), goals=("goal", "sum")).reset_index()
    xg = sh.groupby(["game_nhl", "player_id"]).xGoal.sum().rename("xg").reset_index()
    agg = agg.merge(xg, on=["game_nhl", "player_id"], how="outer")
    g = mp_goalies[mp_goalies.season == year][["gameId", "playerId", "ongoal", "goals", "xGoals"]]
    j = g.merge(agg, left_on=["gameId", "playerId"], right_on=["game_nhl", "player_id"], how="left", suffixes=("_g", "_s"))
    matched = j["ongoal_s"].notna() if "ongoal_s" in j.columns else j["ongoal_y"].notna()
    # suffixes: g has ongoal, agg has ongoal -> ongoal_g / ongoal_s if we renamed. merge suffixes default _x _y.
    # I passed suffixes=("_g","_s"), so ongoal_g and ongoal_s.
    if "ongoal_g" not in j.columns:
        raise MoneyPuckError(f"shot check merge failed; columns {list(j.columns)[:12]}")
    n = len(g)
    rate = float(matched.mean()) if n else 0.0
    m = j[matched]
    rep = {"year": year, "goalie_games": int(n), "matched": int(matched.sum()), "match_rate": round(rate, 4),
           "sa_mae": round(float((m.ongoal_g - m.ongoal_s).abs().mean()), 4) if len(m) else None,
           "ga_mae": round(float((m.goals_g - m.goals_s).abs().mean()), 4) if len(m) else None,
           "xg_mae": round(float((m.xGoals - m.xg).abs().mean()), 4) if len(m) else None,
           "download_error": err}
    if rate < 0.5:
        raise MoneyPuckError(f"shot file joined only {rate:.1%} of {year} goalie games; the game-id map is wrong. {rep}")
    if rep["sa_mae"] is not None and rep["sa_mae"] > 1.0:
        raise MoneyPuckError(f"shot file on-goal totals disagree with the goalie game log (MAE {rep['sa_mae']}). {rep}")
    if err:
        print(f"  [moneypuck] ERROR shot download for {year} failed, used cache. {err}")
    return rep


def write_snapshot(years: list[int] | None = None) -> str:
    """Refresh the committed fallback from the network (or the cache). Used when updating the snapshot."""
    years = years or [2023, 2024, 2025, 2026]
    df, info = load_goalie_games(years, refresh=True)
    os.makedirs(os.path.dirname(SNAPSHOT), exist_ok=True)
    keep = [c for c in KEEP if c in df.columns]
    # situation is not on the normalized frame; the snapshot is situation=all only
    out = df[keep].sort_values(["season", "gameId", "playerId"]).copy()
    out["gameDate"] = out.gameDate.astype(int)
    out.to_csv(SNAPSHOT, index=False, compression="gzip")
    meta = {"built": str(pd.Timestamp.utcnow().date()), "seasons": years, "rows": int(len(out)),
            "through": info.get("through"), "source": "MoneyPuck goalie game files, situation=all",
            "credit": "https://moneypuck.com/data.htm"}
    json.dump(meta, open(SNAPSHOT_META, "w"), indent=1)
    return SNAPSHOT


if __name__ == "__main__":
    print(write_snapshot())
