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
import calibrate
import engine
import odds
import pricing
import prizepicks
import saves_dist
import sog
import starters
import linecombos
import moneypuck
import moneypuck_teams
import pick6
import players
import prices as dkp
import props_board
import sources
import slate as slate_mod
import tracker
import winners

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(HERE, "output")
SCHEDULE_API = "https://api-web.nhle.com/v1/schedule/{d}"
DEFUNCT = {"ARI"}                 # franchises no longer in the league (Arizona -> Utah)
ROSTER_API = "https://api-web.nhle.com/v1/roster/{team}/current"


def season_end_year(today: dt.date) -> int:
    """NHL seasons start in October: Sept 2026 belongs to the season ending 2027."""
    return today.year + 1 if today.month >= 8 else today.year


def fetch_slate(today: dt.date):
    """Games from yesterday (CT) for the next 7 days from the NHL schedule API; yesterday's only while
    still live (a late game past midnight CT). Best-effort: returns [] if the API can't be reached (the
    page then falls back to the matchup builder). `today` is the America/Chicago date."""
    try:
        req = urllib.request.Request(SCHEDULE_API.format(d=(today - dt.timedelta(days=1)).isoformat()),
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
    return [g for g in games if g["date"] >= today.isoformat() or g["state"] in slate_mod.LIVE]


def latest_final(today: dt.date) -> str | None:
    """Date of the most recent finished NHL game (schedule API), for the data-freshness check."""
    try:
        req = urllib.request.Request(SCHEDULE_API.format(d=(today - dt.timedelta(days=3)).isoformat()),
                                     headers={"User-Agent": "qrob-goalie-model"})
        with urllib.request.urlopen(req, timeout=30) as r:
            js = json.load(r)
    except Exception as e:
        print(f"  [freshness] schedule unavailable: {e}")
        return None
    done = [day.get("date") for day in js.get("gameWeek", []) for g in day.get("games", [])
            if g.get("gameType") in (2, 3) and g.get("gameState") in ("OFF", "FINAL")]
    return max(done) if done else None


def goal_rates(st: engine.State, team):
    return {k: round(st.goal_rate(tbl, team), 4) for k, tbl in
            (("gf", st.gf), ("ga", st.ga), ("xgf", st.xgf), ("xga", st.xga))}


def sog_export(teams, sst: sog.State, sp: sog.SogParams, skater_df: pd.DataFrame, pst: sog.State | None = None,
               combos: dict | None = None, slots: dict | None = None, R: players.Rosters | None = None):
    """Per-team skater list for the SOG and points props: current roster when we have it,
    otherwise players who played for the team in its last 25 games (wide enough
    to keep regulars who were hurt at the end of the season). Each player carries his shot rate
    (r60) and points rate (p60) per 60 and expected TOI; when DailyFaceoff line combos are in,
    his listed line / PP unit and, on a role change, a role-change badge and (only when the combination
    was confirmed within 6 hours) the adjusted TOI, capped at +/- 15% (linecombos.role_toi)."""
    out = {}
    recent = skater_df.sort_values("game_date")
    for team in sorted(teams):
        if team in ROSTER_SKATERS:
            players = ROSTER_SKATERS[team]
        else:
            last_games = recent[recent.team_abbrev == team].game_id.drop_duplicates().tail(25)
            r = recent[recent.game_id.isin(last_games) & (recent.team_abbrev == team)]
            players = [{"id": int(i), "name": sst.name.get(int(i), n), "pos": sst.posn.get(int(i), p)}
                       for i, n, p in r[["player_id", "player_name", "pos"]].drop_duplicates("player_id").values
                       if sst.team.get(int(i)) == team]
        rows = []
        for pl in players:
            pid, pos = pl["id"], pl["pos"]
            h = list(sst.hist.get(pid, []))
            row = {"id": pid, "name": sst.name.get(pid, pl["name"]), "pos": pos,
                   "r60": round(float(sst.rate60(pid, pos)), 3), "toi": round(float(sst.exp_toi(pid, pos)), 2),
                   "gp": len(h), "l10": h, "new": pid not in sst.shots}
            if pst is not None:
                row["p60"] = round(float(pst.rate60(pid, pos)), 3)
                row["ptoi"] = round(float(pst.exp_toi(pid, pos)), 2)
                row["pl10"] = [int(v) for v in pst.hist.get(pid, [])]
            rows.append(row)
        # recent slot from expected TOI rank within the team (forwards 3 per line, defence 2 per pair)
        for pos in ("F", "D"):
            ranked = sorted((r for r in rows if r["pos"] == pos), key=lambda r: -r["toi"])
            for i, r in enumerate(ranked):
                r["slot"] = linecombos.recent_slot(i + 1, pos)
        listed = (combos or {}).get(team, {})
        by_id = {}
        for c in listed.values():
            m = R.match(c["name"], team) if R is not None else {"player_id": None}
            if m["player_id"] is not None:
                by_id[m["player_id"]] = c
        for r in rows:
            c = by_id.get(r["id"]) if R is not None else listed.get(prizepicks.name_key(r["name"]))
            if not c:
                continue
            r["line"], r["pp"] = c.get("line"), c.get("pp")
            toi, changed, adjusted = linecombos.role_toi(r["toi"], r["line"], r.get("slot"), slots or {}, c.get("updated"))
            if changed:
                f = toi / r["toi"] if r["toi"] else 1.0
                r["role_change"] = f"{r['slot']}→{r['line']}"
                r["role_adjusted"] = bool(adjusted)
                r["toi"] = round(toi, 2)
                if "ptoi" in r:
                    r["ptoi"] = round(r["ptoi"] * f, 2)
        rows.sort(key=lambda r: -r["r60"] * r["toi"])
        out[team] = rows
    return out


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
            "rate_cf": round(st.corsi_rate(st.cf, team)[0], 3),
            "rate_ca": round(st.corsi_rate(st.ca, team)[0], 3),
            "rate_ff": round(st.fenwick_rate(st.ff, team)[0], 3),
            "rate_fa": round(st.fenwick_rate(st.fa, team)[0], 3),
            **goal_rates(st, team),
        }
    # early in a season, teams that haven't played yet still need ratings
    # (limited to last season's teams so relocated franchises like ARI drop out)
    active = set(tg[tg.season >= season - 1].team_abbrev) - DEFUNCT
    for team in active - set(out):
        out[team] = {"gp": 0, "rate_off": round(st.team_rate(st.off, team), 3),
                     "rate_def": round(st.team_rate(st.dfn, team), 3),
                     "rate_cf": round(st.corsi_rate(st.cf, team)[0], 3), "rate_ca": round(st.corsi_rate(st.ca, team)[0], 3),
                     "rate_ff": round(st.fenwick_rate(st.ff, team)[0], 3), "rate_fa": round(st.fenwick_rate(st.fa, team)[0], 3),
                     **goal_rates(st, team)}
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
        row = {"id": gid, "name": name, "team": None if st.g_team.get(gid) in DEFUNCT else st.g_team.get(gid),
               "sv": round(st.goalie_sv(gid), 4), "share": round(st.goalie_share(gid), 4),
               "l10": round(float(np.mean(hist)), 2) if hist else None,
               "last10": hist}
        row.update(out.get(gid, {"gp": 0}))
        res.append(row)
    return res


ROSTER_SKATERS: dict = {}


def fetch_rosters(R: players.Rosters):
    """Current goalies on each NHL roster ({team: [{"id", "name"}]}) from the rosters players.fetch pulled
    (live, or the last saved copy; box-score fallbacks are not treated as rosters). Skaters (forwards +
    defense) are collected into ROSTER_SKATERS the same way."""
    out = {}
    short = lambda p: f"{p['first'][:1]}. {p['last']}".strip(". ")
    for team, ps in R.teams.items():
        if R.source.get(team, "").startswith(("live", "saved")):
            gs = [{"id": p["id"], "name": short(p)} for p in ps if p["pos"] == "G"]
            if gs:
                out[team] = gs
            sk = [{"id": p["id"], "name": short(p), "pos": p["pos"]} for p in ps if p["pos"] in ("F", "D")]
            if sk:
                ROSTER_SKATERS[team] = sk
    print(f"  [roster] goalies for {len(out)} teams, skaters for {len(ROSTER_SKATERS)}")
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
        if team not in rosters and team not in recent:
            continue
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
            ids = [int(i) for i in recent[team].index]
            if prev is not None:  # early season: add last season's goalies for this team
                pt = prev[prev.team_abbrev == team].player_id.value_counts()
                ids += [int(i) for i in pt.index if int(i) not in ids]
            charts[team] = [i for i in ids if i not in elsewhere]
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


DIST = saves_dist.load(os.path.join(OUT, "saves_dist.json"))
PRICES = os.path.join(HERE, "data", "dk_prices.csv")
BOOK_PRICES = os.path.join(HERE, "data", "book_prices.csv")


def save_prices(dk_saves, dk_sog, dk_points=None):
    """Append this build's DraftKings prices (both sides) to the price history used for grading
    and calibration. Later snapshots of the same line replace earlier ones when read."""
    snap = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    # the pull's own fetch time (odds.fetched_at) and the game's start, so readers can take the last price
    # before puck drop (prices.last_pregame); a snapshot is stored only when the price changed (prices.append)
    snap = odds.fetched_at or snap
    row = lambda mk, r, team: {"market": mk, "date": r["date"], "name": r["name"], "team": team,
                               "teams": "/".join(r.get("teams", [])), "line": r["line"], "over": r.get("over"),
                               "under": r.get("under"), "snap": r.get("fetched_at") or snap, "start": r.get("start")}
    rows = [row("saves", r, r.get("team", "")) for r in dk_saves or []]
    rows += [row("sog", r, "") for r in dk_sog or []]
    rows += [row("points", r, "") for r in dk_points or []]
    if rows and odds.status == "fresh":       # never re-store a fallback (cached) pull as a new snapshot
        dkp.append(PRICES, rows)
    # every other sportsbook's line, same rule (a row only when the price moved), for the forward consensus check
    brows = [{"market": r["market"], "date": r["date"], "name": r["name"], "player_id": r.get("player_id"),
              "teams": "/".join(r.get("teams", [])), "book": r["book"], "line": r["line"], "over": r.get("over"),
              "under": r.get("under"), "snap": r.get("fetched_at") or snap, "start": r.get("start")} for r in odds.book_rows]
    if brows and odds.status == "fresh":
        dkp.append(BOOK_PRICES, brows, key=dkp.KEY + ["book"])


def saves_rows(df: pd.DataFrame, season: int) -> pd.DataFrame:
    """This season's walk-forward starts with the goalie's team win probability (game-winner model)."""
    x = df[df.season == season]
    if x.empty:
        return x
    W = json.load(open(os.path.join(OUT, "winners_params.json")))
    g = winners.games(df[df.season == season])
    ph, _, _ = winners.predict(g, W["w"], W["home"], W["ot_home"], W.get("x", 0))
    g = g.assign(p_home=ph)[["game_id", "home", "p_home"]]
    x = x.merge(g, on="game_id", how="left")
    x["p_win"] = np.where(x.team == x.home, x.p_home, 1 - x.p_home)
    return x


def saves_bias_now(df: pd.DataFrame, season: int, today) -> float:
    """Rolling saves bias (30-day half-life) from every graded start of this season and last: actual saves
    minus the walk-forward projection the page would have shown (game script included)."""
    rows = []
    for s_ in (season - 1, season):
        x = saves_rows(df, s_)
        if len(x):
            rows.append(x)
    if not rows:
        return 0.0
    x = pd.concat(rows)
    proj = [saves_dist.project(r.exp_sa, r.share, r.sv, r.p_win, DIST)["proj"] for r in x.itertuples()]
    return saves_dist.bias_now(pd.to_datetime(x.date).dt.strftime("%Y-%m-%d").values, x.saves.values - np.array(proj),
                               today, pricing.SAVES_BIAS_HL)


def live_legs(day_games, live) -> list[dict]:
    """Legs logged before puck drop for the slate day's started games, with the stat so far and HIT / MISS."""
    started = {str(g["id"]): g for g in day_games if g.get("state") in slate_mod.FINAL | slate_mod.LIVE}
    out = []
    for r in tracker._read_legs():
        g = started.get(str(r["game"]))
        if g is None:
            continue
        lv = (live.get(str(r["game"])) or {})
        st = (lv.get("players") or {}).get(str(r["player_id"]), {})
        v = st.get({"sog": "sog", "points": "points", "saves": "saves"}.get(r["market"], ""))
        out.append({k: r.get(k) for k in ("name", "team", "market", "line", "side", "verdict", "p", "source", "mult")}
                   | {"stat": v, "state": lv.get("state", g.get("state")),
                      "status": slate_mod.leg_status(r["market"], r["side"], float(r["line"]), v, lv.get("state", g.get("state")))})
    return out


def main():
    now = dt.datetime.now(dt.timezone.utc)
    today = slate_mod.ct_today(now)           # the page's day is America/Chicago, not UTC
    cur = season_end_year(today)
    years = list(range(2024, cur + 1))
    print(f"Loading seasons {years} ...")
    tg, st_df = data.load_all(years, refresh=True)
    mp_rep = moneypuck.verify(st_df)          # raises if MoneyPuck is missing or disagrees with the box scores
    tg = moneypuck_teams.with_attempts(tg)    # MoneyPuck score-adjusted Fenwick (engine uses it when it covers the season)
    have = sorted(tg.season.unique())
    latest = int(have[-1])

    ppath = os.path.join(OUT, "params.json")
    p = engine.Params.load(ppath)
    df, state = engine.run(tg, st_df, p)
    # Preseason: the new season hasn't started in the data yet, so apply the
    # same between-season regression the backtest uses.
    if latest < cur:
        state.new_season(cur)

    display_season = latest
    report = json.load(open(os.path.join(OUT, "backtest.json")))
    sp = sog.SogParams.load(os.path.join(OUT, "sog_params.json"))
    skater_df = sog.load(years)
    sog_rows, sst = sog.run(skater_df, sp, record_from=cur)   # this season's walk-forward SOG projections (calibration replay)
    pp_ = sog.SogParams.load(os.path.join(OUT, "points_params.json"))
    points_rows, pst = sog.run(skater_df, pp_, record_from=cur, stat="points")
    if latest < cur:
        sst.new_season(cur)
        pst.new_season(cur)
    bt = pd.read_csv(os.path.join(OUT, "backtest_games.csv"))
    bt = bt[(bt.season == 2026) & (bt.edge.abs() >= 1.0)]

    goalies = goalie_table(st_df, state, display_season)
    slate = fetch_slate(today)
    slate_day = slate_mod.slate_day(slate, now)
    teams = ({g[k] for g in slate for k in ("home", "away")} or set(state.off)) - DEFUNCT
    box_rosters = players.from_box(skater_df[skater_df.season == latest], st_df[st_df.season == latest])
    R = players.fetch(teams, box_rosters)
    rosters = fetch_rosters(R)
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
    dk = odds.fetch(goalies, R=R)
    pp = prizepicks.fetch(goalies)
    p6_rows, p6_stats = pick6.fetch(slate, R)
    # PrizePicks: its own API if it lets the build through, else its lines on The Odds API, else the last good board
    pp_props = prizepicks.props(slate, R, odds_rows=odds.pp_rows, odds_status=odds.status, odds_at=odds.fetched_at)
    if not pp:   # goalie saves feed (starters, saves table) from the same PrizePicks lines
        pp = [{"name": r["name"], "team": r["team"], "line": r["line"], "date": r["date"], "opp": None, "url": None,
               "goalie_id": r["player_id"], "source": "The Odds API"} for r in pp_props if r["market"] == "saves" and not r.get("alt")]
    # real per-source fetch times (never the build time): fresh this build, or the last good pull as a labelled fallback
    lines_at = dt.datetime.now(dt.timezone.utc)
    src_info = {"pick6": sources.info(pick6.fetch_status, pick6.fetched_at, lines_at, None if pick6.status == "ok" else pick6.status),
                "dk": sources.info(odds.status, odds.fetched_at, lines_at, odds.last_error),
                "pp": sources.info(prizepicks.props_status, prizepicks.props_fetched_at, lines_at,
                                   None if prizepicks.status == "ok" or (pp_props and prizepicks.last_js is None and odds.status == "fresh")
                                   else prizepicks.last_error)}
    if prizepicks.last_js is None and odds.pp_rows:
        src_info["pp"]["via"] = "The Odds API"
    starter_rows = starters.fetch(goalies, sorted({g["date"] for g in slate}))
    combos = linecombos.fetch({g[k] for g in slate for k in ("home", "away")} - DEFUNCT)
    sv_rows = saves_rows(df, cur)
    saves_bias = round(saves_bias_now(df, cur, today), 3)
    slots = linecombos.slot_toi(skater_df, latest)
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
        "built": now.strftime("%Y-%m-%d %H:%M UTC"),
        "built_iso": now.isoformat(timespec="seconds"),
        "sources": src_info, "sources_at": lines_at.isoformat(timespec="seconds"), "stale_min": sources.STALE_MIN,
        "slate_day": slate_day,
        "saves_bias": saves_bias,
        "moneypuck": mp_rep,
        "rosters_status": players.status, "roster_source": R.source,
        "pick6_status": pick6.status, "pick6_stats": p6_stats,
        "dk_match": odds.match_counts,
        "season": f"{cur - 1}-{str(cur)[2:]}",
        "display_season": f"{display_season - 1}-{str(display_season)[2:]}",
        "preseason": bool(latest < cur),
        "data_through": str(tg.game_date.max()),
        "latest_final": latest_final(today),
        # the shots-against weights actually in use (MoneyPuck Fenwick set, or our Corsi set as the fallback)
        "params": {**p.to_dict(), **state.weights(), "sa_mode": state.mode},
        "league": round(state.league(), 3),
        "lg_cf": round(state.lg_cf.s / state.lg_cf.w, 3),
        "lg_ff": round(state.lg_ff.s / state.lg_ff.w, 3),
        "moneypuck_teams": {"sa_mode": state.mode, **(json.load(open(os.path.join(moneypuck_teams.DIR, "status.json")))
                                                      if os.path.exists(os.path.join(moneypuck_teams.DIR, "status.json")) else {})},
        "lg_share": lg_share,
        "sd": report["sd"],
        "teams": team_table(tg, state, display_season),
        "goalies": goalies,
        "pp": pp,
        "pp_error": prizepicks.last_error,
        "pp_status": prizepicks.status,
        "starters": starter_rows,
        "starters_status": starters.status,
        "sog": {"params": sp.to_dict(), "players": sog_export(teams, sst, sp, skater_df, pst, combos, slots, R),
                "opp": {t: round(float(sst.opp_factor(t)), 4) for t in sst.team_sa if t not in DEFUNCT},
                # (the old proxy-line SOG backtest, output/sog_backtest.json, is no longer shown: synthetic lines and
                # stale parameters; the Backtest tab's rule record replays the live rule on real graded lines)
                "team": {t: round(float(sst.team_factor(t)), 4) for t in sst.team_for if t not in DEFUNCT}},
        "points": {"params": pp_.to_dict(),
                   "opp": {t: round(float(pst.opp_factor(t)), 4) for t in pst.team_sa if t not in DEFUNCT},
                   "team": {t: round(float(pst.team_factor(t)), 4) for t in pst.team_for if t not in DEFUNCT}},
        "lines_status": linecombos.status, "slot_toi": slots,
        "win": {"params": json.load(open(os.path.join(OUT, "winners_params.json"))),
                "lg_goals": round(state.lg_goals.s / state.lg_goals.w, 4),
                "backtest": json.load(open(os.path.join(OUT, "winners_backtest.json")))},
        "dk": dk,
        "dk_sog": [{"name": r["name"], "teams": r["teams"], "date": r["date"], "line": r["line"], "player_id": r.get("player_id"),
                    "team": r.get("team"), "over": r.get("over"), "under": r.get("under"), "fetched_at": r.get("fetched_at")} for r in odds.sog_rows],
        "dk_points": [{"name": r["name"], "teams": r["teams"], "date": r["date"], "line": r["line"], "player_id": r.get("player_id"),
                       "team": r.get("team"), "over": r.get("over"), "under": r.get("under"), "fetched_at": r.get("fetched_at")} for r in odds.points_rows],
        # the other sportsbooks' two-sided lines (odds.OTHER_BOOKS, same request, no extra credits): the market
        # reference where DraftKings doesn't price a player's line, and logged for a forward consensus check
        "books": [{"market": r["market"], "player_id": r.get("player_id"), "line": r["line"], "book": r["book"],
                   "over": r.get("over"), "under": r.get("under")} for r in odds.book_rows if r.get("match") == "MATCHED"],
        "odds_books": odds.books_used,
        "rosters": {t: [[p["id"], p["first"], p["last"], p["pos"]] for p in ps] for t, ps in R.teams.items() if t in teams},
        "ml": odds.ml_rows,
        "dist": DIST,
        "pricing": pricing.config(),
        "dk_error": odds.last_error,
        "odds_remaining": odds.remaining, "odds_costs": odds.last_costs[:20],
        "depth": depth_charts(st_df[st_df.season == display_season], rosters,
                              preseason=bool(latest < cur),
                              prev=st_df[st_df.season == display_season - 1]),
        "rosters_ok": len(rosters),
        "last_played": {k: str(v) for k, v in state.last_played.items()},
        # who started each team's most recent game (for back-to-back defaults)
        "last_starter": {t: int(x.sort_values("game_date").player_id.iloc[-1])
                         for t, x in st_df.groupby("team_abbrev")},
        "slate": slate,
        "results": [{"date": r.date, "goalie_id": int(r.goalie_id), "saves": int(r.saves)}
                    for r in recent.itertuples()],
        "backtest": {k: v for k, v in report.items() if k != "params"},
        "bt_games": json.loads(bt.to_json(orient="records")),
    }
    save_prices(dk, odds.sog_rows, odds.points_rows)
    # grade finished games, refit calibration on everything graded, then freeze tonight's calls
    try:
        payload["tracking"] = tracker.grade([cur], today)
    except Exception as e:  # never let grading break the dashboard
        print(f"  [tracker] grading failed: {e}")
        payload["tracking"] = json.load(open(tracker.OUT)) if os.path.exists(tracker.OUT) else None
    try:
        payload["calib"] = calibrate.fit(tracker._read_log(), sv_rows, DIST,
                                         pd.read_csv(PRICES) if os.path.exists(PRICES) else None,
                                         sog_rows=sog_rows, sog_prm=sp, points_rows=points_rows, points_prm=pp_)
        with open(os.path.join(OUT, "calibration.json"), "w") as f:
            json.dump(payload["calib"], f, indent=1, default=_np)
    except Exception as e:
        print(f"  [calibrate] failed: {e}")
        payload["calib"] = json.load(open(os.path.join(OUT, "calibration.json"))) \
            if os.path.exists(os.path.join(OUT, "calibration.json")) else None
    # tonight's board: every Pick6 line (DK as fallback), one verdict per player and market; every leg shown is logged
    try:
        payload["board"] = props_board.build(payload, p6_rows + pp_props, now,
                                            review=((p6_stats or {}).get("review") or []) + prizepicks.props_review)
        print(f"  [board] {payload['board']['counts']}")
    except Exception as e:  # never let the board break the dashboard
        import traceback; traceback.print_exc()
        payload["board"] = {"rows": [], "plays": [], "counts": {}, "error": str(e)}
    try:
        tracker.log_legs(payload["board"]["rows"], payload["built_iso"])
    except Exception:  # a logging failure must not blank the board
        import traceback; traceback.print_exc()
    payload["legs"] = tracker.legs_summary()
    # started games on the slate day: live / final stats and HIT / MISS for the legs logged before puck drop
    day_games = [g for g in slate if g["date"] == slate_day]
    live = slate_mod.fetch_live(day_games)
    payload["live"] = {"status": slate_mod.status, "games": live, "legs": live_legs(day_games, live)}
    print(f"  [tracker] snapshot dates: {tracker.snapshot(payload)}")
    tpl = open(os.path.join(HERE, "template.html"), encoding="utf-8").read()
    html = tpl.replace("/*__DATA__*/null", json.dumps(payload, separators=(",", ":"), default=_np))
    with open(os.path.join(ROOT, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Wrote index.html ({len(html) / 1024:.0f} KB) | data through {payload['data_through']} "
          f"| slate games: {len(payload['slate'])} | DraftKings goalies: {len(dk)} "
          f"| PrizePicks goalies: {len(pp)}")


if __name__ == "__main__":
    main()
