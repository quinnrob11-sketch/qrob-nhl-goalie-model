"""Probability calibration and the real-line backtest, refit on every build.

For each market (saves, SOG) it takes every graded real line in real_line_log.csv that has a
price, plus the model's raw P(over) for it:
  * saves: recomputed with the CURRENT saves model (walk-forward engine rows, no lookahead), so the
    calibration always matches the model in use;
  * SOG: recomputed with the CURRENT SOG model (walk-forward sog.run rows), falling back to the
    P(over) logged at pick time for lines that don't match a projection.

Outputs (model/output/calibration.json, shown on the Backtest tab):
  * calibration per market, fitted on all graded history (used for tonight's picks). It is
    side-split with no intercept: lines the raw model leans OVER and lines it leans UNDER each get
    their own slope on logit(p), so 50% stays 50% and no intercept can push every line to one side.
    Below MIN_CAL_N (500) graded lines the slopes are shrunk toward identity by n / 500;
  * a walk-forward replay: each week is calibrated only on earlier weeks, blended with the no-vig
    market (pricing.BLEND_W), and decided by the live rule (pricing.decide), then graded at the
    real price -> hit %, units, ROI by side and EV tier (HIGH > MED > LOW ordering reported);
  * the tier gate: tiers are capped at LOW until a market has 150 forward-graded plays (logged with a
    price-aware EV) hitting above 57.7% (2-pick 1x DFS break-even) with positive ROI;
  * the old rule (edge / probability tiers, no price) on the same lines, for comparison;
  * calibration buckets (predicted vs actual), overall and by side for raw / calibrated / final.
"""
from __future__ import annotations

import datetime as dt
import math

import numpy as np
import pandas as pd

import prices as dkp
import pricing
import prizepicks
import saves_dist

MIN_TIER_N = 30
SLOPE_MIN, SLOPE_MAX = 0.5, 1.25   # side-split calibration slopes are kept in this range
GATE_N = 150                      # forward-graded plays a market needs before tiers above LOW...
GATE_HIT = pricing.dfs_break_even(1.0)   # ...with a hit rate above 2-pick 1x DFS break-even (57.7%)...
                                         # ...and positive ROI


def forward_gate(log: list[dict]) -> dict:
    """Tier gate from plays graded going forward (rows logged with a price-aware EV), de-duplicated the
    way the tracker counts them. Tiers stay capped at LOW until a market has GATE_N such plays with
    hit rate above GATE_HIT and ROI above zero. Also returns the forward record by tier and by side."""
    import tracker
    best = {}
    for r in log:
        if r.get("result") not in ("HIT", "MISS", "PUSH") or r["market"] not in ("saves", "sog") or r.get("ev") in (None, ""):
            continue
        k = (r["date"], r["market"], r["player"], r["team"])
        if k not in best or tracker.BOOK_PREF.get(r.get("book"), 9) < tracker.BOOK_PREF.get(best[k].get("book"), 9):
            best[k] = r
    out = {}
    for mk in MARKETS:
        plays = [r for r in best.values() if r["market"] == mk and tracker.is_play(r)]
        rec = tracker._rec(plays)
        n = rec["hit"] + rec["miss"]
        ok = n >= GATE_N and (rec["pct"] or 0) > GATE_HIT and (rec["roi"] or 0) > 0
        out[mk] = {"open": bool(ok), "plays": n, "need": GATE_N, "hit_needed": round(GATE_HIT, 4), "record": rec,
                   "by_tier": {t: tracker._rec([r for r in plays if r.get("tier") == t]) for t in ("HIGH", "MED", "LOW")},
                   "by_side": {s: tracker._rec([r for r in plays if r["side"].upper() == s]) for s in ("OVER", "UNDER")}}
    return out


def _lg(p):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def platt_fit(p, y, l2=1.0):
    """Logistic recalibration of logit(p), lightly regularised toward identity (a=0, b=1)."""
    X = np.c_[np.ones(len(p)), _lg(np.asarray(p, float))]
    w = np.array([0.0, 1.0]); prior = w.copy(); y = np.asarray(y, float)
    for _ in range(60):
        q = 1 / (1 + np.exp(-(X @ w)))
        g = X.T @ (q - y) + l2 * (w - prior)
        H = (X.T * (q * (1 - q))) @ X + l2 * np.eye(2)
        w = w - np.linalg.solve(H, g)
    return {"a": round(float(w[0]), 4), "b": round(float(w[1]), 4), "n": int(len(p))}


def _slope_fit(x, y, l2=1.0):
    """P(y) = sigmoid(b x), no intercept, regularised toward b = 1."""
    b = 1.0
    for _ in range(50):
        q = 1 / (1 + np.exp(-b * x))
        g = np.sum(x * (q - y)) + l2 * (b - 1)
        h = np.sum(x * x * q * (1 - q)) + l2
        b -= g / h
    return float(b)


def side_fit(p_over, went_over, push=None, min_n=None):
    """Side-split calibration with no intercept: lines the raw model leans OVER get slope b, lines it
    leans UNDER get b_under, both fitted on P(that side wins) = sigmoid(b x logit(p_side)). Each side's
    slope is shrunk toward 1 by (that side's lines) / MIN_CAL_N and kept in [SLOPE_MIN, SLOPE_MAX]."""
    min_n = min_n or pricing.MIN_CAL_N
    p = np.asarray(p_over, float); y = np.asarray(went_over, bool)
    keep = ~np.asarray(push, bool) if push is not None else np.ones(len(p), bool)
    p, y = p[keep], y[keep]
    lean_over = p >= 0.5
    out = {"a": 0.0, "n": int(len(p)), "n_over": int(lean_over.sum()), "n_under": int((~lean_over).sum())}
    lam = min(1.0, len(p) / min_n)
    for key, m, win in (("b", lean_over, y), ("b_under", ~lean_over, ~y)):
        raw = _slope_fit(np.abs(_lg(p[m])), win[m].astype(float)) if m.sum() >= 20 else 1.0
        out[key + "_fit"] = round(raw, 4)
        # each side is shrunk by its own line count, and the slope is kept in [SLOPE_MIN, SLOPE_MAX]: a steep
        # slope fitted on lines near 50% would otherwise be extrapolated to a lopsided line (points overs had
        # b = 2.24 from 135 lines, turning a raw 82% into 96%)
        lam_s = min(lam, m.sum() / min_n)
        out[key] = round(min(max(1 + lam_s * (raw - 1), SLOPE_MIN), SLOPE_MAX), 4)
        out[key + "_shrink"] = round(lam_s, 3)
    out["shrink"] = round(lam, 3)
    out["mode"] = "full" if lam >= 1 else f"shrunk {lam:.2f} toward identity (n < {min_n})"
    return out


def _profit(price, win, push):
    pr = np.asarray(price, float)
    pay = np.where(pr < 0, 100 / -pr, pr / 100)
    return np.where(push, 0.0, np.where(win, pay, -1.0))


def _rec(win, prof, push):
    n = int(len(win)); graded = ~np.asarray(push, bool)
    w = np.asarray(win, bool)[graded]
    return {"n": n, "hit": int(w.sum()), "miss": int((~w).sum()),
            "pct": round(float(w.mean()), 4) if len(w) else None,
            "units": round(float(np.sum(prof)), 2), "roi": round(float(np.sum(prof)) / n, 4) if n else None}


def _buckets(p_side, win):
    b = pd.DataFrame({"p": p_side, "w": win}).groupby(
        pd.cut(p_side, [0.5, 0.55, 0.6, 0.65, 0.7, 1.0]), observed=True).agg(pred=("p", "mean"), act=("w", "mean"), n=("w", "size"))
    return [{"bucket": str(i), "pred": round(r.pred, 3), "actual": round(r.act, 3), "n": int(r.n)} for i, r in b.iterrows()]


MARKETS = ("saves", "sog", "points")
WEEK0 = pd.Timestamp("2000-01-03")          # a Monday: walk-forward weeks are counted from here


def week_key(dates) -> pd.Series:
    """Monotonic week number for walk-forward splits. ISO week numbers restart at 1 on New Year, so a split on
    them would train October-December weeks on January data; this count never wraps."""
    return ((pd.to_datetime(pd.Series(dates)).dt.normalize() - WEEK0).dt.days // 7).astype(int).values
BLEND_GRID = np.round(np.linspace(0, 1, 21), 2)
DISAGREE_MIN_N = 100          # disagreements needed before the model weight is shrunk by their record
# Weight on the model until 200 walk-forward lines exist: never an in-sample fit. On 2026-11-03 the points
# weight was fitted in-sample on 488 lines (0.75); it made 18 of the first 20 live TAKEs, which went 9-9.
# Walk-forward, the log-loss optimum was about 0.3 for points (flat 0.1-0.6) and 0-0.4 for saves.
W_DEFAULT = {"sog": 0.0, "points": 0.3, "saves": 0.05}
W_CAP = {"sog": 1.0, "points": 0.5, "saves": 0.4}   # walk-forward optima sit well below these
LINE_L2 = 50.0                # per-line intercepts are shrunk hard toward 0


def logloss(p, y):
    p = np.clip(np.asarray(p, float), 1e-4, 1 - 1e-4); y = np.asarray(y, float)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))) if len(p) else None


def brier(p, y):
    return float(np.mean((np.asarray(p, float) - np.asarray(y, float)) ** 2)) if len(p) else None


def disagreement(p_model_over, p_mkt_over, went_over) -> dict:
    """Record of the model's side on lines where it and the no-vig market lean opposite ways."""
    pm, mk, y = (np.asarray(a, float) for a in (p_model_over, p_mkt_over, went_over))
    d = (pm >= .5) != (mk >= .5)
    win = np.where(pm >= .5, y, 1 - y)[d]
    return {"n": int(d.sum()), "hit": int(win.sum()), "pct": round(float(win.mean()), 4) if d.any() else None}


def fit_blend(p_model_over, p_mkt_over, went_over) -> dict:
    """Weight on the (calibrated) model in w x model + (1 - w) x market, by log loss over a grid. When the
    model's record on lines where it disagrees with the market is below the 1x DFS break-even (57.7%),
    the weight is shrunk by (hit - 50%) / (break-even - 50%), floored at 0."""
    pm, mk, y = (np.asarray(a, float) for a in (p_model_over, p_mkt_over, went_over))
    if len(pm) < 50:
        return {"w": pricing.BLEND_W, "w_fit": None, "shrink": 1.0, "disagree": None, "n": int(len(pm))}
    lls = [logloss(w * pm + (1 - w) * mk, y) for w in BLEND_GRID]
    w_fit = float(BLEND_GRID[int(np.argmin(lls))])
    dis = disagreement(pm, mk, y)
    be = pricing.dfs_break_even(1.0)
    shrink = 1.0
    if dis["n"] >= DISAGREE_MIN_N and dis["pct"] < be:
        shrink = max(0.0, (dis["pct"] - 0.5) / (be - 0.5))
    return {"w": round(w_fit * shrink, 3), "w_fit": w_fit, "shrink": round(shrink, 3), "disagree": dis, "n": int(len(pm))}


def _icpt(p, y, l2=LINE_L2):
    """Intercept-only logistic recalibration on logit(p), shrunk toward 0."""
    z = _lg(np.asarray(p, float)); y = np.asarray(y, float); a = 0.0
    for _ in range(30):
        q = 1 / (1 + np.exp(-(a + z)))
        a -= (np.sum(q - y) + l2 * a) / (np.sum(q * (1 - q)) + l2)
    return float(a)


def line_intercepts(p_cal_over, lines, went_over, min_n=30) -> dict:
    b = np.array([pricing.line_bucket(x) for x in lines])
    return {k: round(_icpt(np.asarray(p_cal_over)[b == k], np.asarray(went_over)[b == k]), 4)
            for k in sorted(set(b)) if k and (b == k).sum() >= min_n}


def reliability_side_line(p_over, lines, went_over) -> list[dict]:
    """Predicted vs actual for the side each probability leans to, by side (More / Less) and line bucket."""
    p = np.asarray(p_over, float); y = np.asarray(went_over, bool)
    so = p >= .5; ps = np.where(so, p, 1 - p); win = np.where(so, y, ~y)
    b = np.array([pricing.line_bucket(x) for x in lines])
    out = []
    for side, m0 in (("More", so), ("Less", ~so)):
        for k in sorted(set(b)):
            m = m0 & (b == k)
            if m.any():
                out.append({"side": side, "line": k, "n": int(m.sum()), "pred": round(float(ps[m].mean()), 4),
                            "actual": round(float(win[m].mean()), 4)})
    return out


def _prop_params(prm):
    """SogParams for a skater market; a bare number is the old fixed negative-binomial size."""
    import sog
    if prm is None or isinstance(prm, (int, float)):
        return sog.SogParams(disp=float(prm or 12.0), disp_k=0.0)
    return prm


def lines_frame(log: list[dict], saves_rows: pd.DataFrame | None, dist_prm: dict,
                sog_rows: pd.DataFrame | None = None, sog_prm=None,
                points_rows: pd.DataFrame | None = None, points_prm=None, all_books: bool = False) -> pd.DataFrame:
    """Graded lines with the model's raw P(over), recomputed with the CURRENT models (walk-forward rows)
    where they match; otherwise the P(over) logged at pick time. Priced DraftKings lines only, unless
    all_books (every book, for calibration checks that don't need a price)."""
    rows = [r for r in log if r.get("result") in ("HIT", "MISS", "PUSH") and r["market"] in MARKETS
            and (all_books or (r.get("book") == "DraftKings" and r.get("price") not in (None, "")))]
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    for c in ("line", "price", "actual", "model_p", "model_proj"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["side_over"] = df.side.str.upper().isin(["OVER", "MORE"])
    df["went_over"] = df.actual > df.line
    df["push"] = df.actual == df.line
    # the other side's price is not in the log; recover it from the stored DK snapshot when present
    df["p_over_old"] = np.where(df.side_over, df.model_p, 1 - df.model_p)
    df["p_over"] = df.p_over_old
    if saves_rows is not None and len(saves_rows):
        s = saves_rows.copy()
        s["date"] = pd.to_datetime(s.date).dt.strftime("%Y-%m-%d")
        s["key"] = s.goalie.map(prizepicks.name_key)
        df["key"] = df.player.map(prizepicks.name_key)
        m = df[df.market == "saves"].reset_index().merge(s[["date", "key", "team", "exp_sa", "share", "sv", "p_win"]],
                                                         on=["date", "key", "team"], how="left").set_index("index")
        newp = [saves_dist.p_over(**_sp(r, dist_prm)) if r.exp_sa == r.exp_sa else np.nan for r in m.itertuples()]
        df.loc[m.index, "p_over"] = newp
    import sog
    for mk, prop_rows, prm in (("sog", sog_rows, sog_prm), ("points", points_rows, points_prm)):
        if prop_rows is None or not len(prop_rows):
            continue
        prm = _prop_params(prm)
        s = prop_rows.copy()
        s["date"] = pd.to_datetime(s.date).dt.strftime("%Y-%m-%d")
        s["key"] = s.player.map(prizepicks.name_key)
        s = s.drop_duplicates(["date", "key", "team"])
        df["key"] = df.player.map(prizepicks.name_key)
        m = df[df.market == mk].drop(columns=["pos"], errors="ignore").reset_index().merge(
            s[["date", "key", "team", "proj", "pos"]], on=["date", "key", "team"], how="inner").set_index("index")
        df.loc[m.index, "p_over"] = [sog.p_over(pj, ln, sog.size_for(pj, prm, ps)) for pj, ln, ps in zip(m.proj, m.line, m.pos)]
        df.loc[m.index, "model_proj"] = m.proj.values
        df.loc[m.index, "pos"] = m.pos.values
    return df.dropna(subset=["p_over", "actual"] if all_books else ["p_over", "price", "actual"])


def _sp(r, prm):
    x = saves_dist.project(r.exp_sa, r.share, r.sv, r.p_win, prm)
    return {"proj": x["proj"], "sd": x["sd"], "line": r.line}


def _side_buckets(p_over, went_over, push):
    """Predicted vs actual for the side each probability leans to, split OVER / UNDER."""
    p_over = np.asarray(p_over, float); keep = ~np.asarray(push, bool)
    so = p_over >= 0.5
    p_side = np.where(so, p_over, 1 - p_over)
    win = np.where(so, went_over, ~np.asarray(went_over, bool))
    return {"OVER": _buckets(p_side[keep & so], win[keep & so]), "UNDER": _buckets(p_side[keep & ~so], win[keep & ~so])}


def _mkt(x):
    return np.array([pricing.novig(o, u) for o, u in zip(x.over, x.under)], float)


def calibrate_market(p_over, lines, went_over, push, mkt) -> dict:
    """The full calibration for one market from graded lines: side-split slopes, the fitted market blend
    weight, and per-line intercepts (`line_a`, kept only by fit() when they win walk-forward)."""
    cal = side_fit(p_over, went_over, push)
    keep = ~np.asarray(push, bool)
    pc = np.array([pricing.platt(p, cal) for p in np.asarray(p_over)[keep]])
    y = np.asarray(went_over, float)[keep]; mk = np.asarray(mkt, float)[keep]
    ok = ~np.isnan(mk)
    cal["blend"] = fit_blend(pc[ok], mk[ok], y[ok])
    cal["w"] = cal["blend"]["w"]
    cal["line_a_fit"] = line_intercepts(pc, np.asarray(lines)[keep], y)
    return cal


def replay(x: pd.DataFrame, mk: str) -> pd.DataFrame:
    """Walk-forward: each week's lines are calibrated on earlier weeks only (side-split slopes, the market
    blend weight fitted by log loss, and the per-line intercept candidate), then decided with the live rule
    (pricing.decide); the one-sided night warning is recorded, not applied. Returns one row per line with
    the decision and its result, plus p_line_over (the same with per-line intercepts) and p_fixed_over (the
    old fixed 0.6 blend) for comparison."""
    y = x.went_over.values; push = x.push.values; mkt = _mkt(x)
    rows = []
    wf_pc, wf_mk, wf_y = [], [], []          # earlier weeks' out-of-sample calibrated p, market p, outcome
    for wk in sorted(x.wk.unique()):
        te, tr = (x.wk == wk).values, (x.wk < wk).values
        cal = calibrate_market(x.p_over.values[tr], x.line.values[tr], y[tr], push[tr], mkt[tr]) if tr.sum() >= 50 else None
        if cal is not None:
            # same as tonight's fit: the weight comes from earlier weeks' walk-forward probabilities once there are 200
            ok = [i for i in range(len(wf_pc)) if wf_mk[i] == wf_mk[i]]
            if len(ok) >= 200:
                cal["w"] = min(fit_blend(np.array(wf_pc)[ok], np.array(wf_mk)[ok], np.array(wf_y)[ok])["w"], W_CAP.get(mk, 1.0))
            else:                                   # as live: a fixed default until 200 walk-forward lines, never in-sample
                cal["w"] = W_DEFAULT.get(mk, 0.0)
        cal_line = dict(cal, line_a=cal["line_a_fit"]) if cal else None
        if cal is not None:
            for r, m_ in zip(x[te].itertuples(), mkt[te]):
                if not r.push:
                    wf_pc.append(pricing.platt(r.p_over, cal)); wf_mk.append(m_); wf_y.append(float(r.went_over))
        for r, m_ in zip(x[te].itertuples(), mkt[te]):
            d = pricing.decide(r.p_over, cal, r.over, r.under, market=mk, proj=r.model_proj, line=r.line)
            pl, _, _ = pricing.final_p_over(r.p_over, cal_line, r.over, r.under, line=r.line)
            pf, _, _ = pricing.final_p_over(r.p_over, cal, r.over, r.under, w=pricing.BLEND_W)
            rows.append({"idx": r.Index, "date": r.date, "side": d["side"], "p": d["p"], "ev": d["ev"], "play": d["play"],
                         "tier": pricing.tier(d["ev"]) if d["play"] else "PASS", "price": r.over if d["side"] == "OVER" else r.under,
                         "p_cal_over": d["p_model"], "p_final_over": d["p"] if d["side"] == "OVER" else 1 - d["p"],
                         "p_line_over": pl, "p_fixed_over": pf, "p_mkt_over": m_, "w": cal["w"] if cal else pricing.BLEND_W,
                         "warm": cal is not None})
    # one-sided board warning per night: display only, it never removes a play
    for d in sorted({r["date"] for r in rows}):
        night = [r for r in rows if r["date"] == d]
        al = pricing.night_alarm(night)
        for r in night:
            r["play_raw"] = r["play"]
            r["alarm"] = al["alarm"]
    out = pd.DataFrame(rows).set_index("idx").loc[x.index]
    out["win"] = np.where(out.side == "OVER", x.went_over, ~x.went_over)
    out["push"] = push
    out["prof"] = _profit(out.price.values, out.win.values, push)
    return out


def realistic_mult(nv_side: float) -> float:
    """The multiplier a Pick6-style board offers on a side the market prices at no-vig `nv_side` (measured on the
    Nov 3-8 boards: under 50% about 1.00x, 50-54% about 0.94x, 54%+ about 0.8x; none of the 54%+ sides at 1x)."""
    return 1.0 if nv_side < 0.50 else 0.94 if nv_side < 0.54 else 0.8


def mean_blend_p(proj, line, nv_over, prm, pos=None, w=None) -> float:
    """SOG P(over `line`) from the mean-space blend: (1 - w) x projection + w x the NB mean that reproduces the
    market's no-vig `nv_over` at that line, priced with the model's dispersion (props_board.score_lines does the same)."""
    import sog
    w = pricing.SOG_MEAN_W if w is None else w
    mu_m = sog.implied_mean(nv_over, line, prm, pos) if nv_over == nv_over and nv_over is not None else None
    if mu_m is None or proj != proj:
        return np.nan
    mu = (1 - w) * float(proj) + w * mu_m
    return float(sog.p_over(mu, line, sog.size_for(mu, prm, pos)))


def rule_record(x: pd.DataFrame, r: pd.DataFrame, mk: str) -> dict:
    """The live TAKE rule (pricing.verdict: market support, blended p over the bar, model agrees where the market
    requires it) replayed on the warm walk-forward weeks only, choosing as if each side were a 1x DFS leg, and settled
    three ways: at DraftKings' own price; as a hypothetical 1x leg (overstates: DFS boards discount these sides); and
    only where a DFS board would really offer the side at >= 1x (realistic_mult), at that multiplier. Hit rates and
    ROI carry one SE. SOG uses the live mean blend (p_mb_over) with the raw model as p_model; it fits nothing week by
    week, so every week counts, but its 0.5 weight and its 62% / 55% bars were chosen on these dates (in-sample for
    those three numbers; bars re-chosen from earlier weeks only give the same record within one SE)."""
    be1 = pricing.dfs_break_even(1.0)
    mb = mk == "sog" and "p_mb_over" in x
    picks = []
    for i, row in enumerate(x.itertuples()):
        if row.push or not (mb or r.warm.iloc[i]):
            continue
        pk = r.p_mkt_over.iloc[i]
        if mb:
            pf = row.p_mb_over
            if pf != pf:
                continue
            v = pricing.verdict(mk, pf, row.p_over, row.line, row.model_proj, 1.0, 1.0, p_mkt_over=None if pk != pk else pk)
        else:
            v = pricing.verdict(mk, r.p_final_over.iloc[i], r.p_cal_over.iloc[i], row.line, row.model_proj, 1.0, 1.0,
                                p_mkt_over=None if pk != pk else pk)
        if not v["verdict"].startswith("TAKE"):
            continue
        win = bool(row.went_over) == (v["side"] == "OVER")
        price = row.over if v["side"] == "OVER" else row.under
        m = realistic_mult(pk if v["side"] == "OVER" else 1 - pk)
        picks.append({"side": v["side"], "win": win, "r_dk": pricing.profit(price) if win else -1.0,
                      "r_1x": (1 / be1 - 1) if win else -1.0,
                      "r_real": ((m / be1 - 1) if win else -1.0) if m >= pricing.MIN_MULT else None})
    def rec(z):
        se = lambda v: round(float(np.std(v, ddof=1) / np.sqrt(len(v))), 4) if len(v) > 1 else None
        w = [float(q["win"]) for q in z]; real = [q["r_real"] for q in z if q["r_real"] is not None]
        return {"n": len(z), "hit": int(sum(w)), "pct": round(float(np.mean(w)), 4) if z else None, "se": se(w),
                "roi_dk": round(float(np.mean([q["r_dk"] for q in z])), 4) if z else None, "roi_dk_se": se([q["r_dk"] for q in z]),
                "roi_1x": round(float(np.mean([q["r_1x"] for q in z])), 4) if z else None,
                "real_n": len(real), "roi_real": round(float(np.mean(real)), 4) if real else None}
    return {"all": rec(picks), "over": rec([q for q in picks if q["side"] == "OVER"]),
            "under": rec([q for q in picks if q["side"] == "UNDER"]),
            "basis": ("live TAKE rule (50/50 mean blend, no Platt), every week, DraftKings lines with a pre-game price; "
                      "the 50/50 weight and the 62% / 55% bars were chosen on these dates") if mb else
                     "live TAKE rule, warm walk-forward weeks, DraftKings lines with a pre-game price"}


def _final_buckets(x: pd.DataFrame, r: pd.DataFrame, mk: str, push) -> dict:
    """Side buckets of the live final probability (SOG: the mean blend, lines where it could be formed)."""
    if mk == "sog" and "p_mb_over" in x:
        p = x.p_mb_over.values.astype(float); f = np.isfinite(p)
        return _side_buckets(p[f], x.went_over.values[f], np.asarray(push, bool)[f])
    return _side_buckets(r.p_final_over.values, x.went_over.values, push)


def _by_side(r: pd.DataFrame, m) -> dict:
    m = np.asarray(m, bool)
    o, u = m & (r.side == "OVER").values, m & (r.side == "UNDER").values
    return {"plays": _rec(r.win.values[m], r.prof.values[m], r.push.values[m]),
            "overs": _rec(r.win.values[o], r.prof.values[o], r.push.values[o]),
            "unders": _rec(r.win.values[u], r.prof.values[u], r.push.values[u])}


def fit(log: list[dict], saves_rows: pd.DataFrame | None, dist_prm: dict, prices: pd.DataFrame | None = None,
        sog_rows: pd.DataFrame | None = None, sog_prm=None, points_rows: pd.DataFrame | None = None,
        points_prm=None) -> dict:
    df = lines_frame(log, saves_rows, dist_prm, sog_rows, sog_prm, points_rows, points_prm)
    out = {"updated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "markets": {},
           "rule": {"blend_w": pricing.BLEND_W, "min_cal_n": pricing.MIN_CAL_N, "blend": "fitted by log loss per market"}}
    if df.empty:
        return out
    # both sides' prices from the DraftKings snapshots (needed to price the side the rule picks)
    if prices is not None and len(prices):
        # the last DraftKings snapshot taken BEFORE puck drop (prices.last_pregame); the old read took the last
        # snapshot of any time, which for ~5% of lines was an in-game price
        pr = dkp.last_pregame(prices.copy()); pr["key"] = pr.name.map(prizepicks.name_key)
        pr = pr.drop_duplicates(["market", "date", "key", "line"], keep="last")
        df["key"] = df.player.map(prizepicks.name_key)
        df = df.merge(pr[["market", "date", "key", "line", "over", "under"]], on=["market", "date", "key", "line"], how="left")
    else:
        df["over"] = np.where(df.side_over, df.price, np.nan); df["under"] = np.where(~df.side_over, df.price, np.nan)
    df["wk"] = week_key(df.date)
    # shots on goal: the live probability is the 50/50 mean-space blend with the DK-implied mean (no Platt, nothing
    # fitted), so the rule record replays exactly that
    if sog_prm is not None and pricing.SOG_MEAN_W > 0 and (df.market == "sog").any():
        df["p_mb_over"] = np.nan
        prm = _prop_params(sog_prm)
        m = df[(df.market == "sog") & df.over.notna() & df.under.notna()]
        df.loc[m.index, "p_mb_over"] = [mean_blend_p(pj, ln, pricing.novig(o, u), prm, ps if isinstance(ps, str) else None)
                                         for pj, ln, o, u, ps in zip(m.model_proj, m.line, m.over, m.under, m.get("pos", [None] * len(m)))]
    gate = forward_gate(log)
    out["gate"] = gate
    for mk in MARKETS:
        x = df[df.market == mk].dropna(subset=["over", "under"]).reset_index(drop=True)
        if len(x) < 40:
            continue
        r = replay(x, mk)
        cal = calibrate_market(x.p_over.values, x.line.values, x.went_over.values, x.push.values, _mkt(x))
        # walk-forward comparison on the weeks after the first (each scored only with earlier weeks)
        wm = r.warm.values & ~x.push.values
        yy = x.went_over.values[wm].astype(float)
        scores = {}
        for name, col in (("raw model", x.p_over.values), ("calibrated model", r.p_cal_over.values),
                          ("DK no-vig", r.p_mkt_over.values), ("blend 0.6 (old)", r.p_fixed_over.values),
                          ("blend fitted (new)", r.p_final_over.values), ("blend fitted + line intercepts", r.p_line_over.values),
                          *((("mean blend 50/50 (live)", x.p_mb_over.values),) if mk == "sog" and "p_mb_over" in x else ())):
            v = np.asarray(col, float)[wm]
            f = np.isfinite(v)          # a probability that could not be formed (e.g. no position) is left out, not NaN
            v, yf = v[f], yy[f]
            scores[name] = {"n": int(f.sum()), "brier": round(brier(v, yf), 5) if len(v) else None,
                            "logloss": round(logloss(v, yf), 5) if len(v) else None}
        # tonight's blend weight: refit by log loss on the walk-forward (out-of-sample) calibrated probabilities
        # once there are enough of them, so an in-sample fit can't flatter the model
        ok = wm & ~np.isnan(r.p_mkt_over.values.astype(float))
        if ok.sum() >= 200:
            wf = fit_blend(r.p_cal_over.values[ok], r.p_mkt_over.values[ok], x.went_over.values[ok])
            cal["blend"] = {**wf, "basis": f"walk-forward ({int(ok.sum())} lines)"}
            cal["w"] = min(wf["w"], W_CAP.get(mk, 1.0))
        else:
            cal["blend"]["basis"] = f"default {W_DEFAULT.get(mk, 0.0)} ({int(ok.sum())} walk-forward lines; needs 200)"
            cal["w"] = W_DEFAULT.get(mk, 0.0)
        use_line = bool(wm.sum() >= 200 and scores["blend fitted + line intercepts"]["logloss"] < scores["blend fitted (new)"]["logloss"])
        if use_line:
            cal["line_a"] = cal["line_a_fit"]
        cal["line_a_used"] = use_line
        play, push = r.play.values, x.push.values
        tiers = {}
        for name in ("HIGH", "MED", "LOW"):
            m = play & (r.tier == name).values
            tiers[name] = _rec(r.win.values[m], r.prof.values[m], push[m])
        ok = all(tiers[t]["n"] >= MIN_TIER_N for t in tiers) and \
            tiers["HIGH"]["pct"] > tiers["MED"]["pct"] > tiers["LOW"]["pct"] and \
            tiers["HIGH"]["roi"] > tiers["MED"]["roi"] > tiers["LOW"]["roi"]
        # old rule on the same lines (side and tier as logged at pick time, at the price of that side)
        oso = x.side_over.values
        oprice = np.where(oso, x.over, x.under)
        owin = np.where(oso, x.went_over, ~x.went_over)
        oprof = _profit(oprice, owin, push)
        old = {}
        if mk == "saves":
            edge = (x.model_proj - x.line).abs().values
            for name, lo, hi in (("HIGH", 2.5, 99), ("MED", 1.5, 2.5), ("LOW", 1.0, 1.5), ("PASS", 0, 1.0)):
                m = (edge >= lo) & (edge < hi); old[name] = _rec(owin[m], oprof[m], push[m])
            m = edge >= 1.5; old["plays"] = _rec(owin[m], oprof[m], push[m])
        else:
            ps_old = np.maximum(x.p_over_old.values, 1 - x.p_over_old.values)
            for name, lo, hi in (("HIGH", .62, 1), ("MED", .58, .62), ("LOW", .55, .58), ("PASS", 0, .55)):
                m = (ps_old >= lo) & (ps_old < hi); old[name] = _rec(owin[m], oprof[m], push[m])
            m = ps_old >= .55; old["plays"] = _rec(owin[m], oprof[m], push[m])
        old["all"] = _rec(owin, oprof, push)
        blind_under = _rec(~x.went_over.values, _profit(x.under.values, ~x.went_over.values, push), push)
        raw_so = x.p_over.values >= 0.5
        new = _by_side(r, play)
        new["tiers"] = tiers
        new["before_alarm"] = _by_side(r, r.play_raw.values)
        nights = []
        for d, g in r.groupby("date"):
            pre, post = g.play_raw.values.astype(bool), g.play.values.astype(bool)
            nights.append({"date": str(d), "pre_over": int((pre & (g.side == "OVER").values).sum()), "pre_under": int((pre & (g.side == "UNDER").values).sum()),
                           "over": int((post & (g.side == "OVER").values).sum()), "under": int((post & (g.side == "UNDER").values).sum()),
                           "alarm": bool(g.get("alarm", pd.Series(dtype=object)).fillna(False).astype(bool).any())})
        new["nights"] = nights
        out["markets"][mk] = {
            "cal": cal, "platt_ref": platt_fit(x.p_over.values, x.went_over.values),
            "tier_cap": None if gate[mk]["open"] else "LOW", "tiers_ok": bool(ok), "gate": gate[mk],
            "new": new, "old": old, "blind_under": blind_under,
            "buckets_raw": _buckets(np.maximum(x.p_over.values, 1 - x.p_over.values),
                                    np.where(raw_so, x.went_over, ~x.went_over)),
            "buckets_cal": _buckets(r.p.values[~push], r.win.values[~push]),
            "buckets_side": {"raw": _side_buckets(x.p_over.values, x.went_over.values, push),
                             "calibrated": _side_buckets(r.p_cal_over.values, x.went_over.values, push),
                             # "final" = the probability the board uses: SOG's 50/50 mean blend, else the fitted blend
                             "final": _final_buckets(x, r, mk, push)},
            "lines": int(len(x)), "from": str(x.date.min()), "to": str(x.date.max()),
            "scores": scores,
            "reliability": {"raw": reliability_side_line(x.p_over.values[wm], x.line.values[wm], x.went_over.values[wm]),
                            "final": reliability_side_line((r.p_line_over if use_line else r.p_final_over).values[wm],
                                                           x.line.values[wm], x.went_over.values[wm])},
            "disagree_wf": disagreement(r.p_cal_over.values[wm], r.p_mkt_over.values[wm], x.went_over.values[wm]),
            "rule": rule_record(x, r, mk)}
    return out
