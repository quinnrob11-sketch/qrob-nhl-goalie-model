"""Backtest for the audit fixes (items 2-6 and 11): before / after on every season we have.

    python model/backtest_audit.py      # writes model/reports/audit_backtest.md + output/audit_backtest.json

1. Distribution (item 4): randomized PIT histogram and P(shots >= k), k = 1-4, predicted vs actual, for
   the old single dispersion (disp_k) and the tiered one (disp_f / disp_d by position and volume tier).
   Walk-forward: 2025-26 scored with tiers fitted on 2024-25, 2026-27 with tiers fitted on both.
2. Calibration (item 2): on every player-game of 2024-25 / 2025-26 / 2026-27 at the lines a book would
   hang (0.5-3.5 where the model's P(over) is 25-75%), reliability by side (More / Less) and line bucket;
   then on the real graded DraftKings lines of this season, walk-forward (calibrate.fit), raw vs final,
   with Brier and log loss against DK no-vig and the old fixed 0.6 blend.
3. Market (item 3): the fitted blend weight, and the model's record where it disagrees with the market.
4. Rule-passing legs: walk-forward record of legs that pass the new TAKE rule vs the old 58% rule.
5. Saves (items 6 / 11): rolling bias correction (30-day half-life) before / after over the last 30 days,
   Over / Under calibration, and record + ROI at 1.5 / 2.0 / 2.5 / 3.0 saves of edge, overs and unders.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from dataclasses import replace

import numpy as np
import pandas as pd

import build_site
import calibrate
import data
import engine
import fit_props
import prices as dkp
import pricing
import prizepicks
import saves_dist
import sog
import tracker

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "output")
REPORTS = os.path.join(HERE, "reports")
SEASONS = (2025, 2026, 2027)
NAME = {2025: "2024-25", 2026: "2025-26", 2027: "2026-27"}


def pct(x, d=1):
    return "–" if x is None or x != x else f"{100 * x:.{d}f}%"


def nb_cdf_vec(k, mu, size):
    p = size / (size + mu); term = p ** size; cdf = term.copy()
    for i in range(1, int(k) + 1):
        term = term * (i - 1 + size) / i * (1 - p); cdf = cdf + term
    return np.minimum(cdf, 1)


def pit(y, mu, size, rng):
    """Randomized PIT for a count: U ~ Uniform(F(y-1), F(y))."""
    lo = np.zeros(len(y)); hi = np.zeros(len(y))
    for v in np.unique(y):
        m = y == v
        hi[m] = nb_cdf_vec(v, mu[m], size[m])
        lo[m] = nb_cdf_vec(v - 1, mu[m], size[m]) if v > 0 else 0.0
    return lo + rng.uniform(size=len(y)) * (hi - lo)


# ---------- 1. distribution ----------
def distribution(rows, p_new, stat):
    rng = np.random.default_rng(7)
    p_old = replace(p_new, disp_edges=(), disp_f=(), disp_d=())
    edges = fit_props.TIER_EDGES[stat]
    out = {}
    for season in (2026, 2027):
        tr = rows[(rows.season < season) & (rows.game_type == "R")]
        te = rows[(rows.season == season) & (rows.game_type == "R")]
        tiers = fit_props.fit_disp_tiers(tr, edges, p_new.disp_k)
        p_t = replace(p_new, disp_edges=edges, disp_f=tiers["F"], disp_d=tiers["D"])
        mu = np.maximum(te.proj.values, .02); y = te.shots.values
        res = {"n": int(len(te)), "tiers": tiers}
        for name, prm in (("old", p_old), ("new", p_t)):
            size = fit_props.sizes(mu, prm, te.pos.values)
            u = pit(y, mu, size, rng)
            h = np.histogram(u, bins=10, range=(0, 1))[0] / len(u)
            ge = {k: {"pred": float(np.mean(1 - nb_cdf_vec(k - 1, mu, size))), "act": float(np.mean(y >= k))} for k in (1, 2, 3, 4)}
            by_tier = {}
            t = np.digitize(mu, edges)
            for i in range(len(edges) + 1):
                m = t == i
                if m.sum() >= 50:
                    by_tier[i] = {k: {"pred": float(np.mean(1 - nb_cdf_vec(k - 1, mu[m], size[m]))), "act": float(np.mean(y[m] >= k))} for k in (1, 2, 3, 4)}
                    by_tier[i]["n"] = int(m.sum())
            res[name] = {"loglik": float(fit_props.nb_logpmf(y, mu, size).mean()), "pit": h.round(4).tolist(),
                         "pit_max_dev": float(np.max(np.abs(h - 0.1))), "ge": ge, "by_tier": by_tier}
        out[season] = res
    return out


# ---------- 2. synthetic-line reliability over every season ----------
def synthetic_reliability(rows, prm, stat):
    lines = fit_props.LINES[stat][:4]
    out = {}
    for season in SEASONS:
        x = rows[(rows.season == season) & (rows.game_type == "R")]
        mu = np.maximum(x.proj.values, .02); size = fit_props.sizes(mu, prm, x.pos.values); y = x.shots.values
        cells = []
        for ln in lines:
            po = 1 - nb_cdf_vec(int(np.floor(ln)), mu, size)
            keep = (po >= .25) & (po <= .75)
            so = po >= .5
            for side, m in (("More", keep & so), ("Less", keep & ~so)):
                if m.sum() < 30:
                    continue
                ps = np.where(so, po, 1 - po)[m]; win = np.where(so, y > ln, y <= ln)[m]
                cells.append({"side": side, "line": pricing.line_bucket(ln), "n": int(m.sum()), "pred": float(ps.mean()), "actual": float(win.mean())})
        out[season] = cells
    return out


# ---------- 4. rule-passing legs on real lines ----------
def rule_legs(log, rows_sog, prm_sog, rows_pts, prm_pts, prices):
    """Walk-forward on graded DK lines: TAKE under the live rule vs the old (calibrated model blended 60/40,
    p >= 58%), both as 1x DFS legs on the same warm weeks. The live rule's p: SOG, the 50/50 mean blend with the
    DK-implied mean (nothing fitted; its 62% / 55% bars were chosen on this season's lines); points, the blend
    fitted walk-forward (model must agree)."""
    df = calibrate.lines_frame(log, None, {}, rows_sog, prm_sog, rows_pts, prm_pts)
    if df.empty:
        return {}
    pr = dkp.last_pregame(prices.copy()); pr["key"] = pr.name.map(prizepicks.name_key)
    pr = pr.drop_duplicates(["market", "date", "key", "line"], keep="last")
    df["key"] = df.player.map(prizepicks.name_key)
    df = df.merge(pr[["market", "date", "key", "line", "over", "under"]], on=["market", "date", "key", "line"], how="left")
    df["wk"] = calibrate.week_key(df.date)
    out = {}
    for mk in ("sog", "points"):
        x = df[(df.market == mk)].dropna(subset=["over", "under"]).reset_index(drop=True)
        if len(x) < 100:
            continue
        r = calibrate.replay(x, mk)
        new, old = [], []
        be1 = pricing.dfs_break_even(1.0)
        mb = mk == "sog" and pricing.SOG_MEAN_W > 0
        prm = calibrate._prop_params(prm_sog) if mb else None
        for i, row in x.iterrows():
            if not r.warm.iloc[i] or row.push:        # the same warm weeks for both rules, so they compare like for like
                continue
            went = bool(row.went_over)
            pb, pm, pk = r.p_final_over.iloc[i], r.p_cal_over.iloc[i], r.p_mkt_over.iloc[i]
            if mb:      # the live SOG probability: mean blend, raw model as "model alone"
                pb = calibrate.mean_blend_p(row.model_proj, row.line, pk, prm, row.pos if isinstance(row.get("pos"), str) else None)
                pm = row.p_over
                if pb != pb:
                    continue
            # the live rule picks the side as if it were a 1x DFS leg (market support required) ...
            v = pricing.verdict(mk, pb, pm, row.line, row.model_proj, 1.0, 1.0, p_mkt_over=pk)
            pf = r.p_fixed_over.iloc[i]; oside = "OVER" if pf >= .5 else "UNDER"
            for side, keep, bag in ((v["side"], v["verdict"].startswith("TAKE"), new), (oside, max(pf, 1 - pf) >= pricing.TAKE_P, old)):
                if not keep:
                    continue
                win = went == (side == "OVER")
                nv = pk if side == "OVER" else 1 - pk
                price = row.over if side == "OVER" else row.under
                # ... and is settled three ways: as a 1x leg (hypothetical: DFS boards discount these sides),
                # at DraftKings' own price, and at the multiplier a Pick6-style board actually offers for a side
                # the market prices this way (measured on Nov 3-8 boards: <50% no-vig ~1.00x, 50-54% ~0.94x,
                # 54%+ ~0.8x; sub-1x sides are not TAKEs, so only sides offered at >= 1x are settled)
                m = 1.0 if nv < 0.50 else 0.94 if nv < 0.54 else 0.8
                bag.append({"side": side, "win": win, "line": row.line, "r_1x": (1 / be1 - 1) if win else -1.0,
                            "r_dk": pricing.profit(price) if win else -1.0,
                            "r_real": ((m / be1 - 1) if win else -1.0) if m >= pricing.MIN_MULT else None})
        def rec(z):
            if not z:
                return {"n": 0, "hit": 0, "pct": None, "se": None, "units_1x": 0.0, "units_dk": 0.0, "roi_dk": None,
                        "real_n": 0, "real_hit": 0, "roi_real": None}
            w = np.array([q["win"] for q in z], float); real = [q for q in z if q["r_real"] is not None]
            se = lambda v: float(np.std(v, ddof=1) / np.sqrt(len(v))) if len(v) > 1 else None
            return {"n": len(z), "hit": int(w.sum()), "pct": float(w.mean()), "se": se(w),
                    "units_1x": round(sum(q["r_1x"] for q in z), 2), "units_dk": round(sum(q["r_dk"] for q in z), 2),
                    "roi_dk": round(float(np.mean([q["r_dk"] for q in z])), 4), "roi_dk_se": se([q["r_dk"] for q in z]),
                    "real_n": len(real), "real_hit": int(sum(q["win"] for q in real)),
                    "roi_real": round(float(np.mean([q["r_real"] for q in real])), 4) if real else None}
        out[mk] = {"new": rec(new), "old": rec(old),
                   "new_by_side": {s: rec([z for z in new if z["side"] == s]) for s in ("OVER", "UNDER")},
                   "old_by_side": {s: rec([z for z in old if z["side"] == s]) for s in ("OVER", "UNDER")}}
    return out


# ---------- 5. saves ----------
def saves(log, df, prices):
    rows = []
    for s in (2026, 2027):
        x = build_site.saves_rows(df, s)
        if len(x):
            rows.append(x)
    x = pd.concat(rows)
    x = x[x.game_type == "R"].copy()
    pr_ = [saves_dist.project(r.exp_sa, r.share, r.sv, r.p_win, build_site.DIST) for r in x.itertuples()]
    x["proj0"] = [q["proj"] for q in pr_]; x["sd"] = [q["sd"] for q in pr_]
    x["date"] = pd.to_datetime(x.date)
    x["bias"] = saves_dist.rolling_bias(x.date.dt.strftime("%Y-%m-%d").values, (x.saves - x.proj0).values, pricing.SAVES_BIAS_HL)
    x["projc"] = x.proj0 + x.bias
    cut = x.date.max() - pd.Timedelta(days=30)
    last = x[x.date > cut]
    out = {"last30": {"n": int(len(last)), "err_before": float((last.saves - last.proj0).mean()),
                      "err_after": float((last.saves - last.projc).mean()),
                      "mae_before": float((last.saves - last.proj0).abs().mean()), "mae_after": float((last.saves - last.projc).abs().mean())},
           "season": {"n": int((x.date.dt.year >= 2026).sum())}}
    # real lines
    lg = pd.DataFrame([r for r in log if r["market"] == "saves" and r.get("result") in ("HIT", "MISS", "PUSH")])
    lg["line"] = lg.line.astype(float); lg["actual"] = lg.actual.astype(float); lg["date"] = pd.to_datetime(lg.date)
    pr = dkp.last_pregame(prices[prices.market == "saves"].copy()); pr["key"] = pr.name.map(prizepicks.name_key)
    pr["date"] = pd.to_datetime(pr.date)
    pr = pr.drop_duplicates(["date", "key", "line"], keep="last")
    lg["key"] = lg.player.map(prizepicks.name_key)
    lg = lg.merge(pr[["date", "key", "line", "over", "under"]], on=["date", "key", "line"], how="left")
    m = lg.merge(x[["date", "team", "proj0", "projc", "sd", "saves"]], on=["date", "team"], how="inner")
    m = m[m.saves == m.actual].copy()
    m["bpref"] = m.book.map({"DraftKings": 0}).fillna(1)
    m = m.sort_values("bpref").drop_duplicates(["date", "team"])
    push = (m.actual == m.line).values; over = (m.actual > m.line).values
    out["lines"] = {"n": int(len(m)), "books": m.book.value_counts().to_dict()}
    out["thresholds"], out["calibration"] = {}, {}
    for col in ("proj0", "projc"):
        edge = (m[col] - m.line).values
        po = np.array([saves_dist.p_over(a, b, c) for a, b, c in zip(m[col], m.sd, m.line)])
        tab = []
        for th in pricing.SAVES_EDGE_GRID:
            for side in ("OVER", "UNDER"):
                sel = ((edge >= th) if side == "OVER" else (edge <= -th)) & ~push
                win = (over if side == "OVER" else ~over)
                price = np.where(m.book.values == "DraftKings", np.where(side == "OVER", m.over.values, m.under.values), np.nan).astype(float)
                prof = np.where(win, np.where(np.isnan(price), 1 / pricing.dfs_break_even(1.0) - 1,
                                              [pricing.profit(q) if q == q else 0.0 for q in price]), -1.0)
                n = int(sel.sum()); h = int((win & sel).sum())
                tab.append({"edge": th, "side": side, "n": n, "hit": h, "miss": n - h, "pct": h / n if n else None,
                            "units": round(float(prof[sel].sum()), 2), "roi": float(prof[sel].mean()) if n else None})
        out["thresholds"][col] = tab
        so = po >= .5; ps = np.where(so, po, 1 - po); win = np.where(so, over, ~over)
        out["calibration"][col] = {s: {"n": int((mm := (so if s == "OVER" else ~so) & ~push).sum()),
                                       "pred": float(ps[mm].mean()) if mm.any() else None, "act": float(win[mm].mean()) if mm.any() else None}
                                   for s in ("OVER", "UNDER")}
    return out


def md(rep) -> str:
    L = ["# Audit backtest: before / after", "",
         f"Built {rep['built']} by `python model/backtest_audit.py`. Seasons: {', '.join(NAME[s] for s in SEASONS)} "
         "(every player-game), plus this season's real graded lines.", "",
         "**Read sections 1-2 carefully:** the shipped shots parameters are fitted on 2025-26, so the 2024-25 and 2025-26 "
         "player-game rows are scored with parameters that saw 2025-26 (in-sample; an honest refit on 2024-25 alone shows "
         "a bias about 0.5 point larger at 1.5 / 2.5). Only the 2026-27 rows and the real-line sections are out of sample, with "
         "three exceptions chosen with this season's lines in view: the shots projection's design (attempt rate, two-scale "
         "ice time), the 50/50 mean-blend weight (the in-sample log-loss optimum; a weight chosen week by week on earlier "
         "weeks scores 0.68478 against DK's 0.68592 on the same lines) and the SOG rule's 62% / 55% bars (bars re-chosen "
         "each week from earlier weeks give the same record within one standard error).", ""]
    # 1
    L += ["## 1. Shots distribution (item 4): dispersion by position and volume tier", "",
          "Randomized PIT deciles should each hold 10%; P(shots ≥ k) predicted vs actual. Old = one disp_k (size = 10 × mean); new = disp_k per position and projection tier, fitted on earlier seasons only.", ""]
    for season, r in rep["distribution"].items():
        L.append(f"**{NAME[int(season)]}** ({r['n']} player-games; tiers F {r['tiers']['F']}, D {r['tiers']['D']})")
        L += ["", "| | log-lik | PIT max deviation | P(≥1) | P(≥2) | P(≥3) | P(≥4) |", "|---|---|---|---|---|---|---|"]
        for nm in ("old", "new"):
            x = r[nm]
            L.append(f"| {nm} | {x['loglik']:.5f} | {100 * x['pit_max_dev']:.2f} pts | " + " | ".join(
                f"{pct(x['ge'][k]['pred'])} / {pct(x['ge'][k]['act'])}" for k in ("1", "2", "3", "4")) + " |")
        L += ["", "PIT deciles (new): " + ", ".join(f"{100 * v:.1f}" for v in r["new"]["pit"]), ""]
        L += ["By projection tier (new; predicted / actual):", "", "| tier | n | P(≥1) | P(≥2) | P(≥3) | P(≥4) |", "|---|---|---|---|---|---|"]
        edges = fit_props.TIER_EDGES["shots_on_goal"]
        labels = [f"< {edges[0]}"] + [f"{a}-{b}" for a, b in zip(edges, edges[1:])] + [f"{edges[-1]}+"]
        for i, t in r["new"]["by_tier"].items():
            L.append(f"| {labels[int(i)]} | {t['n']} | " + " | ".join(f"{pct(t[k]['pred'])} / {pct(t[k]['act'])}" for k in ("1", "2", "3", "4")) + " |")
        L.append("")
    # 2
    L += ["## 2. Calibration by side and line (item 2)", "", "### Every player-game, book-style lines (model P(over) 25-75%)", "",
          "| season | side | line | n | predicted | actual | gap |", "|---|---|---|---|---|---|---|"]
    for season, cells in rep["synthetic"].items():
        for c in cells:
            L.append(f"| {NAME[int(season)]} | {c['side']} | {c['line']} | {c['n']} | {pct(c['pred'])} | {pct(c['actual'])} | {100 * (c['actual'] - c['pred']):+.1f} |")
    L += ["", "### Real graded DraftKings lines, this season, walk-forward (SOG's 'mean blend 50/50 (live)' row: weight chosen on these lines)", ""]
    for mk, m in rep["real"].items():
        c = m["cal"]
        L += [f"**{mk}**: {m['lines']} lines {m['from']} to {m['to']}. Model weight in the blend **{c.get('w')}** "
              f"(log-loss fit {c['blend'].get('w_fit')}, shrink {c['blend'].get('shrink')}, {c['blend'].get('basis', '')}); "
              f"side-split slopes b {c['b']} / b_under {c['b_under']}; per-line intercepts {'used' if c.get('line_a_used') else 'not used (no walk-forward gain)'}.", "",
              "| probability | n | Brier | log loss |", "|---|---|---|---|"]
        for k, v in m["scores"].items():
            L.append(f"| {k} | {v['n']} | {v['brier'] if v['brier'] is not None else '–'} | {v['logloss'] if v['logloss'] is not None else '–'} |")
        for nm in ("raw", "final"):
            lab = nm if nm == "raw" else ("final = the board's probability (the 50/50 mean blend)" if mk == "sog" and (m.get("live") or {}).get("kind") == "mean_blend"
                                          else "final = the board's probability (the fitted blend)")
            L += ["", f"Reliability, {lab}:", "", "| side | line | n | predicted | actual | gap | ±3 pts (n ≥ 200) |", "|---|---|---|---|---|---|---|"]
            for r in m["reliability"][nm]:
                gap = r["actual"] - r["pred"]
                L.append(f"| {r['side']} | {r['line']} | {r['n']} | {pct(r['pred'])} | {pct(r['actual'])} | {100 * gap:+.1f} | "
                         f"{('✓' if abs(gap) <= .03 else '✗') if r['n'] >= 200 else 'n < 200'} |")
        d = m.get("disagree_wf") or {}
        L += ["", f"Model's side where it and DK no-vig disagree (walk-forward): {d.get('hit')}-{(d.get('n') or 0) - (d.get('hit') or 0)} ({pct(d.get('pct'))}), against a 57.7% 1x break-even.", ""]
    # 4
    L += ["## 3. Rule-passing legs on real lines (items 3 and 9)", "",
          "Walk-forward on every DK line the tracker logged with a pre-game price (one line per player and date: the line in the last pre-game call; "
          "an independent recompute on every DK quote, 4,358 SOG lines, gives the same SOG record within one standard error). New = the live TAKE rule choosing as if the side were a 1x DFS leg: market support (its own side ≥ 55%) and blended p over the bar (SOG: the 50/50 mean blend at ≥ 62%, no model-agrees check; its bars were chosen on these dates, so SOG 'new' is in-sample for the bars; points: the fitted blend at ≥ 58%, model agrees). Old = calibrated model blended 60/40 at p ≥ 58%. Both rules on the same warm weeks.",
          "Each pick is settled three ways. **1x** is hypothetical: DFS boards discount exactly these sides (on Nov 3-8 Pick6 paid ≥1x on 0 sides DK priced at 54%+), so it overstates. **DK price** is DraftKings' own odds. **Real DFS** settles only the sides a Pick6-style board would offer at ≥ 1x, at that multiplier, using the measured map (DK no-vig under 50%: 1.00x, 50-54%: 0.94x, 54%+: 0.8x). A rule that needs the market's side at 55%+ therefore has 0 real DFS legs by construction; the data agrees (of 1,999 graded Pick6 SOG legs, none qualified at ≥ 1x). ± is one standard error.", "",
          "| market | rule | legs | record | hit % | units 1x (hypothetical) | ROI at DK price | real DFS legs | ROI real DFS |", "|---|---|---|---|---|---|---|---|---|"]
    fse = lambda v: f" ± {100 * v:.1f}" if v is not None else ""
    for mk, r in rep["rule_legs"].items():
        for nm in ("old", "new"):
            for lab, y in [(nm, r[nm])] + [(f"{nm}, {'MORE' if s == 'OVER' else 'LESS'}", y) for s, y in r[nm + "_by_side"].items()]:
                L.append(f"| {mk} | {lab} | {y['n']} | {y['hit']}-{y['n'] - y['hit']} | {pct(y['pct'])}{fse(y.get('se'))} | {y['units_1x']:+.2f} | "
                         f"{pct(y.get('roi_dk'))}{fse(y.get('roi_dk_se'))} | {y.get('real_n', 0)} ({y.get('real_hit', 0)} hit) | {pct(y.get('roi_real'))} |")
    # 5
    s = rep["saves"]; l3 = s["last30"]
    L += ["", "## 4. Saves (items 6 and 11)", "",
          f"Rolling bias correction (30-day half-life, shrunk by 20 starts), last 30 days ({l3['n']} starts): mean actual − projected "
          f"**{l3['err_before']:+.2f} → {l3['err_after']:+.2f}** saves (MAE {l3['mae_before']:.2f} → {l3['mae_after']:.2f}).", "",
          f"Real lines: {s['lines']['n']} goalie-nights ({', '.join(f'{k} {v}' for k, v in s['lines']['books'].items())}).", "",
          "| projection | side | n | predicted | actual |", "|---|---|---|---|---|"]
    for col, c in s["calibration"].items():
        for side, v in c.items():
            L.append(f"| {'bias-corrected' if col == 'projc' else 'before'} | {side} | {v['n']} | {pct(v['pred'])} | {pct(v['act'])} |")
    L += ["", "Record and ROI by edge threshold (projection − line in the pick direction; DK lines at their price, DFS at the 1x break-even):", "",
          "| projection | edge | side | n | record | hit % | units | ROI |", "|---|---|---|---|---|---|---|---|"]
    for col, tab in s["thresholds"].items():
        for t in tab:
            L.append(f"| {'bias-corrected' if col == 'projc' else 'before'} | {t['edge']} | {t['side']} | {t['n']} | {t['hit']}-{t['miss']} | {pct(t['pct'])} | {t['units']:+.2f} | {pct(t['roi'])} |")
    L += ["", "## 5. Role changes (item 5)", "",
          "Not measurable yet: there is no history of pre-game line combinations, so the role-change subset can't be backtested. From this build on every displayed leg is logged with its role-change tag (model/data/legs.csv), and the Results tab will show that subset once it grades.", ""]
    return "\n".join(L) + "\n"


def main():
    years = [2024, 2025, 2026, 2027]
    sk = sog.load(years)
    log = tracker._read_log()
    prices = pd.read_csv(os.path.join(HERE, "data", "dk_prices.csv"))
    rep = {"built": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}
    prm_s = sog.SogParams.load(os.path.join(OUT, "sog_params.json"))
    prm_p = sog.SogParams.load(os.path.join(OUT, "points_params.json"))
    rows_s, _ = sog.run(sk, prm_s, record_from=2025)
    rows_p, _ = sog.run(sk, prm_p, record_from=2025, stat="points")
    print("rows ready")
    rep["distribution"] = distribution(rows_s, prm_s, "shots_on_goal")
    rep["synthetic"] = synthetic_reliability(rows_s, prm_s, "shots_on_goal")
    tg, st_df = data.load_all(years, refresh=False)
    df, _ = engine.run(tg, st_df, engine.Params.load(os.path.join(OUT, "params.json")))
    cal = calibrate.fit(log, build_site.saves_rows(df, 2027), build_site.DIST, prices,
                        sog_rows=rows_s[rows_s.season == 2027], sog_prm=prm_s,
                        points_rows=rows_p[rows_p.season == 2027], points_prm=prm_p)
    rep["real"] = {mk: {k: m.get(k) for k in ("cal", "scores", "reliability", "disagree_wf", "lines", "from", "to", "live")}
                   for mk, m in cal["markets"].items()}
    rep["rule_legs"] = rule_legs(log, rows_s[rows_s.season == 2027], prm_s, rows_p[rows_p.season == 2027], prm_p, prices)
    rep["saves"] = saves(log, df, prices)
    os.makedirs(REPORTS, exist_ok=True)
    json.dump(rep, open(os.path.join(OUT, "audit_backtest.json"), "w"), indent=1, default=build_site._np)
    text = md(json.loads(json.dumps(rep, default=build_site._np)))
    open(os.path.join(REPORTS, "audit_backtest.md"), "w").write(text)
    print(text)


if __name__ == "__main__":
    main()
