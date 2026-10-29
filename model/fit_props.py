"""Walk-forward fit of the skater prop models: shots on goal and points.

    python model/fit_props.py              # fit both, write params + model/reports/props_fit.md
    python model/fit_props.py --dry-run    # report only
    python model/fit_props.py --stat points

Everything used for the current season is fitted on earlier seasons only:
  * recency / shrinkage (rate_hl, toi_hl, k_min, carry, c_opp, c_team): coordinate search on the
    previous season's negative-binomial log-likelihood;
  * back-to-back and opponent back-to-back: projected-vs-actual ratios pooled over earlier seasons;
  * linear mean recalibration (cal_a, cal_b): actual ~ raw on the previous season;
  * dispersion (disp_k, size = disp_k x mean): max likelihood on the previous season.
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
DISP_K = (3, 5, 7, 10, 15, 20, 30)
LINES = {"shots_on_goal": (0.5, 1.5, 2.5, 3.5, 4.5), "points": (0.5, 1.5, 2.5)}


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


def sizes(mu, p):
    mu = np.asarray(mu, float)
    return np.maximum(p.disp_k * np.maximum(mu, 0.02), 0.5) if p.disp_k else np.full(mu.shape, p.disp)


def reliability(p, y, edges=(0, .1, .2, .3, .4, .5, .55, .6, .65, .7, .8, .9, 1.0001)):
    b = pd.cut(p, edges, right=False)
    g = pd.DataFrame({"p": p, "y": y}).groupby(b, observed=True).agg(n=("y", "size"), pred=("p", "mean"), act=("y", "mean"))
    return [{"bucket": f"{i.left:.0%}-{min(i.right, 1):.0%}", "n": int(r.n), "pred": round(float(r.pred), 4),
             "actual": round(float(r.act), 4)} for i, r in g.iterrows()]


def score(df, p, season, stat):
    x = df[df.season == season]
    mu = np.maximum(x.proj.values, 0.02); y = x.shots.values; sz = sizes(mu, p)
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
    start = sog.SogParams.load(path) if os.path.exists(path) else sog.SogParams()
    start = replace(start, b2b=1.0, opp_b2b=1.0, cal_a=0.0, cal_b=1.0, disp_k=start.disp_k or 10.0)
    prev = season - 1

    def run(p):
        df, _ = sog.run(sk, p, record_from=prev - 1, stat=stat)
        return df

    def ll(df, p, ss):
        x = df[df.season == ss]; mu = np.maximum(x.proj.values, .02)
        return float(nb_logpmf(x.shots.values, mu, sizes(mu, p)).mean())

    p = start
    df = run(p); best = ll(df, p, prev)
    log.append(f"### {stat}\n\nStart: log-lik {best:.5f} on {prev - 1}-{str(prev)[2:]}.\n")
    for name, vals in GRID.items():
        for v in vals:
            cand = replace(p, **{name: v})
            if cand == p:
                continue
            d = run(cand); s = ll(d, cand, prev)
            if s > best + 1e-5:
                best, p, df = s, cand, d
        log.append(f"- {name} = {getattr(p, name)} (log-lik {best:.5f})")
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
