"""Price-aware decisions shared by the tracker, the calibration fit and the dashboard.

A side is a PLAY only when its calibrated probability beats the price's break-even by MARGIN:
  * sportsbook (American odds): break-even = implied probability of that side's price;
  * DFS pick'em (Pick6 / PrizePicks): per-leg break-even = payout^(-1/legs) / multiplier.
    Only 1x sides qualify by default.
EV% = p x profit - (1 - p) per unit staked. Tiers come from EV and are capped at LOW per market
when graded history doesn't show HIGH > MED > LOW (see calibrate.py).
"""
from __future__ import annotations

import math

MARGIN = 0.02
EV_TIERS = (("HIGH", 0.08), ("MED", 0.05), ("LOW", MARGIN))
DFS_DEFAULT = {"legs": 2, "payout": 3.0}          # 2-pick power play at 3x -> 57.7% per leg


def implied(american) -> float | None:
    if american in (None, "") or american != american:
        return None
    o = float(american)
    return -o / (-o + 100) if o < 0 else 100 / (o + 100)


def profit(american) -> float:
    """Profit per 1 unit staked at an American price."""
    o = float(american)
    return 100 / -o if o < 0 else o / 100


def dfs_break_even(mult: float = 1.0, legs: int = DFS_DEFAULT["legs"], payout: float = DFS_DEFAULT["payout"]) -> float:
    return payout ** (-1.0 / legs) / (mult or 1.0)


def platt(p: float, cal: dict | None) -> float:
    """Calibrated probability. cal = {"a": .., "b": ..} fitted on logit(p_raw)."""
    if not cal:
        return p
    p = min(max(p, 1e-4), 1 - 1e-4)
    z = cal["a"] + cal["b"] * math.log(p / (1 - p))
    return 1 / (1 + math.exp(-z))


def tier(ev: float | None, cap: str | None = None) -> str:
    if ev is None:
        return ""
    t = next((name for name, lo in EV_TIERS if ev >= lo), "PASS")
    if cap == "LOW" and t in ("HIGH", "MED"):
        return "LOW"
    return t


def decide(p_over_raw: float, cal: dict | None, over_price=None, under_price=None, mult_over=None,
           mult_under=None, dfs: dict | None = None, allow_sub1x: bool = False, cap: str | None = None) -> dict:
    """Pick the better side by EV. Prices are American odds (sportsbook) or None; multipliers are
    DFS per-side multipliers (1, 0.9, 0.8 ...). Returns side, p (calibrated, that side), be, ev, tier, play."""
    p_over = platt(p_over_raw, cal)
    best = None
    for side, p, price, mult in (("OVER", p_over, over_price, mult_over), ("UNDER", 1 - p_over, under_price, mult_under)):
        if price not in (None, ""):
            be = implied(price)
            ev = p * profit(price) - (1 - p)
        elif mult not in (None, ""):
            mult = float(mult)
            d = dfs or DFS_DEFAULT
            be = dfs_break_even(mult, d["legs"], d["payout"])
            ev = p / be - 1          # value per leg relative to break-even
            if mult < 1 and not allow_sub1x:
                ev = min(ev, MARGIN - 1e-9)   # sub-1x sides never qualify by default
        else:
            be, ev = 0.5, p / 0.5 - 1
        cand = {"side": side, "p": p, "be": be, "ev": ev}
        if best is None or ev > best["ev"]:
            best = cand
    best["play"] = best["p"] > best["be"] + MARGIN and best["ev"] >= MARGIN
    best["tier"] = tier(best["ev"], cap) if best["play"] else "PASS"
    return best
