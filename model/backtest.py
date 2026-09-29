"""Fit on 2024-25, test out-of-sample on 2025-26.

    python model/backtest.py            # fit + report, writes model/output/backtest.json
    python model/backtest.py --no-fit   # reuse params in model/output/params.json

IMPORTANT: historical sportsbook saves lines are not in the public data, so
lines are *proxies* (see engine.proxy_line). Hit rates against a proxy line
are an upper bound on what you'd see against real DK / PrizePicks lines.
"""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import replace

import numpy as np
import pandas as pd

import data
import engine

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "output")
TRAIN, TEST = 2025, 2026          # season end-years: 2024-25 train, 2025-26 test
EDGE_BUCKETS = [0.5, 1.0, 1.5, 2.0, 2.5, 3.0]

GRID = {
    "half_life": [10, 15, 20, 30, 45, 70],
    "k_team": [3, 6, 10, 15, 25],
    "carry": [0.15, 0.25, 0.35, 0.5, 0.7],
    "a": [0.5, 0.65, 0.8, 0.95, 1.1],
    "b": [0.3, 0.45, 0.6, 0.75, 0.9, 1.05],
    "k_sv": [500, 1000, 1500, 2500, 4000],
    "sv_half_life": [30, 60, 120, 250],
    "k_share": [5, 15, 40],
}


def mae(df):
    return float((df.proj - df.saves).abs().mean())


def fit_multipliers(df: pd.DataFrame, p: engine.Params) -> engine.Params:
    """Home / playoff / back-to-back multipliers from shot-volume residuals on the train season."""
    r = df.actual_team_sa / df.exp_sa
    home = float(np.sqrt(r[df.is_home].mean() / r[~df.is_home].mean())) * p.home
    po = float(r[df.game_type == "P"].mean() / r[df.game_type == "R"].mean()) * p.playoff
    b2b = float(r[df.b2b].mean() / r[~df.b2b].mean()) * p.b2b
    return replace(p, home=round(home, 4), playoff=round(po, 4), b2b=round(b2b, 4))


def fit(tg, st) -> engine.Params:
    p = engine.Params()

    def score(pp):
        df, _ = engine.run(tg, st, pp, record_from_season=TRAIN)
        return mae(df[df.season == TRAIN]), df

    best, df = score(p)
    for sweep in range(2):
        p = fit_multipliers(df[df.season == TRAIN], p)
        best, df = score(p)
        for name, values in GRID.items():
            for v in values:
                cand = replace(p, **{name: v})
                s, d = score(cand)
                if s < best - 1e-4:
                    best, p, df = s, cand, d
            print(f"  sweep {sweep + 1} {name:>12} = {getattr(p, name):<7} train MAE {best:.4f}")
    p = fit_multipliers(df[df.season == TRAIN], p)
    return p


def bucket_table(g: pd.DataFrame):
    rows = []
    for lo in EDGE_BUCKETS:
        s = g[g.edge.abs() >= lo]
        if len(s) == 0:
            continue
        o, u = s[s.side == "OVER"], s[s.side == "UNDER"]
        rows.append({
            "min_edge": lo, "n": int(len(s)), "hit": float(s.hit.mean()),
            "over_n": int(len(o)), "over_hit": float(o.hit.mean()) if len(o) else None,
            "under_n": int(len(u)), "under_hit": float(u.hit.mean()) if len(u) else None,
            "units": float(units(s)),
        })
    return rows


def units(s: pd.DataFrame, price=-115):
    """Flat 1u bets at a typical saves-prop price."""
    win = 100 / abs(price) if price < 0 else price / 100
    return s.hit.sum() * win - (~s.hit).sum()


def evaluate(df: pd.DataFrame, sd: float, season: int):
    d = df[(df.season == season) & df.l10.notna()].copy()
    d["line"] = d.l10.apply(engine.proxy_line)
    g = engine.grade(d, sd)
    g["tier"] = g.edge.abs().apply(engine.tier)
    calib = []
    for lo, hi in [(0.5, 0.55), (0.55, 0.6), (0.6, 0.65), (0.65, 0.7), (0.7, 1.0)]:
        s = g[(g.p_side >= lo) & (g.p_side < hi)]
        if len(s):
            calib.append({"p_lo": lo, "p_hi": hi, "n": int(len(s)),
                          "pred": float(s.p_side.mean()), "hit": float(s.hit.mean())})
    # Stress test: a sharper book that already prices the goalie's team shot
    # suppression, save% and pull risk, and only misses opponent / venue / rest.
    sharp = d.copy()
    sharp["line"] = (sharp.team_def * sharp.sv * sharp.share).apply(engine.proxy_line)
    gs = engine.grade(sharp, sd)
    reg, po = g[g.game_type == "R"], g[g.game_type == "P"]
    summary = {
        "season": season, "starts": int(len(d)),
        "mae_model": mae(d), "mae_l10": float((d.l10 - d.saves).abs().mean()),
        "bias": float((d.proj - d.saves).mean()),
        "corr_model": float(np.corrcoef(d.proj, d.saves)[0, 1]),
        "corr_l10": float(np.corrcoef(d.l10, d.saves)[0, 1]),
        "buckets": bucket_table(g),
        "buckets_regular": bucket_table(reg),
        "buckets_playoffs": bucket_table(po),
        "buckets_sharp": bucket_table(gs),
        "tiers": {t: {"n": int(len(s)), "hit": float(s.hit.mean())}
                  for t, s in g.groupby("tier")},
        "calibration": calib,
    }
    return summary, g


def monthly(g: pd.DataFrame, min_edge=1.5):
    s = g[g.edge.abs() >= min_edge].copy()
    s["month"] = s.date.str[:7]
    return [{"month": m, "n": int(len(x)), "hit": float(x.hit.mean())}
            for m, x in s.groupby("month")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-fit", action="store_true")
    args = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)

    tg, st = data.load_all([2024, TRAIN, TEST])
    ppath = os.path.join(OUT, "params.json")
    if args.no_fit and os.path.exists(ppath):
        p = engine.Params(**json.load(open(ppath)))
    else:
        print("Fitting on 2024-25 ...")
        p = fit(tg, st)
        json.dump(p.to_dict(), open(ppath, "w"), indent=2)
    print("Params:", p)

    df, _ = engine.run(tg, st, p, record_from_season=TRAIN)
    train = df[df.season == TRAIN]
    sd = float((train.proj - train.saves).std())
    report = {"params": p.to_dict(), "sd": sd, "line_proxy": "floor(last-10-start avg saves) + 0.5",
              "price": -115}
    games = []
    for season in (TRAIN, TEST):
        summ, g = evaluate(df, sd, season)
        summ["monthly"] = monthly(g)
        report[str(season)] = summ
        games.append(g)
        label = "TRAIN 2024-25" if season == TRAIN else "TEST  2025-26 (out-of-sample)"
        print(f"\n{label}: {summ['starts']} starts | MAE model {summ['mae_model']:.3f} vs "
              f"last-10 {summ['mae_l10']:.3f} | corr {summ['corr_model']:.3f} vs {summ['corr_l10']:.3f}")
        print("  edge>=   n     hit    OVER          UNDER         units@-115")
        for b in summ["buckets"]:
            oh = f"{b['over_hit']:.1%}" if b["over_hit"] is not None else "  -  "
            uh = f"{b['under_hit']:.1%}" if b["under_hit"] is not None else "  -  "
            print(f"  {b['min_edge']:>4}  {b['n']:>5}  {b['hit']:.1%}  {b['over_n']:>4} {oh}   "
                  f"{b['under_n']:>4} {uh}   {b['units']:+.1f}")
        print("  stress test vs sharper proxy line: " + ", ".join(
            f">={b['min_edge']}: {b['hit']:.1%} (n={b['n']})" for b in summ["buckets_sharp"]))
    allg = pd.concat(games)
    cols = ["date", "season", "game_type", "goalie", "team", "opp", "is_home", "proj", "line",
            "edge", "side", "p_side", "saves", "hit", "tier", "exp_sa", "sv"]
    allg[cols].round(3).to_csv(os.path.join(OUT, "backtest_games.csv"), index=False)
    json.dump(report, open(os.path.join(OUT, "backtest.json"), "w"), indent=2)
    print(f"\nWrote {OUT}/backtest.json and backtest_games.csv")


if __name__ == "__main__":
    main()
