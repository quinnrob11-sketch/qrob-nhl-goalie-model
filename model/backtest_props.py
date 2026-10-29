"""Calibration backtest for every prop market, this season: Brier score and reliability tables.

    python model/backtest_props.py            # writes model/reports/calibration_backtest.md (+ .json)

Two views:
  1. The model's own distributions on EVERY game this season (no book line needed): for each
     skater-game, P(shots > L) and P(points > L) at the standard lines; for each start, P(saves > L)
     at three lines around the projection. Walk-forward: every game is projected from earlier games.
  2. Real graded lines (all books, de-duplicated), where the stated hit % is what the board shows:
     raw model, the side-split Platt calibration and an isotonic calibration, each refit week by
     week on earlier weeks only. Brier and a reliability table by stated-hit-% bucket.
Buckets follow the board's tiers: 50-55, 55-58 (near miss), 58-62 (Strong), 62%+ (Lock).
"""
from __future__ import annotations

import json
import os

import numpy as np
import pandas as pd

import calibrate
import data
import engine
import fit_props
import fit_sa
import prizepicks
import saves_dist
import sog
import tracker

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "output")
REPORTS = os.path.join(HERE, "reports")
TIER_EDGES = (0.5, 0.55, 0.58, 0.62, 1.0001)
TIER_NAMES = ("50-55%", "55-58% near miss", "58-62% Strong", "62%+ Lock")


def tier_table(p_side, hit):
    p_side = np.asarray(p_side, float); hit = np.asarray(hit, float)
    rows = []
    for lo, hi, name in zip(TIER_EDGES[:-1], TIER_EDGES[1:], TIER_NAMES):
        m = (p_side >= lo) & (p_side < hi)
        rows.append({"bucket": name, "n": int(m.sum()), "stated": round(float(p_side[m].mean()), 4) if m.any() else None,
                     "actual": round(float(hit[m].mean()), 4) if m.any() else None})
    return rows


def iso_fit(p, y):
    """Isotonic (pool-adjacent-violators) map from P(over) to the over rate. Returns knots."""
    o = np.argsort(p); x = np.asarray(p, float)[o]; v = np.asarray(y, float)[o]
    blocks = [[x[i], x[i], v[i], 1.0] for i in range(len(x))]   # lo, hi, mean, weight
    out = []
    for b in blocks:
        out.append(b)
        while len(out) > 1 and out[-2][2] >= out[-1][2]:
            a, c = out[-2], out.pop()
            w = a[3] + c[3]
            out[-1] = [a[0], c[1], (a[2] * a[3] + c[2] * c[3]) / w, w]
    xs = [(b[0] + b[1]) / 2 for b in out]; ys = [min(max(b[2], .02), .98) for b in out]
    return {"x": xs, "y": ys}


def iso_apply(p, cal):
    return np.interp(p, cal["x"], cal["y"])


def walk_calibrations(x):
    """Raw, side-split Platt and isotonic P(over), each refit weekly on earlier weeks only."""
    y = x.went_over.values.astype(float); push = x.push.values
    raw = x.p_over.values
    platt = raw.copy(); iso = raw.copy()
    for wk in sorted(x.wk.unique()):
        te, tr = (x.wk == wk).values, (x.wk < wk).values & ~push
        if tr.sum() < 50:
            continue
        cal = calibrate.side_fit(raw[tr], y[tr].astype(bool))
        import pricing
        platt[te] = [pricing.platt(p, cal) for p in raw[te]]
        lam = min(1.0, tr.sum() / 500)       # same small-sample shrink toward identity as the Platt fit
        iso[te] = lam * iso_apply(raw[te], iso_fit(raw[tr], y[tr])) + (1 - lam) * raw[te]
    return {"raw": raw, "platt (side-split)": platt, "isotonic": iso}


def real_lines(season_start: str):
    log = tracker._read_log()
    tg, st = data.load_all([2024, 2025, 2026, 2027])
    df, _ = engine.run(tg, st, engine.Params.load(os.path.join(OUT, "params.json")))
    cur = int(df.season.max())
    srows = df[df.season == cur]
    srows = fit_sa.with_pwin(srows)
    sk = sog.load([2024, 2025, 2026, 2027])
    sp = sog.SogParams.load(os.path.join(OUT, "sog_params.json"))
    sr, _ = sog.run(sk, sp, record_from=cur)
    pp_path = os.path.join(OUT, "points_params.json")
    pp = sog.SogParams.load(pp_path) if os.path.exists(pp_path) else None
    pr = sog.run(sk, pp, record_from=cur, stat="points")[0] if pp else None
    x = calibrate.lines_frame(log, srows, saves_dist.load(os.path.join(OUT, "saves_dist.json")), sr, sp, pr, pp, all_books=True)
    x = x[x.date >= season_start]
    # one row per prop (the tracker's de-duplication: date + market + player + team)
    x = x.sort_values("book").drop_duplicates(["date", "market", "player", "team"]).reset_index(drop=True)
    x["wk"] = pd.to_datetime(x.date).dt.isocalendar().week.astype(int)
    out = {}
    for mk in calibrate.MARKETS:
        m = x[x.market == mk].reset_index(drop=True)
        if len(m) < 30:
            continue
        res = {"n": int(len(m)), "from": str(m.date.min()), "to": str(m.date.max()), "methods": {}}
        g = ~m.push.values
        for name, po in walk_calibrations(m).items():
            yo = m.went_over.values.astype(float)
            side_over = po >= .5
            ps = np.where(side_over, po, 1 - po); hit = np.where(side_over, yo, 1 - yo)
            res["methods"][name] = {"brier": round(float(np.mean((po[g] - yo[g]) ** 2)), 5),
                                    "tiers": tier_table(ps[g], hit[g])}
        out[mk] = res
    return out


def model_distributions():
    sk = sog.load([2024, 2025, 2026, 2027])
    season = int(sk.season.max())
    out = {}
    for stat, fname, mk in (("shots_on_goal", "sog_params.json", "sog"), ("points", "points_params.json", "points")):
        path = os.path.join(OUT, fname)
        if not os.path.exists(path):
            continue
        p = sog.SogParams.load(path)
        df, _ = sog.run(sk, p, record_from=season, stat=stat)
        out[mk] = fit_props.score(df, p, season, stat)
    # saves: P(saves > L) at three lines around each start's projection
    tg, st = data.load_all([2024, 2025, 2026, 2027])
    e, _ = engine.run(tg, st, engine.Params.load(os.path.join(OUT, "params.json")), record_from_season=season)
    e = fit_sa.with_pwin(e)
    D = saves_dist.load(os.path.join(OUT, "saves_dist.json"))
    po, yo = [], []
    for r in e.itertuples():
        x = saves_dist.project(r.exp_sa, r.share, r.sv, r.p_win, D)
        for d in (-3, 0, 3):
            line = np.floor(x["proj"] + d) + 0.5
            po.append(saves_dist.p_over(x["proj"], x["sd"], line)); yo.append(float(r.saves > line))
    po, yo = np.array(po), np.array(yo)
    ps = np.maximum(po, 1 - po); hit = np.where(po >= .5, yo, 1 - yo)
    out["saves"] = {"season": season, "n": int(len(e)), "bias": round(float((e.saves - [saves_dist.project(r.exp_sa, r.share, r.sv, r.p_win, D)["proj"] for r in e.itertuples()]).mean()), 3),
                    "brier": round(float(np.mean((po - yo) ** 2)), 5), "reliability": fit_props.reliability(ps, hit)}
    return out


def main():
    season_start = "2026-09-01"
    dist = model_distributions()
    real = real_lines(season_start)
    L = ["# Calibration backtest (this season)", "",
         "Generated by `python model/backtest_props.py`. Lower Brier is better; a calibrated model's \"stated\" and \"actual\" columns match.", "",
         "## 1. Model distributions on every game (walk-forward, no book lines)", ""]
    for mk, v in dist.items():
        if mk == "saves":
            L += [f"**Saves**: {v['n']} starts, mean actual − projected {v['bias']:+.2f} saves, Brier {v['brier']} (three lines per start).", "",
                  "| stated P(side) | n | stated | actual |", "|---|---|---|---|"]
            L += [f"| {b['bucket']} | {b['n']} | {b['pred']:.1%} | {b['actual']:.1%} |" for b in v["reliability"]]
        else:
            L += [f"**{mk.upper()}**: {v['n']} player-games, log-lik {v['loglik']}, mean actual − projected {v['bias']:+.3f}.", "",
                  "| line | Brier | predicted over | actual over |", "|---|---|---|---|"]
            L += [f"| {ln} | {x['brier']} | {x['pred_over']:.1%} | {x['act_over']:.1%} |" for ln, x in v["lines"].items()]
            ln = "1.5" if mk == "sog" else "0.5"
            L += ["", f"Reliability at {ln} (the side the model favours):", "", "| stated P(side) | n | stated | actual |", "|---|---|---|---|"]
            L += [f"| {b['bucket']} | {b['n']} | {b['pred']:.1%} | {b['actual']:.1%} |" for b in v["lines"][ln]["reliability"]]
        L.append("")
    L += ["## 2. Real graded lines: raw vs calibrated (refit weekly on earlier weeks)", ""]
    for mk, v in real.items():
        L += [f"**{mk.upper()}**: {v['n']} props, {v['from']} to {v['to']}.", "",
              "| method | Brier | " + " | ".join(TIER_NAMES) + " |", "|---|---|" + "---|" * len(TIER_NAMES)]
        for name, m in v["methods"].items():
            cells = [f"{t['actual']:.1%} vs {t['stated']:.1%} (n {t['n']})" if t["n"] else "–" for t in m["tiers"]]
            L.append(f"| {name} | {m['brier']} | " + " | ".join(cells) + " |")
        L.append("")
    L += ["Cells read *actual hit % vs stated hit % (count)*."]
    os.makedirs(REPORTS, exist_ok=True)
    open(os.path.join(REPORTS, "calibration_backtest.md"), "w").write("\n".join(L) + "\n")
    json.dump({"distributions": dist, "real_lines": real}, open(os.path.join(OUT, "calibration_backtest.json"), "w"), indent=1)
    print("\n".join(L))


if __name__ == "__main__":
    main()
