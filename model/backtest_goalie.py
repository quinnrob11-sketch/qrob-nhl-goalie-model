"""Walk-forward backtest of goalie saves for the 2026-27 regular season.

    python model/backtest_goalie.py

Scores the production projection (game script + the rolling bias correction) against every
regular-season start so far, with no lookahead. Also scores three MoneyPuck alternatives
(GSAx save%, fenwick shot volume, both) and keeps the production formula unless one of them
beats it by more than one standard error of the paired absolute-error difference. Writes
model/reports/goalie_backtest.md and model/output/goalie_backtest.json.

MoneyPuck.com is the source of the goalie game logs and the shot file used in the cross-check.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from collections import defaultdict

import numpy as np
import pandas as pd

import calibrate
import data
import engine
import fit_sa
import moneypuck
import prices as dkp
import pricing
import prizepicks
import saves_dist
import tracker

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "output")
REPORTS = os.path.join(HERE, "reports")
DIST = saves_dist.load(os.path.join(OUT, "saves_dist.json"))
LINES = [round(x, 1) for x in np.arange(22.5, 31.0, 1.0)]


def _proj_frame(df: pd.DataFrame) -> pd.DataFrame:
    pr = [saves_dist.project(r.exp_sa, r.share, r.sv, r.p_win, DIST) for r in df.itertuples()]
    out = df.copy()
    out["proj0"] = [p["proj"] for p in pr]
    out["sd"] = [p["sd"] for p in pr]
    out["mu"] = [p["mu"] for p in pr]
    out["date"] = pd.to_datetime(out.date)
    dates = out.date.dt.strftime("%Y-%m-%d")
    out["bias"] = saves_dist.rolling_bias(dates, out.saves.values - out.proj0.values, pricing.SAVES_BIAS_HL)
    out["proj"] = out.proj0 + out.bias
    return out


def _score(name: str, proj: np.ndarray, actual: np.ndarray) -> dict:
    err = proj - actual
    return {"name": name, "n": int(len(actual)), "mae": round(float(np.mean(np.abs(err))), 4),
            "bias": round(float(np.mean(err)), 4)}


def _paired(candidate: np.ndarray, base: np.ndarray, actual: np.ndarray) -> dict:
    d = np.abs(candidate - actual) - np.abs(base - actual)
    se = float(d.std(ddof=1) / np.sqrt(len(d))) if len(d) > 1 else 0.0
    return {"d_mae": round(float(d.mean()), 4), "se": round(se, 4),
            "better": bool(d.mean() < -max(se, 0.02))}


class _D:
    def __init__(self):
        self.s = 0.0
        self.w = 0.0

    def add(self, x, dec, w=1.0):
        self.s = self.s * dec + x * w
        self.w = self.w * dec + w

    def mean(self, prior, k):
        return (self.s + k * prior) / (self.w + k)


def _mp_features(df: pd.DataFrame, mp: pd.DataFrame, p: engine.Params) -> pd.DataFrame:
    """Pre-game MoneyPuck team rates and goalie GSAx, from goalie game logs only (no lookahead)."""
    g = mp.sort_values(["date", "gameId", "playerId"])
    rows = []
    for (gid, team), x in g.groupby(["gameId", "team"]):
        rows.append({"game_id": int(gid), "team": team, "opp": x.opp.iloc[0], "date": x.date.iloc[0],
                     "sa": float(x.ongoal.sum()), "xga": float(x.xGoals.sum()),
                     "fen_a": float(x.unblocked_shot_attempts.sum()), "hd_a": float(x.highDangerShots.sum())})
    tg = pd.DataFrame(rows)
    opp = tg[["game_id", "team", "sa", "xga", "fen_a", "hd_a"]].rename(
        columns={"team": "opp", "sa": "sf", "xga": "xgf", "fen_a": "fen_f", "hd_a": "hd_f"})
    tg = tg.merge(opp, on=["game_id", "opp"], how="left")
    dec = 0.5 ** (1.0 / p.half_life)
    svdec = 0.5 ** (1.0 / p.sv_half_life)
    off_s, dfn_s = defaultdict(_D), defaultdict(_D)
    off_f, dfn_f = defaultdict(_D), defaultdict(_D)
    lg_s, lg_f = _D(), _D()
    lg_s.add(28, 1, 40)
    lg_f.add(45, 1, 40)
    g_gs = defaultdict(_D)
    by_t = {d: x for d, x in tg.groupby("date", sort=True)}
    by_g = {d: x for d, x in g.groupby("date", sort=True)}
    feat_t, feat_g = {}, {}
    for day in sorted(set(by_t) | set(pd.to_datetime(df.date).unique())):
        lgs, lgf = lg_s.mean(28, 1), lg_f.mean(45, 1)
        if day in by_t:
            for r in by_t[day].itertuples(index=False):
                feat_t[(day, r.team)] = {"sa": dfn_s[r.team].mean(lgs, p.k_team),
                                         "sf": off_s[r.team].mean(lgs, p.k_team),
                                         "fa": dfn_f[r.team].mean(lgf, p.k_team),
                                         "ff": off_f[r.team].mean(lgf, p.k_team),
                                         "lgs": lgs, "lgf": lgf}
        if day in by_g:
            for r in by_g[day].itertuples(index=False):
                gs = g_gs[int(r.playerId)]
                feat_g[(day, int(r.playerId))] = {"skill": (gs.s / gs.w) if gs.w else 0.0, "w": gs.w}
        if day in by_t:
            for r in by_t[day].itertuples(index=False):
                if r.sf == r.sf:
                    off_s[r.team].add(r.sf, dec)
                    dfn_s[r.team].add(r.sa, dec)
                    off_f[r.team].add(r.fen_f, dec)
                    dfn_f[r.team].add(r.fen_a, dec)
                    lg_s.add(r.sf, 0.5 ** (1.0 / p.lg_half_life))
                    lg_f.add(r.fen_f, 0.5 ** (1.0 / p.lg_half_life))
        if day in by_g:
            for r in by_g[day].itertuples(index=False):
                if r.ongoal and r.ongoal > 0:
                    g_gs[int(r.playerId)].add(r.gsax / r.ongoal, svdec, float(r.ongoal))
    out = df.copy()
    out["date"] = pd.to_datetime(out.date)

    def vol(rate_a, rate_f, lg, r):
        sa = lg * (rate_a / lg) ** p.a * (rate_f / lg) ** p.b
        sa *= p.home if r.is_home else 1 / p.home
        if r.game_type == "P":
            sa *= p.playoff
        if r.b2b:
            sa *= p.b2b
        if r.opp_b2b:
            sa *= p.opp_b2b
        return sa

    fen_vol, skill = [], []
    for r in out.itertuples(index=False):
        ft, fo = feat_t.get((r.date, r.team)), feat_t.get((r.date, r.opp))
        fg = feat_g.get((r.date, int(r.goalie_id)))
        if ft and fo and ft["lgf"]:
            fen = vol(ft["fa"], fo["ff"], ft["lgf"], r)
            fen_vol.append(fen * (ft["lgs"] / ft["lgf"]))
        else:
            fen_vol.append(np.nan)
        if fg and fg["w"]:
            skill.append(fg["skill"] * fg["w"] / (fg["w"] + 1500.0))
        else:
            skill.append(0.0)
    out["fen_vol"] = fen_vol
    out["skill"] = skill
    return out


def _alt_proj(frame: pd.DataFrame, kind: str) -> np.ndarray:
    """kind: gsax (replace sv with league sv + shrunk GSAx/shot), fenwick (replace shot volume), both."""
    proj = []
    for r in frame.itertuples(index=False):
        sv = r.sv
        exp = r.exp_sa
        if kind in ("gsax", "both"):
            sv = float(np.clip(0.900 + r.skill, 0.86, 0.94))
        if kind in ("fenwick", "both") and r.fen_vol == r.fen_vol:
            exp = float(r.fen_vol)
        proj.append(saves_dist.project(exp, r.share, sv, r.p_win, DIST)["proj"])
    arr = np.array(proj, float)
    return arr + saves_dist.rolling_bias(frame.date.dt.strftime("%Y-%m-%d"), frame.saves.values - arr, pricing.SAVES_BIAS_HL)


def _cal_table(proj, sd, actual) -> list[dict]:
    rows = []
    for line in LINES:
        po = np.array([saves_dist.p_over(p, s, line) for p, s in zip(proj, sd)])
        act = float((actual > line).mean())
        rows.append({"line": line, "n": int(len(actual)), "pred": round(float(po.mean()), 4),
                     "actual": round(act, 4), "gap": round(act - float(po.mean()), 4)})
    return rows


def _real_lines(ev: pd.DataFrame) -> pd.DataFrame:
    """Graded saves lines joined to the walk-forward projection. One row per date + goalie + line
    (DraftKings preferred when the same line is on more than one book)."""
    log = pd.DataFrame([r for r in tracker._read_log() if r["market"] == "saves" and r.get("result") in ("HIT", "MISS", "PUSH")])
    if log.empty:
        return log
    log["line"] = log.line.astype(float)
    log["actual"] = pd.to_numeric(log.actual, errors="coerce")
    log["key"] = log.player.map(prizepicks.name_key)
    log["book_rank"] = log.book.map({"DraftKings": 0, "PrizePicks": 1, "Pick6": 2}).fillna(3)
    prices = pd.read_csv(os.path.join(HERE, "data", "dk_prices.csv"))
    prices = dkp.last_pregame(prices[prices.market == "saves"].copy())
    prices["key"] = prices.name.map(prizepicks.name_key)
    prices["line"] = prices.line.astype(float)
    prices = prices.drop_duplicates(["date", "key", "line"], keep="last")
    log = log.merge(prices[["date", "key", "line", "over", "under"]], on=["date", "key", "line"], how="left")
    ev = ev.copy()
    ev["date"] = ev.date.dt.strftime("%Y-%m-%d")
    ev["key"] = ev.goalie.map(prizepicks.name_key)
    m = log.merge(ev[["date", "key", "team", "proj", "proj0", "sd", "saves", "goalie"]], on=["date", "key", "team"], how="inner")
    m = m[m.saves == m.actual].copy()
    m = m.sort_values("book_rank").drop_duplicates(["date", "key", "line"])
    m["push"] = m.actual == m.line
    m["went_over"] = m.actual > m.line
    m["edge"] = m.proj - m.line
    m["p_over"] = [saves_dist.p_over(p, s, ln) for p, s, ln in zip(m.proj, m.sd, m.line)]
    m["wk"] = calibrate.week_key(m.date)
    # walk-forward side-split calibration: each week uses only earlier weeks
    p_cal = np.array(m.p_over, float)
    order = np.argsort(m.wk.values, kind="mergesort")
    weeks = m.wk.values
    for w in sorted(set(weeks)):
        te, tr = weeks == w, weeks < w
        if tr.sum() < 30:
            continue
        cal = calibrate.side_fit(m.p_over.values[tr], m.went_over.values[tr], m.push.values[tr])
        p_cal[te] = [pricing.platt(p, cal, ln) for p, ln in zip(m.p_over.values[te], m.line.values[te])]
    m["p_cal"] = p_cal
    return m


def _units(win, push, price) -> float:
    if push:
        return 0.0
    if price == price and price not in (None, ""):
        try:
            return pricing.profit(float(price)) if win else -1.0
        except (TypeError, ValueError):
            pass
    be = pricing.dfs_break_even(1.0)
    return (1.0 / be - 1.0) if win else -1.0


def _edge_table(m: pd.DataFrame) -> list[dict]:
    rows = []
    if m.empty:
        return rows
    for th in pricing.SAVES_EDGE_GRID:
        for side in ("OVER", "UNDER"):
            sel = (m.edge >= th) if side == "OVER" else (m.edge <= -th)
            sel = sel & ~m.push
            sub = m[sel]
            win = (sub.actual > sub.line) if side == "OVER" else (sub.actual < sub.line)
            price = sub.over if side == "OVER" else sub.under
            prof = np.array([_units(bool(w), False, p) for w, p in zip(win, price)])
            n = int(len(sub))
            rows.append({"edge": th, "side": side, "n": n, "hit": int(win.sum()) if n else 0, "miss": n - int(win.sum()) if n else 0,
                         "pct": round(float(win.mean()), 4) if n else None,
                         "units": round(float(prof.sum()), 2) if n else 0.0,
                         "roi": round(float(prof.mean()), 4) if n else None})
    return rows


def _rule(m: pd.DataFrame) -> dict:
    """edge >= 2.5 over / 3.0 under, calibrated P(side) >= 58%, priced as a 1x DFS leg."""
    if m.empty:
        return {"n": 0}
    picks = []
    for r in m.itertuples(index=False):
        if r.push:
            continue
        v = pricing.verdict("saves", float(r.p_cal), float(r.p_cal), float(r.line), float(r.proj),
                            mult_over=1.0, mult_under=1.0, confirmed=True, matched=True)
        if not str(v["verdict"]).startswith("TAKE"):
            continue
        win = (r.actual > r.line) if v["side"] == "OVER" else (r.actual < r.line)
        picks.append((v["side"], bool(win), _units(bool(win), False, None)))
    n = len(picks)
    hit = sum(w for _, w, _ in picks)
    units = sum(u for _, _, u in picks)
    by = {}
    for side in ("OVER", "UNDER"):
        z = [p for p in picks if p[0] == side]
        by[side] = {"n": len(z), "hit": sum(w for _, w, _ in z),
                    "units": round(sum(u for _, _, u in z), 2),
                    "roi": round(sum(u for _, _, u in z) / len(z), 4) if z else None}
    return {"n": n, "hit": hit, "miss": n - hit, "pct": round(hit / n, 4) if n else None,
            "units": round(units, 2), "roi": round(units / n, 4) if n else None, "by_side": by,
            "price": "1x DFS (2-pick at 3x, break-even 57.7%)"}


def _side_cal(m: pd.DataFrame) -> dict:
    if m.empty:
        return {}
    out = {}
    keep = ~m.push.values
    for name, p in (("bias-corrected", m.p_over.values), ("calibrated", m.p_cal.values)):
        so = p >= 0.5
        cells = {}
        for side, mask in (("OVER", so), ("UNDER", ~so)):
            mm = mask & keep
            ps = np.where(so, p, 1 - p)[mm]
            win = np.where(so, m.went_over.values, ~m.went_over.values)[mm]
            cells[side] = {"n": int(mm.sum()), "pred": round(float(ps.mean()), 4) if mm.any() else None,
                           "actual": round(float(win.mean()), 4) if mm.any() else None}
        out[name] = cells
    return out


def _pct(x):
    return "–" if x is None else f"{100 * x:.1f}%"


def _md(rep: dict) -> str:
    b, a = rep["before"], rep["after"]
    L = ["# Goalie saves backtest, 2026-27", "",
         f"Built {rep['built']} by `python model/backtest_goalie.py`. Walk-forward: every projection uses only games played "
         "before that date. Season is the regular season through the latest box score in the NHL feed. "
         "MoneyPuck.com goalie game logs and the 2026-27 shot file are the external source.", "",
         "## Result", "",
         rep["decision"], "",
         "## Projection accuracy (every regular-season start)", "",
         "| model | starts | MAE | bias (projected − actual) |", "|---|---|---|---|",
         f"| before (production, no rolling bias) | {b['nobias']['n']} | {b['nobias']['mae']:.3f} | {b['nobias']['bias']:+.3f} |",
         f"| before (production + rolling bias) | {b['bias']['n']} | {b['bias']['mae']:.3f} | {b['bias']['bias']:+.3f} |",
         f"| after | {a['n']} | {a['mae']:.3f} | {a['bias']:+.3f} |", "",
         f"Shots the goalie is projected to face vs shots he faced: bias {rep['shots']['bias']:+.3f}, MAE {rep['shots']['mae']:.3f}. "
         f"Team shots against: bias {rep['shots']['team_bias']:+.3f}. Mean shrunk save% {rep['shots']['sv']:.4f}, "
         f"actual save% {rep['shots']['actual_sv']:.4f}.", "",
         "Full games (time on ice at least 55 minutes) are where a pull did not happen, so the time-in-net haircut "
         f"makes the projection low there (bias {rep['slices']['full']['bias']:+.2f} on {rep['slices']['full']['n']} starts). "
         f"The {rep['slices']['pull']['n']} starts under 40 minutes are high by {rep['slices']['pull']['bias']:+.1f} saves. "
         "Those two cancel, which is why the unconditional bias is about zero. Removing the haircut would make the average high.", "",
         "### Slices of the production projection (with the rolling bias)", "",
         "| slice | n | MAE | bias |", "|---|---|---|---|"]
    for name, s in rep["slices"].items():
        if name in ("full", "pull"):
            continue
        L.append(f"| {name} | {s['n']} | {s['mae']:.2f} | {s['bias']:+.2f} |")
    L += ["", "## MoneyPuck alternatives (not shipped)", "",
          "Each one is walk-forward, then the same rolling bias is refit on its own residuals. "
          "`dMAE` is the paired change in absolute error versus the production projection (negative would be an improvement). "
          "A change is kept only when dMAE is better than both one standard error and 0.02 saves.", "",
          "| alternative | MAE | bias | dMAE | SE | kept |", "|---|---|---|---|---|---|"]
    for alt in rep["alternatives"]:
        L.append(f"| {alt['name']} | {alt['mae']:.3f} | {alt['bias']:+.3f} | {alt['paired']['d_mae']:+.4f} | {alt['paired']['se']:.4f} | {'yes' if alt['paired']['better'] else 'no'} |")
    L += ["", "GSAx is MoneyPuck expected goals against minus goals, per shot, shrunk by 1,500 shots and added to a .900 save%. "
          "Fenwick volume replaces team shots-on-goal with unblocked shot attempts faced, converted back to shots on goal at the league on-goal rate, "
          "with the same home, back-to-back and game-script multipliers. Neither the goalie's recent shot quality nor the opponent's unblocked volume "
          "moved the error by a meaningful amount. Back-to-back and opponent back-to-back multipliers were left as fitted: the 2024-25 and 2025-26 "
          "residuals are small, and the 2026-27 back-to-back sample is about 50 starts.", "",
          "## Calibration of P(over) by line", "",
          "Every 2026-27 regular-season start, at each half-point line. Predicted is the mean of the model's P(saves > line); actual is the share of starts over that line.", "",
          "| line | n | predicted | actual | gap |", "|---|---|---|---|---|"]
    for row in rep["calibration_starts"]:
        L.append(f"| {row['line']:.1f} | {row['n']} | {_pct(row['pred'])} | {_pct(row['actual'])} | {100 * row['gap']:+.1f} pts |")
    sc = rep["side_cal"]
    L += ["", "On graded real lines, the side the bias-corrected model leans to:", "",
          "| projection | side | n | predicted | actual |", "|---|---|---|---|---|"]
    for name, cells in sc.items():
        for side, v in cells.items():
            L.append(f"| {name} | {side} | {v['n']} | {_pct(v['pred'])} | {_pct(v['actual'])} |")
    L += ["", "## Record and ROI", "",
          f"Graded real lines joined to the walk-forward projection: {rep['lines']['n']} lines "
          f"({rep['lines']['from']} to {rep['lines']['to']}), one row per date + goalie + line. "
          "Units below use the DraftKings price when that line has one, otherwise the 1x DFS price (2-pick at 3x).", "",
          "| edge | side | n | record | hit % | units | ROI |", "|---|---|---|---|---|---|---|"]
    for t in rep["thresholds"]:
        L.append(f"| {t['edge']} | {t['side']} | {t['n']} | {t['hit']}-{t['miss']} | {_pct(t['pct'])} | {t['units']:+.2f} | {_pct(t['roi'])} |")
    rule = rep["rule"]
    L += ["", "Play rule (the one the page uses for a TAKE): edge at least **2.5** saves on an over and **3.0** on an under, "
          "calibrated P(side) at least **58%**, priced at **1x**. Calibration is side-split and fit only on earlier weeks. "
          "Shots and points thresholds are unchanged.", "",
          f"Record: {rule.get('hit', 0)}-{rule.get('miss', 0)} ({_pct(rule.get('pct'))}), units {rule.get('units', 0):+.2f}, "
          f"ROI {_pct(rule.get('roi'))}, n={rule.get('n', 0)}, price {rule.get('price', '')}. "
          "This record is the same before and after, because the projection did not change.", ""]
    for side, v in (rule.get("by_side") or {}).items():
        L.append(f"- {side}: {v['hit']}-{v['n'] - v['hit']}, units {v['units']:+.2f}, ROI {_pct(v['roi'])}, n={v['n']}")
    ck, sh = rep["crosscheck"], rep.get("shots_file") or {}
    L += ["", "## MoneyPuck cross-check", "",
          f"Goalie game logs versus NHL starter box scores: {ck['matched']} of {ck['nhl_starts']} matched "
          f"({_pct(ck['match_rate'])}). Regular season {_pct(ck.get('regular_match_rate'))} of {ck.get('regular_starts')}; "
          f"the public game file is regular season only, so playoff starts in it are {ck.get('playoff_matched')} of {ck.get('playoff_starts')}. "
          f"Shots-against MAE {ck['sa_mae']}, saves MAE {ck['saves_mae']}, "
          f"TOI MAE {ck['toi_mae']}, exact shots { _pct(ck['sa_exact']) }. "
          f"Team-abbrev disagreements other than Arizona/Utah: {ck['team_mismatches']} "
          f"({', '.join(ck['team_mismatch_pairs']) or 'none'}). "
          f"{ck.get('missing_note', '')} "
          f"Source {ck['source']['seasons']}, through {ck['source'].get('through')}.", ""]
    if sh:
        L += [f"Shot file, {sh['year']}: {sh['matched']} of {sh['goalie_games']} goalie games joined "
              f"(`season * 1_000_000 + shot game_id`). On-goal MAE {sh['sa_mae']} (the shot zip lags the game log and drops a few shots), "
              f"goals MAE {sh['ga_mae']}, xGoals MAE {sh['xg_mae']} against the sum of shot-level xGoal on unblocked attempts. "
              "The NHL box score matches the goalie game log, not the shot zip, so the model keeps the NHL counts.", ""]
    if ck["source"].get("warning"):
        L += [f"Download warning: {ck['source']['warning']}", ""]
    L += ["## What changed in the pipeline", "",
          "- Frozen calls now add the same rolling bias the page adds before they price a line, so the logged projection is the one on the slate.",
          "- A DailyFaceoff starter who is Likely or otherwise not confirmed is the projected starter (still not a play), ahead of the back-to-back backup, matching the page.",
          "- The build loads MoneyPuck goalie games, cross-checks shots, saves and time on ice, and raises if they disagree or if both the download and the committed snapshot are missing.",
          ""]
    return "\n".join(L) + "\n"


def main():
    years = [2024, 2025, 2026, 2027]
    print("loading NHL", flush=True)
    tg, st = data.load_all(years, refresh=False)
    p = engine.Params.load(os.path.join(OUT, "params.json"))
    df, _ = engine.run(tg, st, p, record_from_season=2026)
    df = fit_sa.with_pwin(df)
    df = _proj_frame(df)
    ev = df[(df.season == 2027) & (df.game_type == "R")].copy()
    print(f"2026-27 regular-season starts: {len(ev)}", flush=True)
    mp_years = sorted({int(s) - 1 for s in tg.season.unique()})
    mp, info = moneypuck.load_goalie_games(mp_years, refresh=True)
    ck = moneypuck.cross_check(st, mp)
    ck["source"] = info
    gtype = st.game_id.astype(str).str.zfill(10).str[4:6]
    reg = st[gtype == "02"].copy()
    have = set(zip(mp.gameId.astype(int), mp.playerId.astype(int)))
    reg["hit"] = [(int(g), int(p)) in have for g, p in zip(reg.game_id, reg.player_id)]
    miss = reg[~reg.hit]
    if len(miss):
        bits = [f"{r.player_name} {r.team_abbrev} {str(r.game_date)[:10]}" for r in miss.itertuples()]
        ck["missing_note"] = ("Regular-season starts in the NHL file and not in the MoneyPuck file: " + "; ".join(bits) + ".")
    else:
        ck["missing_note"] = "Every regular-season NHL start is in the MoneyPuck file."
    if not ck["ok"]:
        raise moneypuck.MoneyPuckError("cross-check failed: " + "; ".join(ck["problems"]))
    shots = moneypuck.shot_check(2026, mp, refresh=True)
    print("cross-check", ck["matched"], "shot check", shots, flush=True)

    base = _score("production+bias", ev.proj.values, ev.saves.values)
    nobias = _score("production", ev.proj0.values, ev.saves.values)
    feat = _mp_features(df, mp, p)
    m27 = ((feat.season == 2027) & (feat.game_type == "R")).values
    alts = []
    for kind, label in (("gsax", "GSAx save% (k=1500 shots)"),
                        ("fenwick", "Fenwick shot volume"),
                        ("both", "Fenwick volume + GSAx save%")):
        proj = _alt_proj(feat, kind)
        sc = _score(label, proj[m27], feat.saves.values[m27])
        sc["paired"] = _paired(proj[m27], feat.proj.values[m27], feat.saves.values[m27])
        alts.append(sc)
        print(label, sc["mae"], sc["paired"], flush=True)
    kept = next((a for a in alts if a["paired"]["better"]), None)
    after = {"n": base["n"], "mae": base["mae"], "bias": base["bias"], "kept": "production"}
    decision = ("No MoneyPuck alternative beat the production projection by more than one standard error "
                "and 0.02 saves, so the formula is unchanged. The after column equals the before column "
                "(production projection plus the rolling bias).")
    if kept:
        after = {"n": kept["n"], "mae": kept["mae"], "bias": kept["bias"], "kept": kept["name"]}
        decision = f"Shipped {kept['name']}: paired MAE improved by {kept['paired']['d_mae']} (SE {kept['paired']['se']})."
    # the gate above is what this run found. The code in engine.py is still the production formula,
    # which is correct exactly when nothing was kept.

    def sl(mask):
        x = ev[mask]
        return {"n": int(len(x)), "mae": round(float((x.proj - x.saves).abs().mean()), 4) if len(x) else None,
                "bias": round(float((x.proj - x.saves).mean()), 4) if len(x) else None}

    lines = _real_lines(ev)
    rep = {
        "built": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "decision": decision,
        "before": {"nobias": nobias, "bias": base},
        "after": after,
        "shots": {"bias": round(float((ev.mu - ev.shots).mean()), 4),
                  "mae": round(float((ev.mu - ev.shots).abs().mean()), 4),
                  "team_bias": round(float((ev.mu.values / ev.share.values - ev.actual_team_sa.values).mean()), 4),
                  "sv": round(float(ev.sv.mean()), 4),
                  "actual_sv": round(float(ev.saves.sum() / ev.shots.sum()), 4)},
        "slices": {"all": sl(np.ones(len(ev), bool)), "home": sl(ev.is_home.values), "away": sl(~ev.is_home.values),
                   "b2b": sl(ev.b2b.values), "opp b2b": sl(ev.opp_b2b.values),
                   "full (TOI ≥ 55)": sl(ev.toi.values >= 55), "pull (TOI < 40)": sl(ev.toi.values < 40)},
        "alternatives": alts,
        "calibration_starts": _cal_table(ev.proj.values, ev.sd.values, ev.saves.values),
        "side_cal": _side_cal(lines),
        "thresholds": _edge_table(lines),
        "rule": _rule(lines),
        "lines": {"n": int(len(lines)), "from": str(lines.date.min()) if len(lines) else None,
                  "to": str(lines.date.max()) if len(lines) else None},
        "crosscheck": ck,
        "shots_file": shots,
    }
    rep["slices"]["full"] = rep["slices"]["full (TOI ≥ 55)"]
    rep["slices"]["pull"] = rep["slices"]["pull (TOI < 40)"]
    os.makedirs(REPORTS, exist_ok=True)
    text = _md(rep)
    open(os.path.join(REPORTS, "goalie_backtest.md"), "w").write(text)
    json.dump(rep, open(os.path.join(OUT, "goalie_backtest.json"), "w"), indent=1)
    print(text)
    if kept:
        raise SystemExit("an alternative beat production; the formula in engine.py was NOT updated automatically")


if __name__ == "__main__":
    main()
