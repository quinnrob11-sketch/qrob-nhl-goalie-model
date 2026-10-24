"""Saves projection as a distribution: shots against x save %, with game script.

Shots the starter faces:  N ~ NegBin(mean mu = exp_SA x time-in-net share, size K)
Saves given shots:         S | N ~ Binomial(N, sv)

    E[S]   = mu x sv
    Var[S] = sv^2 (mu + mu^2 / K) + mu sv (1 - sv)

P(saves > line) uses a normal with that mean and variance (continuity-corrected by the half-point
line). Unlike the old fixed spread (sd 6.9 for everyone) the spread grows with the workload, so a
heavy underdog facing 34 shots gets ~sd 8 and a favourite facing 24 gets ~sd 5.6. SD_FLOOR is the
minimum spread for anyone. Fitted on 2024-25 (K = 30); it beats the fixed spread on 2025-26 and
2026-27 log-likelihood. The exact NegBin x Binomial sum fit worse than this normal form because
pulled goalies and game-to-game save% swings fatten the tails.

Game script: exp_SA x exp(-GS x logit(p_win)), p_win = the goalie's team win probability (no-vig
DraftKings moneyline when posted, otherwise the game-winner model). Heavier underdogs face more
shots. GS is refit walk-forward (fit_sa.py) and the multiplier is capped at 1 +/- GS_CAP (12%).
"""
from __future__ import annotations

import math

# the fitted values in model/output/saves_dist.json (a test keeps them equal)
DEFAULTS = {"nb_k": 30.0, "gs": 0.025, "gs_cap": 0.12, "sd_floor": 5.5}


def load(path: str) -> dict:
    """Fitted distribution settings. A missing file is an error, never a silent fall back."""
    import json
    import os
    if not os.path.exists(path):
        raise FileNotFoundError(f"saves distribution file missing: {path} (refusing to fall back to defaults)")
    return json.load(open(path))


def game_script(exp_sa: float, p_win: float | None, gs: float, cap: float = DEFAULTS["gs_cap"]) -> float:
    """exp_SA x exp(-gs x logit(p_win)), the multiplier capped to 1 +/- cap."""
    if p_win is None or not 0 < p_win < 1 or not gs:
        return exp_sa
    m = math.exp(-gs * math.log(p_win / (1 - p_win)))
    return exp_sa * min(max(m, 1 - cap), 1 + cap)


def spread(mu: float, sv: float, k: float, floor: float) -> float:
    return max(math.sqrt(sv * sv * (mu + mu * mu / k) + mu * sv * (1 - sv)), floor)


def project(exp_sa: float, share: float, sv: float, p_win: float | None, prm: dict) -> dict:
    """Projected saves, its spread, and the shots behind it."""
    k, gs, cap, floor = (prm.get(x, DEFAULTS[x]) for x in ("nb_k", "gs", "gs_cap", "sd_floor"))
    sa = game_script(exp_sa, p_win, gs, cap)
    mu = sa * share
    return {"exp_sa": sa, "mu": mu, "proj": mu * sv, "sd": spread(mu, sv, k, floor)}


def p_over(proj: float, sd: float, line: float) -> float:
    """P(saves > line). Whole-number lines: P(over | no push)."""
    cdf = lambda x: 0.5 * math.erfc(-(x - proj) / sd / math.sqrt(2))
    if line != math.floor(line):
        return 1 - cdf(line)
    over, under = 1 - cdf(line + 0.5), cdf(line - 0.5)
    return over / (over + under) if over + under > 0 else 0.5


def devig(ml_a, ml_b):
    """Two American moneylines -> no-vig win probabilities (a, b)."""
    def imp(o):
        o = float(o)
        return -o / (-o + 100) if o < 0 else 100 / (o + 100)
    a, b = imp(ml_a), imp(ml_b)
    return a / (a + b), b / (a + b)
