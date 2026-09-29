"""Game-winner (moneyline) model, built on the saves engine.

Expected goals for each side blend two views:
  shot view  = shots the opponent's goalie is expected to face x (1 - his save%)
               (the same exp_SA and shrunk SV% the saves model uses, so the
               starting goalie matters)
  rate view  = LG_goals x (team GF rate / LG) x (opponent GA rate / LG)
  lambda     = w * shot + (1 - w) * rate, then x home (/ home for the road side)
Win probability: independent Poisson goals; ties (OT/shootout) split by `ot_home`.

    python model/winners.py        # fit on 2024-25, test on 2025-26

No historical moneylines are in the public data, so the backtest scores
probability quality (log loss, Brier, accuracy, calibration), not ROI.
"""
from __future__ import annotations

import json
import math
import os

import numpy as np
import pandas as pd

import data
import engine

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "output")
TRAIN, TEST = 2025, 2026
MAXG = 12


def poisson_pmf(lam, n=MAXG):
    p = [math.exp(-lam)]
    for k in range(1, n + 1):
        p.append(p[-1] * lam / k)
    return p


def win_prob(lh, la, ot_home):
    ph, pa = poisson_pmf(lh), poisson_pmf(la)
    home = sum(ph[i] * sum(pa[:i]) for i in range(1, MAXG + 1))
    tie = sum(ph[i] * pa[i] for i in range(MAXG + 1))
    return home + tie * ot_home


def games(df: pd.DataFrame) -> pd.DataFrame:
    """One row per game with both sides' inputs (from engine.run rows)."""
    h = df[df.is_home].set_index("game_id")
    a = df[~df.is_home].set_index("game_id")
    g = h.join(a, lsuffix="_h", rsuffix="_a", how="inner")
    out = pd.DataFrame({
        "date": g.date_h, "season": g.season_h, "game_type": g.game_type_h,
        "home": g.team_h, "away": g.team_a, "goalie_h": g.goalie_h, "goalie_a": g.goalie_a,
        # shots the AWAY goalie faces come from the home side, and vice versa
        "shot_h": g.exp_sa_a * (1 - g.sv_a), "shot_a": g.exp_sa_h * (1 - g.sv_h),
        "rate_h": g.lg_goals_h * (g.gf_rate_h / g.lg_goals_h) * (g.ga_rate_a / g.lg_goals_h),
        "rate_a": g.lg_goals_h * (g.gf_rate_a / g.lg_goals_h) * (g.ga_rate_h / g.lg_goals_h),
        "xg_h": g.lg_goals_h * (g.xgf_rate_h / g.lg_goals_h) * (g.xga_rate_a / g.lg_goals_h),
        "xg_a": g.lg_goals_h * (g.xgf_rate_a / g.lg_goals_h) * (g.xga_rate_h / g.lg_goals_h),
        "home_win": (g.goals_for_h > g.goals_against_h).astype(int),
    })
    return out.reset_index()


def predict(g: pd.DataFrame, w, home, ot_home, x=0.0):
    """x = share of the rate view taken from expected goals instead of actual goals."""
    rh = (1 - x) * g.rate_h + x * g.xg_h
    ra = (1 - x) * g.rate_a + x * g.xg_a
    lh = (w * g.shot_h + (1 - w) * rh) * home
    la = (w * g.shot_a + (1 - w) * ra) / home
    return np.array([win_prob(x, y, ot_home) for x, y in zip(lh, la)]), lh, la


def logloss(p, y):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def fit(g):
    tr = g[g.season == TRAIN]
    best = None
    for w in np.arange(0, 1.01, 0.1):
        for x in (0.0, 0.25, 0.5, 0.75, 1.0):
            for home in np.arange(1.0, 1.13, 0.02):
                for ot in (0.46, 0.5, 0.54):
                    p, _, _ = predict(tr, w, home, ot, x)
                    ll = logloss(p, tr.home_win.values)
                    if best is None or ll < best[0]:
                        best = (ll, round(float(w), 2), round(float(home), 3), ot, x)
    return {"w": best[1], "home": best[2], "ot_home": best[3], "x": best[4]}


def evaluate(g, prm, season, base_home):
    s = g[g.season == season].copy()
    p, lh, la = predict(s, prm["w"], prm["home"], prm["ot_home"], prm.get("x", 0.0))
    s["p_home"], s["lam_h"], s["lam_a"] = p, lh, la
    y = s.home_win.values
    pick_home = p >= 0.5
    conf = np.maximum(p, 1 - p)
    correct = np.where(pick_home, y == 1, y == 0)
    buckets = []
    for lo, hi in [(0.5, 0.55), (0.55, 0.6), (0.6, 0.65), (0.65, 0.7), (0.7, 1.01)]:
        m = (conf >= lo) & (conf < hi)
        if m.sum():
            buckets.append({"lo": lo, "hi": min(hi, 1.0), "n": int(m.sum()),
                            "pred": float(conf[m].mean()), "hit": float(correct[m].mean())})
    return {
        "season": season, "games": int(len(s)),
        "logloss": logloss(p, y), "logloss_home_only": logloss(np.full(len(y), base_home), y),
        "brier": float(np.mean((p - y) ** 2)), "accuracy": float(correct.mean()),
        "accuracy_home_only": float(max(y.mean(), 1 - y.mean())),
        "buckets": buckets,
    }, s


def main():
    os.makedirs(OUT, exist_ok=True)
    p = engine.Params(**json.load(open(os.path.join(OUT, "params.json"))))
    tg, st = data.load_all([2024, TRAIN, TEST])
    df, _ = engine.run(tg, st, p, record_from_season=TRAIN)
    g = games(df)
    prm = fit(g)
    base_home = float(g[g.season == TRAIN].home_win.mean())
    prm["base_home"] = base_home
    json.dump(prm, open(os.path.join(OUT, "winners_params.json"), "w"), indent=2)
    report = {"params": prm}
    for season in (TRAIN, TEST):
        r, s = evaluate(g, prm, season, base_home)
        report[str(season)] = r
        label = "TRAIN 2024-25" if season == TRAIN else "TEST  2025-26 (out-of-sample)"
        print(f"{label}: {r['games']} games | log loss {r['logloss']:.4f} (home-only {r['logloss_home_only']:.4f}) "
              f"| accuracy {r['accuracy']:.1%} (home-only {r['accuracy_home_only']:.1%}) | Brier {r['brier']:.4f}")
        for b in r["buckets"]:
            print(f"   conf {b['lo']:.0%}-{b['hi']:.0%}: n={b['n']:4d} predicted {b['pred']:.1%} actual {b['hit']:.1%}")
    print("params", prm)
    json.dump(report, open(os.path.join(OUT, "winners_backtest.json"), "w"), indent=2)


if __name__ == "__main__":
    main()
