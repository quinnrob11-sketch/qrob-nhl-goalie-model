"""Probability calibration and the real-line backtest, refit on every build.

For each market (saves, SOG) it takes every graded real line in real_line_log.csv that has a
price, plus the model's raw P(over) for it:
  * saves: recomputed with the CURRENT saves model (walk-forward engine rows, no lookahead), so the
    calibration always matches the model in use;
  * SOG: the P(over) logged at pick time.

Outputs (model/output/calibration.json, shown on the Backtest tab):
  * Platt calibration per market, fitted on all graded history (used for tonight's picks);
  * a walk-forward replay: each week is calibrated only on earlier weeks, then the price-aware
    rule (calibrated p > break-even + 2%) is graded at the real price -> hit %, units, ROI by EV
    tier. If HIGH > MED > LOW doesn't hold on both hit % and ROI, the market's tiers are capped
    at LOW;
  * the old rule (edge / probability tiers, no price) on the same lines, for comparison;
  * calibration buckets (predicted vs actual).
"""
from __future__ import annotations

import datetime as dt
import math

import numpy as np
import pandas as pd

import pricing
import prizepicks
import saves_dist

MIN_TIER_N = 30


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


def _apply(p, cal):
    return 1 / (1 + np.exp(-(cal["a"] + cal["b"] * _lg(np.asarray(p, float)))))


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


def lines_frame(log: list[dict], saves_rows: pd.DataFrame | None, dist_prm: dict) -> pd.DataFrame:
    """Graded, priced DraftKings lines with the model's raw P(over)."""
    rows = [r for r in log if r.get("book") == "DraftKings" and r.get("result") in ("HIT", "MISS", "PUSH")
            and r.get("price") not in (None, "") and r["market"] in ("saves", "sog")]
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
    return df.dropna(subset=["p_over", "price", "actual"])


def _sp(r, prm):
    x = saves_dist.project(r.exp_sa, r.share, r.sv, r.p_win, prm)
    return {"proj": x["proj"], "sd": x["sd"], "line": r.line}


def fit(log: list[dict], saves_rows: pd.DataFrame | None, dist_prm: dict, prices: pd.DataFrame | None = None) -> dict:
    df = lines_frame(log, saves_rows, dist_prm)
    out = {"updated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "markets": {}}
    if df.empty:
        return out
    # both sides' prices from the DraftKings snapshots (needed to price the side the NEW rule picks)
    if prices is not None and len(prices):
        pr = prices.copy(); pr["key"] = pr.name.map(prizepicks.name_key)
        pr = pr.sort_values("snap").drop_duplicates(["market", "date", "key", "line"], keep="last")
        df["key"] = df.player.map(prizepicks.name_key)
        df = df.merge(pr[["market", "date", "key", "line", "over", "under"]], on=["market", "date", "key", "line"], how="left")
    else:
        df["over"] = np.where(df.side_over, df.price, np.nan); df["under"] = np.where(~df.side_over, df.price, np.nan)
    df["wk"] = pd.to_datetime(df.date).dt.isocalendar().week.astype(int)
    for mk in ("saves", "sog"):
        x = df[df.market == mk].dropna(subset=["over", "under"]).reset_index(drop=True)
        if len(x) < 40:
            continue
        y = x.went_over.astype(float).values
        cal = platt_fit(x.p_over.values, y)
        # walk-forward: calibrate each week on earlier weeks only
        pc = np.full(len(x), np.nan)
        for wk in sorted(x.wk.unique()):
            te, tr = (x.wk == wk).values, (x.wk < wk).values
            pc[te] = _apply(x.p_over.values[te], platt_fit(x.p_over.values[tr], y[tr])) if tr.sum() >= 50 else x.p_over.values[te]
        so = pc >= 0.5
        p_side = np.where(so, pc, 1 - pc)
        price = np.where(so, x.over, x.under)
        be = np.array([pricing.implied(v) for v in price])
        ev = p_side * np.where(price < 0, 100 / -price, price / 100) - (1 - p_side)
        win = np.where(so, x.went_over, ~x.went_over)
        push = x.push.values
        prof = _profit(price, win, push)
        play = (p_side > be + pricing.MARGIN) & (ev >= pricing.MARGIN)
        tiers = {}
        for name, lo, hi in (("HIGH", 0.08, 9), ("MED", 0.05, 0.08), ("LOW", pricing.MARGIN, 0.05)):
            m = play & (ev >= lo) & (ev < hi)
            tiers[name] = _rec(win[m], prof[m], push[m])
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
        out["markets"][mk] = {
            "cal": cal, "tier_cap": None if ok else "LOW", "tiers_ok": bool(ok),
            "new": {"plays": _rec(win[play], prof[play], push[play]), "tiers": tiers,
                    "overs": _rec(win[play & so], prof[play & so], push[play & so]),
                    "unders": _rec(win[play & ~so], prof[play & ~so], push[play & ~so])},
            "old": old, "blind_under": blind_under,
            "buckets_raw": _buckets(np.maximum(x.p_over.values, 1 - x.p_over.values),
                                    np.where(raw_so, x.went_over, ~x.went_over)),
            "buckets_cal": _buckets(p_side, win),
            "lines": int(len(x)), "from": str(x.date.min()), "to": str(x.date.max())}
    return out
