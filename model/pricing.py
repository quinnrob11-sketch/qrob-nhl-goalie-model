"""Price-aware decisions shared by the tracker, the calibration fit and the dashboard.

Final probability = BLEND_W x calibrated model + (1 - BLEND_W) x no-vig market, when the book posts both
prices (DraftKings). A side is a PLAY only when that probability beats the price's break-even by MARGIN (MARGIN_SOG for SOG,
where the projection must also sit SOG_GAP past the line in the play direction unless EV >= SOG_GAP_EV):
  * sportsbook (American odds): break-even = implied probability of that side's price;
  * DFS pick'em (Pick6 / PrizePicks): per-leg break-even = payout^(-1/legs) / multiplier.
    Only 1x sides qualify by default.
EV% = p x profit - (1 - p) per unit staked. Saves probabilities of 65%+ are shown and ranked as 60%
("capped"); the decision itself is unchanged. Tiers come from EV and are capped at LOW per market
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
ALARM_SHARE = 0.75          # one-sided board warning: more than this share of a night's plays on one side
ALARM_MIN_PLAYS = 2         # (display only: the alarm never removes a play)
SAVES_CAP_AT = 0.65         # saves probabilities at or above this are shown and ranked as SAVES_CAP_TO,
SAVES_CAP_TO = 0.60         # tagged "capped" (saves rated 65%+ hit 46% on 41 graded plays)
EV_TIERS = (("HIGH", 0.08), ("MED", 0.05), ("LOW", MARGIN))
DFS_DEFAULT = {"legs": 2, "payout": 3.0}          # 2-pick power play at 3x -> 57.7% per leg

# ---- the TAKE / PASS verdict (one per player and market; see verdict() and best_line()) ----
TAKE_P = 0.58               # shots / points: blended p of the side at least this
NEAR_MISS_P = 0.55          # 55-58% shows as PASS (near miss)
LOCK_P = 0.62               # tier label on a TAKE: Lock 62%+, Strong 58-62%
MIN_MULT = 1.0              # DFS legs below 1x never TAKE
SAVES_EDGE_OVER = 2.5       # saves: bias-corrected projection minus line, in the pick direction
SAVES_EDGE_UNDER = 3.0      # unders need more until the backtest shows they are calibrated
SAVES_TAKE_P = 0.58         # saves also need calibrated p of the side at least this
SAVES_EDGE_GRID = (1.5, 2.0, 2.5, 3.0)   # edges reported in the backtest so the threshold can be chosen
SAVES_BIAS_HL = 30.0        # days; half-life of the rolling saves bias correction

# ---- limits from the out-of-sample review (model/reports/accuracy_review.md) ----
# Out of sample no model beat DraftKings' no-vig price in any market, so a TAKE needs the market's support:
# model-only SOG picks at 1x hit 52-54% (n=437), the points model's own leans 56.6% (n=235); the market's
# favoured side is what actually wins (points no-vig >= 0.55 hit 66.8%, n=832).
MKT_MIN = 0.55              # shots / points / saves: a TAKE needs a market quote whose own side is at least this
NEAR_BAND = 0.03            # near miss: p within this of the market's TAKE bar, everything else met
SOG_TAKE_P = 0.58           # shots on goal: blended p of the side at least this (see SOG section of the review)
SOG_LOCK_P = 0.62
SOG_MEAN_W = 0.0            # shots on goal: weight on the market-implied mean in the projection blend (0 = off):
                            # mu = (1 - w) x model projection + w x the NB mean that reproduces the market's no-vig
PRICED_TAKES = False        # a line priced at a sportsbook's own odds (DraftKings) is never a TAKE: walk-forward,
                            # DK-priced TAKEs hit exactly DK's no-vig and lost to the vig at every weight
                            # (points -7% to -23%; the live 10-10, -21.9%)
SAVES_TAKE_OVERS = False    # saves overs lost at every edge threshold (5-8, 1-4, 0-2; every DK over 207-235)
POINTS_UNDER_MAX = 1.0      # points unders only on lines below this: 1.5+ unders were rated 65.6% and hit 50.9%


def config() -> dict:
    """The decision knobs, exported to the page so its mirror of decide() uses the same values."""
    return {"margin": MARGIN, "margin_sog": MARGIN_SOG, "sog_gap": SOG_GAP, "sog_gap_ev": SOG_GAP_EV,
            "blend_w": BLEND_W, "min_cal_n": MIN_CAL_N,
            "alarm_share": ALARM_SHARE, "alarm_min_plays": ALARM_MIN_PLAYS,
            "saves_cap_at": SAVES_CAP_AT, "saves_cap_to": SAVES_CAP_TO,
            "take_p": TAKE_P, "near_miss_p": NEAR_MISS_P, "lock_p": LOCK_P, "min_mult": MIN_MULT,
            "saves_edge_over": SAVES_EDGE_OVER, "saves_edge_under": SAVES_EDGE_UNDER, "saves_take_p": SAVES_TAKE_P,
            "saves_bias_hl": SAVES_BIAS_HL, "mkt_min": MKT_MIN, "near_band": NEAR_BAND,
            "sog_take_p": SOG_TAKE_P, "sog_lock_p": SOG_LOCK_P, "sog_mean_w": SOG_MEAN_W, "priced_takes": PRICED_TAKES,
            "saves_take_overs": SAVES_TAKE_OVERS, "points_under_max": POINTS_UNDER_MAX}


def take_p(market: str) -> float:
    return SAVES_TAKE_P if market == "saves" else SOG_TAKE_P if market == "sog" else TAKE_P


def lock_p(market: str) -> float:
    return SOG_LOCK_P if market == "sog" else LOCK_P


def near_p(market: str) -> float:
    return take_p(market) - NEAR_BAND


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


def line_bucket(line) -> str:
    """Line bucket for calibration: 0.5 / 1.5 / 2.5 / 3.5+ (skaters)."""
    try:
        x = float(line)
    except (TypeError, ValueError):
        return ""
    return "3.5+" if x >= 3.5 else f"{max(0.5, math.floor(x) + 0.5):.1f}"


def platt(p: float, cal: dict | None, line=None) -> float:
    """Calibrated P(over). cal = {"a", "b"} on logit(p_raw); when the fit is side-split it also has
    "b_under": lines the raw model leans UNDER on use that slope instead (no intercept, so 50% stays 50%).
    When the build found a per-line intercept improves walk-forward log loss, cal["line_a"] holds one
    intercept per line bucket, added on top."""
    if not cal:
        return p
    p = min(max(p, 1e-4), 1 - 1e-4)
    b = cal["b_under"] if "b_under" in cal and p < 0.5 else cal["b"]
    z = cal.get("a", 0.0) + b * math.log(p / (1 - p))
    if line is not None and cal.get("line_a"):
        z += cal["line_a"].get(line_bucket(line), 0.0)
    return 1 / (1 + math.exp(-z))


def novig(over_price, under_price) -> float | None:
    """No-vig P(over) from both American prices, or None if either is missing."""
    o, u = implied(over_price), implied(under_price)
    return o / (o + u) if o is not None and u is not None else None


def blend_w(cal: dict | None) -> float:
    """Weight on the model in the market blend: fitted by log loss (calibrate.fit_blend) when the build
    has one, else the fixed BLEND_W."""
    w = (cal or {}).get("w")
    return float(w) if w is not None else BLEND_W


def final_p_over(p_over_raw: float, cal: dict | None, over_price=None, under_price=None, w: float | None = None,
                 market_p=None, line=None) -> tuple:
    """(final P(over), calibrated model P(over), no-vig market P(over) or None). market_p is a no-vig
    P(over) from another book on the same line (e.g. DraftKings for a DFS leg), used when this line has no prices."""
    w = blend_w(cal) if w is None else w
    pm = platt(p_over_raw, cal, line)
    mk = novig(over_price, under_price)
    if mk is None and market_p is not None:
        mk = market_p
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
           market: str | None = None, proj: float | None = None, line: float | None = None, market_p=None) -> dict:
    """Pick the better side by EV. Prices are American odds (sportsbook) or None; multipliers are
    DFS per-side multipliers (1, 0.9, 0.8 ...). Returns side, p (final, that side), be, ev, tier, play,
    plus p_model / p_mkt (P(over) from the calibrated model and the no-vig market)."""
    p_over, p_model, p_mkt = final_p_over(p_over_raw, cal, over_price, under_price, market_p=market_p, line=line)
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
    # display / ranking only: the play decision and grading above use the uncapped probability
    best["capped"] = market == "saves" and best["p"] >= SAVES_CAP_AT
    best["p_show"] = SAVES_CAP_TO if best["capped"] else best["p"]
    return best


def side_break_even(price=None, mult=None, dfs: dict | None = None) -> float | None:
    if price not in (None, ""):
        return implied(price)
    if mult not in (None, ""):
        d = dfs or DFS_DEFAULT
        return dfs_break_even(float(mult), d["legs"], d["payout"])
    return None


def verdict(market: str, p_over: float, p_model_over: float, line: float, proj: float | None = None,
            mult_over=None, mult_under=None, over_price=None, under_price=None, matched: bool = True,
            confirmed: bool = True, dfs: dict | None = None, p_mkt_over=None) -> dict:
    """One explicit call for one line: TAKE MORE, TAKE LESS or PASS with a one-line reason.

    TAKE only if all hold for the side: it is offered at >= MIN_MULT on a DFS board (never a sportsbook's own
    price, PRICED_TAKES); the market (p_mkt_over: no-vig P(over) at this line) prices this player-line and its
    own probability for the side is >= MKT_MIN; blended p >= take_p(market) (saves: also an edge of
    SAVES_EDGE_UNDER saves past the line, and no overs); p beats the price's break-even; the player is
    MATCHED (saves: a confirmed starter); the model alone leans the same way; and no market-specific block
    (points unders on lines >= POINTS_UNDER_MAX). The side considered is the one with the higher blended p.
    Near miss: everything met except p, which is within NEAR_BAND of the bar.
    Returns side ("OVER" / "UNDER"), p, p_model, p_mkt_side (the market's probability for the side), be, mult / price,
    verdict, reason, tier, ev."""
    side = "OVER" if p_over >= 0.5 else "UNDER"
    p = p_over if side == "OVER" else 1 - p_over
    pm = p_model_over if side == "OVER" else 1 - p_model_over
    mult = mult_over if side == "OVER" else mult_under
    price = over_price if side == "OVER" else under_price
    be = side_break_even(price, mult, dfs)
    ev = (p * profit(price) - (1 - p)) if price not in (None, "") else (p / be - 1 if be else None)
    edge = None if proj is None else (proj - line if side == "OVER" else line - proj)
    pk = None if p_mkt_over in (None, "") or p_mkt_over != p_mkt_over else \
        (float(p_mkt_over) if side == "OVER" else 1 - float(p_mkt_over))
    out = {"side": side, "p": p, "p_model": pm, "p_mkt_side": pk, "be": be, "mult": None if mult in (None, "") else float(mult),
           "price": price, "ev": ev, "edge": edge, "verdict": "PASS", "tier": "", "reason": ""}
    need = take_p(market)
    pct = f"{100 * p:.0f}%"
    reason, near = None, False
    if not matched:
        reason = "unmatched player"
    elif market == "saves" and not confirmed:
        reason = "starter not confirmed"
    elif mult not in (None, "") and float(mult) == 0:
        reason = f"{'MORE' if side == 'OVER' else 'LESS'} not offered on this line"
    elif mult not in (None, "") and float(mult) < MIN_MULT - 1e-9:
        reason = f"pays {float(mult):g}x"
    elif price not in (None, "") and not PRICED_TAKES:
        reason = "sportsbook price: no edge over the book's own odds"
    elif market == "saves" and side == "OVER" and not SAVES_TAKE_OVERS:
        reason = "saves overs: no edge (they lost at every threshold)"
    elif market == "points" and side == "UNDER" and line >= POINTS_UNDER_MAX - 1e-9:
        reason = f"points {line:g} unders: the model is overconfident here"
    elif market == "saves" and (edge is None or edge < (SAVES_EDGE_OVER if side == "OVER" else SAVES_EDGE_UNDER) - 1e-9):
        need_e = SAVES_EDGE_OVER if side == "OVER" else SAVES_EDGE_UNDER
        reason = f"edge {edge:+.1f} < {need_e:g}" if edge is not None else "no projection"
    elif pk is None:
        reason = "no market price on this line (model-only picks have not won)"
    elif pk < MKT_MIN - 1e-9:
        reason = f"market only {100 * pk:.0f}% on this side"
    elif p < need - 1e-9:
        near = p >= need - NEAR_BAND - 1e-9
        reason = f"{pct} near miss" if near else f"{pct} < {100 * need:.0f}%"
    elif be is not None and p <= be:
        reason = f"{pct} doesn't beat break-even {100 * be:.1f}%"
    elif pm <= 0.5:
        reason = f"model alone {100 * pm:.0f}% disagrees (market-driven)"
    if reason is None:
        out.update(verdict=f"TAKE {'MORE' if side == 'OVER' else 'LESS'}", tier="Lock" if p >= lock_p(market) - 1e-9 else "Strong")
    else:
        out["reason"] = reason
        if near:
            out["tier"] = "Near miss"
    return out


def best_line(cands: list[dict]) -> int | None:
    """Index of the single line to TAKE among one player's lines in one market (main + alts): the highest
    EV among TAKE verdicts at >= 1x. None when no line is a TAKE."""
    best, bev = None, None
    for i, c in enumerate(cands):
        if not str(c.get("verdict", "")).startswith("TAKE"):
            continue
        ev = c.get("ev") if c.get("ev") is not None else -9
        if best is None or ev > bev:
            best, bev = i, ev
    return best


def night_alarm(decisions: list[dict]) -> dict:
    """One market, one night: the over/under split of the plays, and whether more than ALARM_SHARE of
    them are on one side. Display only (the red banner and the logged split); it never removes a play."""
    n = sum(1 for d in decisions if d.get("play"))
    over = sum(1 for d in decisions if d.get("play") and d["side"] == "OVER")
    share = max(over, n - over) / n if n else 0.0
    return {"plays": n, "over": over, "under": n - over, "share": round(share, 4),
            "side": ("OVER" if over * 2 > n else "UNDER" if over * 2 < n else "even") if n else None,
            "alarm": bool(n >= ALARM_MIN_PLAYS and share > ALARM_SHARE)}
