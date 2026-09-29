"""Build index.html (the dashboard Vercel serves) with all data inlined.

    python model/build_site.py

Steps: load every season available -> walk the model forward to today ->
export team/goalie ratings, tonight's slate (if the NHL schedule is reachable),
recent results (for grading picks you log in the page) and the backtest report.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import urllib.request
import zlib

import numpy as np
import pandas as pd

import data
import engine
import odds
import prizepicks

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(HERE, "output")
SCHEDULE_API = "https://api-web.nhle.com/v1/schedule/{d}"
ROSTER_API = "https://api-web.nhle.com/v1/roster/{team}/current"


def season_end_year(today: dt.date) -> int:
    """NHL seasons start in October: Sept 2026 belongs to the season ending 2027."""
    return today.year + 1 if today.month >= 8 else today.year


def fetch_slate(today: dt.date):
    """Upcoming games for the next 7 days from the NHL schedule API. Best-effort:
    returns [] if the API can't be reached (the page then falls back to the matchup builder)."""
    try:
        req = urllib.request.Request(SCHEDULE_API.format(d=today.isoformat()),
                                     headers={"User-Agent": "qrob-goalie-model"})
        with urllib.request.urlopen(req, timeout=30) as r:
            js = json.load(r)
    except Exception as e:
        print(f"  [slate] schedule unavailable: {e}")
        return []
    games = []
    for day in js.get("gameWeek", []):
        for g in day.get("games", []):
            if g.get("gameType") not in (2, 3):
                continue
            games.append({
                "date": day.get("date"), "start": g.get("startTimeUTC"), "id": g.get("id"),
                "home": g["homeTeam"]["abbrev"], "away": g["awayTeam"]["abbrev"],
                "type": "P" if g.get("gameType") == 3 else "R",
                "state": g.get("gameState"),
            })
    return games


def team_table(tg: pd.DataFrame, st: engine.State, season: int):
    s = tg[tg.season == season]
    out = {}
    for team, x in s.groupby("team_abbrev"):
        n = len(x)
        cf, ca = x.cf.sum(), x.opp_cf.sum()
        xgf, xga = x.xgf.sum(), x.opp_xgf.sum()
        out[team] = {
            "gp": n,
            "sf": round(x.shots_on_goal.mean(), 2), "sa": round(x.opp_shots_on_goal.mean(), 2),
            "gf": round(x.goals.mean(), 2), "ga": round(x.opp_goals.mean(), 2),
            "cf_pct": round(cf / (cf + ca), 4) if cf + ca else None,
            "xgf_pct": round(xgf / (xgf + xga), 4) if xgf + xga else None,
            "block_pct": round(x.blocks_made.sum() / ca, 4) if ca else None,
            "pace": round((cf + ca) / n, 1),
            "pim": round(x.pim.mean(), 2), "opp_pim": round(x.opp_pim.mean(), 2),
            "rate_off": round(st.team_rate(st.off, team), 3),
            "rate_def": round(st.team_rate(st.dfn, team), 3),
        }
    # early in a season, teams that haven't played yet still need ratings
    # (limited to last season's teams so relocated franchises like ARI drop out)
    active = set(tg[tg.season >= season - 1].team_abbrev)
    for team in active - set(out):
        out[team] = {"gp": 0, "rate_off": round(st.team_rate(st.off, team), 3),
                     "rate_def": round(st.team_rate(st.dfn, team), 3)}
    return out


def goalie_table(starts: pd.DataFrame, st: engine.State, season: int):
    s = starts[starts.season == season]
    out = {}
    for gid, x in s.groupby("player_id"):
        mins = x.toi_min.sum()
        shots, saves, ga = x.shots_against.sum(), x.saves.sum(), x.goals_against.sum()
        xga = x.xga.sum() if "xga" in x else np.nan
        out[int(gid)] = {
            "gp": int(len(x)), "avg_sv": round(x.saves.mean(), 2),
            "sv_pct": round(saves / shots, 4) if shots else None,
            "ga60": round(ga / mins * 60, 3) if mins else None,
            "gsax60": round((xga - ga) / mins * 60, 3) if mins and not np.isnan(xga) else None,
            "rebound_pct": round(x.rebounds.sum() / shots, 4) if shots and "rebounds" in x else None,
            "sa60": round(shots / mins * 60, 2) if mins else None,
        }
    res = []
    for gid, name in st.g_name.items():
        hist = list(st.g_hist.get(gid, []))
        row = {"id": gid, "name": name, "team": st.g_team.get(gid),
               "sv": round(st.goalie_sv(gid), 4), "share": round(st.goalie_share(gid), 4),
               "l10": round(float(np.mean(hist)), 2) if hist else None,
               "last10": hist}
        row.update(out.get(gid, {"gp": 0}))
        res.append(row)
    return res


def fetch_rosters(teams):
    """Current goalies on each NHL roster: {team: [{"id", "name"}]}. Best-effort per team."""
    out = {}
    for team in sorted(teams):
        try:
            req = urllib.request.Request(ROSTER_API.format(team=team),
                                         headers={"User-Agent": "qrob-goalie-model"})
            with urllib.request.urlopen(req, timeout=30) as r:
                js = json.load(r)
        except Exception as e:
            print(f"  [roster] {team} unavailable: {e}")
            continue
        gs = []
        for p in js.get("goalies", []):
            first = (p.get("firstName") or {}).get("default", "")
            last = (p.get("lastName") or {}).get("default", "")
            gs.append({"id": int(p["id"]), "name": f"{first[:1]}. {last}".strip(". ")})
        if gs:
            out[team] = gs
    print(f"  [roster] goalies for {len(out)} teams")
    return out


def depth_charts(starts: pd.DataFrame, rosters: dict, n=12, preseason=False, prev=None):
    """Default starter order per team.

    With a current roster: only that team's rostered goalies, ranked by starts in
    the team's last n games (in-season form) and then by total starts this season
    for any team. Preseason, last spring's team usage says little once rosters
    have turned over, so goalies are ranked by last season's total starts alone
    (an offseason signing who was a #1 elsewhere ranks first). `prev` (last
    season's starts) breaks ties early in a season, before a team has played.
    Without one: the team's goalies by starts in its last n games.
    """
    s = starts.sort_values("game_date")
    season_starts = s.player_id.value_counts()
    prev_starts = prev.player_id.value_counts() if prev is not None else pd.Series(dtype=int)
    recent = {team: x.tail(n).player_id.value_counts() for team, x in s.groupby("team_abbrev")}
    charts = {}
    for team in set(recent) | set(rosters):
        if team in rosters:
            ids = [g["id"] for g in rosters[team]]
            rc = recent.get(team, pd.Series(dtype=int))
            if preseason:
                ids.sort(key=lambda i: (-int(season_starts.get(i, 0)), -int(rc.get(i, 0)), i))
            else:
                ids.sort(key=lambda i: (-int(rc.get(i, 0)), -int(season_starts.get(i, 0)),
                                        -int(prev_starts.get(i, 0)), i))
            charts[team] = ids
        else:
            # no roster for this team: drop goalies now rostered somewhere else
            elsewhere = {g["id"] for t, gs in rosters.items() if t != team for g in gs}
            charts[team] = [int(i) for i in recent[team].index if int(i) not in elsewhere]
    return charts


def _np(o):
    """json fallback for numpy scalars / NaN."""
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        return None if np.isnan(o) else float(o)
    if isinstance(o, np.bool_):
        return bool(o)
    raise TypeError(type(o))


def main():
    today = dt.datetime.now(dt.timezone.utc).date()
    cur = season_end_year(today)
    years = list(range(2024, cur + 1))
    print(f"Loading seasons {years} ...")
    tg, st_df = data.load_all(years, refresh=True)
    have = sorted(tg.season.unique())
    latest = int(have[-1])

    ppath = os.path.join(OUT, "params.json")
    p = engine.Params(**json.load(open(ppath))) if os.path.exists(ppath) else engine.Params()
    df, state = engine.run(tg, st_df, p)
    # Preseason: the new season hasn't started in the data yet, so apply the
    # same between-season regression the backtest uses.
    if latest < cur:
        state.new_season(cur)

    display_season = latest
    report = json.load(open(os.path.join(OUT, "backtest.json")))
    bt = pd.read_csv(os.path.join(OUT, "backtest_games.csv"))
    bt = bt[(bt.season == 2026) & (bt.edge.abs() >= 1.0)]

    goalies = goalie_table(st_df, state, display_season)
    slate = fetch_slate(today)
    teams = {g[k] for g in slate for k in ("home", "away")} or set(state.off)
    rosters = fetch_rosters(teams)
    lg_share = round(state.lg_share.s / state.lg_share.w, 4)
    # Current rosters fix offseason moves; goalies with no NHL starts get a
    # league-average profile so they still project.
    by_id = {g["id"]: g for g in goalies}
    for team, gs in rosters.items():
        for r in gs:
            if r["id"] in by_id:
                by_id[r["id"]]["team"] = team
            else:
                by_id[r["id"]] = {"id": r["id"], "name": r["name"], "team": team, "gp": 0,
                                  "sv": engine.LEAGUE_SV, "share": lg_share, "l10": None,
                                  "last10": [], "new": True}
                goalies.append(by_id[r["id"]])
    dk = odds.fetch(goalies)
    pp = prizepicks.fetch(goalies)
    # Goalies on the board we have no NHL history for get the same treatment.
    for r in pp:
        if r["goalie_id"] is None:
            gid = -zlib.crc32(r["name"].encode())
            if not any(g["id"] == gid for g in goalies):
                goalies.append({"id": gid, "name": r["name"], "team": r["team"], "gp": 0,
                                "sv": engine.LEAGUE_SV, "share": lg_share, "l10": None,
                                "last10": [], "new": True})
            r["goalie_id"] = gid

    recent = df[pd.to_datetime(df.date) >= pd.Timestamp(today) - pd.Timedelta(days=45)]
    payload = {
        "built": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "season": f"{cur - 1}-{str(cur)[2:]}",
        "display_season": f"{display_season - 1}-{str(display_season)[2:]}",
        "preseason": bool(latest < cur),
        "data_through": str(tg.game_date.max()),
        "params": p.to_dict(),
        "league": round(state.league(), 3),
        "lg_share": lg_share,
        "sd": report["sd"],
        "teams": team_table(tg, state, display_season),
        "goalies": goalies,
        "pp": pp,
        "pp_error": prizepicks.last_error,
        "dk": dk,
        "dk_error": odds.last_error,
        "odds_remaining": odds.remaining,
        "depth": depth_charts(st_df[st_df.season == display_season], rosters,
                              preseason=bool(latest < cur),
                              prev=st_df[st_df.season == display_season - 1]),
        "rosters_ok": len(rosters),
        "last_played": {k: str(v) for k, v in state.last_played.items()},
        "slate": slate,
        "results": [{"date": r.date, "goalie_id": int(r.goalie_id), "saves": int(r.saves)}
                    for r in recent.itertuples()],
        "backtest": {k: v for k, v in report.items() if k != "params"},
        "bt_games": json.loads(bt.to_json(orient="records")),
    }
    tpl = open(os.path.join(HERE, "template.html"), encoding="utf-8").read()
    html = tpl.replace("/*__DATA__*/null", json.dumps(payload, separators=(",", ":"), default=_np))
    with open(os.path.join(ROOT, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Wrote index.html ({len(html) / 1024:.0f} KB) | data through {payload['data_through']} "
          f"| slate games: {len(payload['slate'])} | DraftKings goalies: {len(dk)} "
          f"| PrizePicks goalies: {len(pp)}")


if __name__ == "__main__":
    main()
