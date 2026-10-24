"""Price-aware decisions shared by the tracker, the calibration fit and the dashboard.

Final probability = BLEND_W x calibrated model + (1 - BLEND_W) x no-vig market, when the book posts both
prices (DraftKings). A side is a PLAY only when that probability beats the price's break-even by MARGIN (MARGIN_SOG for SOG,
where the projection must also sit SOG_GAP past the line in the play direction unless EV >= SOG_GAP_EV):
  * sportsbook (American odds): break-even = implied probability of that side's price;
  * DFS pick'em (Pick6 / PrizePicks): per-leg break-even = payout^(-1/legs) / multiplier.
    Only 1x sides qualify by default.
EV% = p x profit - (1 - p) per unit staked. Tiers come from EV and are capped at LOW per market
when graded history doesn't show HIGH > MED > LOW (see calibrate.py).
"""
from __future__ import annotations

import math

MARGIN = 0.02
MARGIN_SOG = 0.03           # SOG needs more: half-point lines on a discrete count lean UNDER at proj = line
SOG_GAP = 0.15              # SOG play only if the projection sits this far past the line in the play direction...
SOG_GAP_EV = 0.05           # ...unless its EV is at least this
BLEND_W = 0.6               # weight on the model in the market blend (both prices posted)
MIN_CAL_N = 500             # graded lines before a market's calibration is used at full strength
ALARM_SHARE = 0.75          # one-sided board: more than this share of a night's plays (per market) on one side...
ALARM_TOP = 0.10            # ...keeps only that night's top 10% of plays by EV
ALARM_MIN_PLAYS = 2         # a single play is trivially one-sided; two or more can trip the alarm
EV_TIERS = (("HIGH", 0.08), ("MED", 0.05), ("LOW", MARGIN))
DFS_DEFAULT = {"legs": 2, "payout": 3.0}          # 2-pick power play at 3x -> 57.7% per leg


def config() -> dict:
    """The decision knobs, exported to the page so its mirror of decide() uses the same values."""
    return {"margin": MARGIN, "margin_sog": MARGIN_SOG, "sog_gap": SOG_GAP, "sog_gap_ev": SOG_GAP_EV,
            "blend_w": BLEND_W, "min_cal_n": MIN_CAL_N,
            "alarm_share": ALARM_SHARE, "alarm_top": ALARM_TOP, "alarm_min_plays": ALARM_MIN_PLAYS}


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
    """Calibrated P(over). cal = {"a", "b"} on logit(p_raw); when the fit is side-split it also has
    "b_under": lines the raw model leans UNDER on use that slope instead (no intercept, so 50% stays 50%)."""
    if not cal:
        return p
    p = min(max(p, 1e-4), 1 - 1e-4)
    b = cal["b_under"] if "b_under" in cal and p < 0.5 else cal["b"]
    z = cal.get("a", 0.0) + b * math.log(p / (1 - p))
    return 1 / (1 + math.exp(-z))


def novig(over_price, under_price) -> float | None:
    """No-vig P(over) from both American prices, or None if either is missing."""
    o, u = implied(over_price), implied(under_price)
    return o / (o + u) if o is not None and u is not None else None


def final_p_over(p_over_raw: float, cal: dict | None, over_price=None, under_price=None, w: float = BLEND_W) -> tuple:
    """(final P(over), calibrated model P(over), no-vig market P(over) or None)."""
    pm = platt(p_over_raw, cal)
    mk = novig(over_price, under_price)
    return (pm if mk is None else w * pm + (1 - w) * mk), pm, mk


def tier(ev: float | None, cap: str | None = None) -> str:
    if ev is None:
        return ""
    t = next((name for name, lo in EV_TIERS if ev >= lo), "PASS")
    if cap == "LOW" and t in ("HIGH", "MED"):
        return "LOW"
    return t


def decide(p_over_raw: float, cal: dict | None, over_price=None, under_price=None, mult_over=None,
           mult_under=None, dfs: dict | None = None, allow_sub1x: bool = False, cap: str | None = None,
           market: str | None = None, proj: float | None = None, line: float | None = None) -> dict:
    """Pick the better side by EV. Prices are American odds (sportsbook) or None; multipliers are
    DFS per-side multipliers (1, 0.9, 0.8 ...). Returns side, p (final, that side), be, ev, tier, play,
    plus p_model / p_mkt (P(over) from the calibrated model and the no-vig market)."""
    p_over, p_model, p_mkt = final_p_over(p_over_raw, cal, over_price, under_price)
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
    margin = MARGIN_SOG if market == "sog" else MARGIN
    best["play"] = best["p"] > best["be"] + margin and best["ev"] >= margin
    if best["play"] and market == "sog" and proj is not None and line is not None and best["ev"] < SOG_GAP_EV:
        gap = proj - line if best["side"] == "OVER" else line - proj
        best["play"] = gap >= SOG_GAP - 1e-9
    best["tier"] = tier(best["ev"], cap) if best["play"] else "PASS"
    best["p_model"], best["p_mkt"] = p_model, p_mkt
    return best


def night_alarm(decisions: list[dict]) -> dict:
    """One market, one night. decisions: dicts with side / ev / play. If more than ALARM_SHARE of the
    plays are on one side, only plays at or above the night's top-ALARM_TOP EV stay plays (`thr`).
    Returns the split; apply it with apply_alarm."""
    ev = sorted((d["ev"] for d in decisions if d.get("play")), reverse=True)
    n = len(ev)
    over = sum(1 for d in decisions if d.get("play") and d["side"] == "OVER")
    share = max(over, n - over) / n if n else 0.0
    alarm = n >= ALARM_MIN_PLAYS and share > ALARM_SHARE
    keep = max(1, math.ceil(ALARM_TOP * n)) if alarm else n
    return {"plays": n, "over": over, "under": n - over, "share": round(share, 4),
            "side": ("OVER" if over * 2 > n else "UNDER" if over * 2 < n else "even") if n else None,
            "alarm": bool(alarm), "kept": keep, "thr": ev[keep - 1] if alarm else None}


def apply_alarm(d: dict, alarm: dict) -> dict:
    """Demote a play below the night's alarm threshold to PASS (in place)."""
    if alarm.get("alarm") and d.get("play") and d["ev"] < alarm["thr"] - 1e-12:
        d.update(play=False, tier="PASS", alarm=True)
    return d
