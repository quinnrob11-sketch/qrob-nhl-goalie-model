"""Walk-forward fit of the skater prop models: shots on goal and points.

    python model/fit_props.py              # fit both, write params + model/reports/props_fit.md
    python model/fit_props.py --dry-run    # report only
    python model/fit_props.py --stat points

Everything used for the current season is fitted on earlier seasons only:
  * recency / shrinkage (rate_hl, toi_hl, k_min, carry, c_opp, c_team): coordinate search on the
    previous season's negative-binomial log-likelihood;
  * back-to-back and opponent back-to-back: projected-vs-actual ratios pooled over earlier seasons;
  * linear mean recalibration (cal_a, cal_b): actual ~ raw on the previous season;
  * dispersion (disp_k, size = disp_k x mean): max likelihood on the previous season, then per
    position (F / D) and volume tier (disp_f / disp_d over disp_edges) on all earlier seasons.
The current season is then scored out of sample (log-likelihood, Brier, reliability).
"""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import replace

import numpy as np
import pandas as pd

import sog

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "output")
REPORTS = os.path.join(HERE, "reports")
FILES = {"shots_on_goal": "sog_params.json", "points": "points_params.json"}
GRID = {"rate_hl": [30, 60, 120], "toi_hl": [4, 8, 16], "k_min": [25, 50, 100, 200], "carry": [0.5, 0.7, 0.9],
        "c_opp": [0.5, 1.0], "c_team": [0.0, 0.5, 1.0]}
# SOG only: shot-attempt rate and the two-scale TOI (walk-forward tested in the sog-projection workflow)
GRID_SOG = {"w_att": [0.5, 0.75, 1.0], "att_hl": [20, 30, 45, 60], "k_att": [25, 50, 100, 200],
            "conv_hl": [60, 120, 250, 500], "k_conv": [100, 200, 400, 800],
            "toi_hl": [3, 4, 5, 6], "toi_hl2": [0.0, 16, 24, 40], "toi_lam": [0.6, 0.7, 0.8, 0.9, 1.0],
            "k_toi": [0.0, 0.25, 0.5], "k_min": [100, 150, 200, 300, 400], "rate_hl": [40, 60, 90]}
PASSES = 3
DISP_K = (3, 5, 7, 10, 15, 20, 30)
LINES = {"shots_on_goal": (0.5, 1.5, 2.5, 3.5, 4.5), "points": (0.5, 1.5, 2.5)}
TIER_EDGES = {"shots_on_goal": (1.5, 2.5, 3.5), "points": (0.4, 0.7, 1.0)}
TIER_K = tuple(np.r_[np.arange(1, 30, 0.5), 40, 60, 100, 300])
TIER_MIN_N = 200


def nb_logpmf(x, mu, size):
    from math import lgamma
    lg = np.vectorize(lgamma)
    x = np.asarray(x, float); mu = np.maximum(np.asarray(mu, float), 1e-3); size = np.broadcast_to(np.asarray(size, float), mu.shape)
    return lg(x + size) - lg(size) - lg(x + 1) + size * np.log(size / (size + mu)) + x * np.log(mu / (size + mu))


def p_over_vec(mu, line, size):
    """P(X > line) for half-point lines, vectorised."""
    k = int(np.floor(line))
    mu = np.maximum(np.asarray(mu, float), 1e-3); size = np.broadcast_to(np.asarray(size, float), mu.shape)
    cdf = np.zeros_like(mu)
    for x in range(k + 1):
        cdf += np.exp(nb_logpmf(np.full(mu.shape, x), mu, size))
    return 1 - np.minimum(cdf, 1)


def sizes(mu, p, pos=None):
    mu = np.asarray(mu, float)
    if pos is not None and p.disp_edges and (p.disp_f or p.disp_d):
        k = np.array([sog.disp_k_for(m, p, q) for m, q in zip(mu, pos)])
        return np.maximum(k * np.maximum(mu, 0.02), 0.5)
    return np.maximum(p.disp_k * np.maximum(mu, 0.02), 0.5) if p.disp_k else np.full(mu.shape, p.disp)


def fit_disp_tiers(df, edges, fallback):
    """disp_k per position and volume tier by max likelihood (size = k x mean). A tier with fewer than
    TIER_MIN_N player-games takes the tier below it (or `fallback`)."""
    t = np.digitize(df.proj.values, edges)
    out = {}
    for pos in ("F", "D"):
        ks = []
        for i in range(len(edges) + 1):
            m = (df.pos.values == pos) & (t == i)
            if m.sum() < TIER_MIN_N:
                ks.append(ks[-1] if ks else float(fallback)); continue
            mu = np.maximum(df.proj.values[m], .02); y = df.shots.values[m]
            ks.append(float(max(TIER_K, key=lambda k: nb_logpmf(y, mu, np.maximum(k * mu, .5)).sum())))
        out[pos] = tuple(ks)
    return out


def reliability(p, y, edges=(0, .1, .2, .3, .4, .5, .55, .6, .65, .7, .8, .9, 1.0001)):
    b = pd.cut(p, edges, right=False)
    g = pd.DataFrame({"p": p, "y": y}).groupby(b, observed=True).agg(n=("y", "size"), pred=("p", "mean"), act=("y", "mean"))
    return [{"bucket": f"{i.left:.0%}-{min(i.right, 1):.0%}", "n": int(r.n), "pred": round(float(r.pred), 4),
             "actual": round(float(r.act), 4)} for i, r in g.iterrows()]


def score(df, p, season, stat):
    x = df[df.season == season]
    mu = np.maximum(x.proj.values, 0.02); y = x.shots.values; sz = sizes(mu, p, x.pos.values)
    out = {"season": int(season), "n": int(len(x)), "loglik": round(float(nb_logpmf(y, mu, sz).mean()), 5),
           "bias": round(float((y - mu).mean()), 4), "lines": {}}
    for ln in LINES[stat]:
        po = p_over_vec(mu, ln, sz); yo = (y > ln).astype(float)
        # the side the model favours, as a pick: P(side) and whether it hit
        ps = np.maximum(po, 1 - po); hit = np.where(po >= .5, yo, 1 - yo)
        out["lines"][str(ln)] = {"brier": round(float(np.mean((po - yo) ** 2)), 5), "pred_over": round(float(po.mean()), 4),
                                 "act_over": round(float(yo.mean()), 4), "reliability": reliability(ps, hit)}
    return out


def fit_stat(stat, sk, season, log):
    path = os.path.join(OUT, FILES[stat])
    if os.path.exists(path):
        start = sog.SogParams.load(path)
    else:   # the defaults are the SOG fit; points start with the attempt rate and second TOI half-life off
        start = sog.SogParams() if stat == "shots_on_goal" else sog.SogParams(w_att=0.0, toi_hl2=0.0, toi_lam=1.0)
    start = replace(start, b2b=1.0, opp_b2b=1.0, cal_a=0.0, cal_b=1.0, disp_k=start.disp_k or 10.0,
                    disp_edges=(), disp_f=(), disp_d=())
    prev = season - 1
    if stat == "shots_on_goal":
        # league SOG per attempt by position on the previous season (prior of the player's conversion)
        x = sk[(sk.season == prev) & sk.has_pbp]
        cf = x[x.pos == "F"]; cd = x[x.pos == "D"]
        start = replace(start, conv_f=round(float(cf.shots_on_goal.sum() / cf.icf.sum()), 4),
                        conv_d=round(float(cd.shots_on_goal.sum() / cd.icf.sum()), 4),
                        w_att=start.w_att or 1.0,
                        # the two-scale TOI needs toi_hl2 > 0 AND toi_lam < 1 at once: start it switched on so the
                        # coordinate search can move either (toi_lam = 1.0 in the grid switches it off)
                        toi_hl2=start.toi_hl2 or 24.0, toi_lam=start.toi_lam if start.toi_lam < 1 else 0.7,
                        k_toi=0.0)

    def run(p):
        df, _ = sog.run(sk, p, record_from=prev - 1, stat=stat)
        return df

    def ll(df, p, ss):
        """NB log-lik on season ss after refitting proj = a + b x raw there (size = disp_k x mean): the search
        then compares candidates at their best calibration, which is how they are used."""
        x = df[df.season == ss]
        if stat != "shots_on_goal":      # points: unchanged objective (raw projection)
            mu = np.maximum(x.proj.values, .02)
            return float(nb_logpmf(x.shots.values, mu, sizes(mu, p)).mean())
        b, a = np.polyfit(x.raw.values, x.shots.values, 1)
        mu = np.maximum(a + b * x.raw.values, .02)
        return float(nb_logpmf(x.shots.values, mu, sizes(mu, p)).mean())

    p = start
    df = run(p); best = ll(df, p, prev)
    log.append(f"### {stat}\n\nStart: log-lik {best:.5f} on {prev - 1}-{str(prev)[2:]}.\n")
    grid = {**GRID, **GRID_SOG} if stat == "shots_on_goal" else GRID
    for it in range(PASSES):
        changed = False
        for name, vals in grid.items():
            for v in vals:
                cand = replace(p, **{name: v})
                if cand == p:
                    continue
                d = run(cand); s = ll(d, cand, prev)
                if s > best + 1e-6:
                    best, p, df, changed = s, cand, d, True
            log.append(f"- pass {it + 1}: {name} = {getattr(p, name)} (log-lik {best:.5f})")
        if not changed:
            break
    # back-to-back effects: projected-vs-actual ratios pooled over earlier seasons
    e = df[df.season < season]
    r = lambda m: e[m].shots.sum() / e[m].raw.sum()
    b2b = round(r(e.b2b) / r(~e.b2b), 4); ob2b = round(r(e.opp_b2b) / r(~e.opp_b2b), 4)
    p = replace(p, b2b=b2b, opp_b2b=ob2b)
    df = run(p)
    # linear mean recalibration on the previous season
    x = df[df.season == prev]
    cb, ca = np.polyfit(x.raw.values, x.shots.values, 1)
    p = replace(p, cal_a=round(float(ca), 4), cal_b=round(float(cb), 4))
    df = run(p)
    # dispersion on the previous season
    x = df[df.season == prev]; mu = np.maximum(x.proj.values, .02)
    lls = {k: float(nb_logpmf(x.shots.values, mu, np.maximum(k * mu, .5)).mean()) for k in DISP_K}
    lls[0] = float(nb_logpmf(x.shots.values, mu, np.full(mu.shape, p.disp)).mean())
    k = max(lls, key=lls.get)
    p = replace(p, disp_k=float(k))
    # dispersion by position and volume tier, on every earlier season
    e = df[(df.season < season) & (df.game_type == "R")]
    tiers = fit_disp_tiers(e, TIER_EDGES[stat], k or 10.0)
    p = replace(p, disp_edges=TIER_EDGES[stat], disp_f=tiers["F"], disp_d=tiers["D"])
    log.append(f"- dispersion by tier (projection edges {TIER_EDGES[stat]}): forwards {tiers['F']}, defence {tiers['D']}")
    log.append(f"- back-to-back x{b2b}, opponent back-to-back x{ob2b} (earlier seasons)")
    log.append(f"- mean recalibration: proj = {p.cal_a:+.4f} + {p.cal_b:.4f} x raw (fit on {prev - 1}-{str(prev)[2:]})")
    log.append(f"- dispersion: size = {k} x mean" if k else f"- dispersion: fixed size {p.disp}")
    return p, run(p), start


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--stat", choices=["shots_on_goal", "points", "both"], default="both")
    a = ap.parse_args()
    sk = sog.load([2024, 2025, 2026, 2027])
    season = int(sk.season.max())
    log = [f"# Skater prop models: walk-forward fit (season {season - 1}-{str(season)[2:]} scored out of sample)", "",
           "Fitted by `model/fit_props.py` on earlier seasons only; the current season is never used to fit.", ""]
    report = {}
    for stat in (["shots_on_goal", "points"] if a.stat == "both" else [a.stat]):
        old_path = os.path.join(OUT, FILES[stat])
        p, df, start = fit_stat(stat, sk, season, log)
        new = score(df, p, season, stat)
        if os.path.exists(old_path):
            od, _ = sog.run(sk, sog.SogParams.load(old_path), record_from=season, stat=stat)
            old = score(od, sog.SogParams.load(old_path), season, stat)
        else:
            old = None
        report[stat] = {"params": p.to_dict(), "current": new, "previous_params": old}
        log += ["", f"Out of sample, {season - 1}-{str(season)[2:]} ({new['n']} player-games): log-lik {new['loglik']}"
                + (f" vs {old['loglik']} with the previous settings" if old else "") + f"; mean actual − projected {new['bias']:+.3f}"
                + (f" (was {old['bias']:+.3f})" if old else "") + ".", "",
                "| line | Brier (new) | Brier (old) | predicted over | actual over |", "|---|---|---|---|---|"]
        for ln, v in new["lines"].items():
            o = old["lines"][ln]["brier"] if old else None
            log.append(f"| {ln} | {v['brier']} | {o if o is not None else '–'} | {v['pred_over']:.1%} | {v['act_over']:.1%} |")
        log.append("")
        if not a.dry_run:
            json.dump(p.to_dict(), open(old_path, "w"), indent=2)
    os.makedirs(REPORTS, exist_ok=True)
    open(os.path.join(REPORTS, "props_fit.md"), "w").write("\n".join(log) + "\n")
    json.dump(report, open(os.path.join(OUT, "props_fit.json"), "w"), indent=1)
    print("\n".join(log))


if __name__ == "__main__":
    main()
