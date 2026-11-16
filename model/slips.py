"""Slips: how likely a pick'em entry's legs are to hit TOGETHER, what the entry pays, and what it is worth.

The board grades one leg at a time; the apps pay on the whole entry. This module answers, for a set of legs on one
app: the joint chance (same-game legs move together), the payout (the level's multiple x each leg's multiplier x the
app's own same-game cut, capped), the expected return, and the same again with every leg's chance trimmed (the stress
test). best_slips() searches the board's legs for the entries worth the most after that trim.

Joint chance: a Gaussian copula. A leg with chance p becomes the event Z < ninv(p) on a standard normal. Legs in
different games are independent. Two legs in the same game are tied by a correlation that depends on the kind of
pair (RHO: measured from box scores, see measure_rho) and flips sign when exactly one of them is a LESS. The joint
chance of a same-game group is a multivariate normal probability (mvn: exact conditioning + Gauss-Legendre, no
sampling, so Python and the page agree to the last digits).

Pushes: on a whole-number line a result exactly on the line is a push; the apps void that leg and pay the entry at
the next level down (a 2-pick left with one leg is refunded). Each leg carries its push chance; a leg's `p` is its
chance given no push (as everywhere on the board).

This is a calculator for display. It never places, submits or automates anything.
template.html mirrors this file (bvn, mvn, slipBook, bestSlips): tests/test_slips.py runs the page's own code against
this module, so a change to one without the other fails the build.
"""
from __future__ import annotations

import itertools
import math

# ---------- the normal distribution (the page mirrors these exactly) ----------


def erfc(x: float) -> float:
    """Numerical Recipes erfc (fractional error < 1.2e-7): the same approximation the page uses."""
    z = abs(x)
    t = 1 / (1 + 0.5 * z)
    r = t * math.exp(-z * z - 1.26551223 + t * (1.00002368 + t * (0.37409196 + t * (0.09678418 + t * (-0.18628806 + t * (
        0.27886807 + t * (-1.13520398 + t * (1.48851587 + t * (-0.82215223 + t * 0.17087277)))))))))
    return r if x >= 0 else 2 - r


def ncdf(x: float) -> float:
    return 0.5 * erfc(-x / math.sqrt(2))


_A = (-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02, 1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00)
_B = (-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02, 6.680131188771972e+01, -1.328068155288572e+01)
_C = (-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00, -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00)
_D = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00, 3.754408661907416e+00)


def ninv(p: float) -> float:
    """Inverse normal CDF (Acklam's rational approximation, relative error < 1.2e-9)."""
    p = min(max(p, 1e-12), 1 - 1e-12)
    if p < 0.02425 or p > 1 - 0.02425:
        q = math.sqrt(-2 * math.log(p if p < 0.5 else 1 - p))
        x = (((((_C[0] * q + _C[1]) * q + _C[2]) * q + _C[3]) * q + _C[4]) * q + _C[5]) / ((((_D[0] * q + _D[1]) * q + _D[2]) * q + _D[3]) * q + 1)
        return x if p < 0.5 else -x
    q = p - 0.5
    r = q * q
    return (((((_A[0] * r + _A[1]) * r + _A[2]) * r + _A[3]) * r + _A[4]) * r + _A[5]) * q / (((((_B[0] * r + _B[1]) * r + _B[2]) * r + _B[3]) * r + _B[4]) * r + 1)


_GL: dict = {}


def gauleg(n: int):
    """Gauss-Legendre nodes and weights on [-1, 1] (Newton on the Legendre polynomial)."""
    if n not in _GL:
        xs, ws = [], []
        for i in range(1, n + 1):
            x = math.cos(math.pi * (i - 0.25) / (n + 0.5))
            dp = 1.0
            for _ in range(100):
                p1, p2 = 1.0, 0.0
                for j in range(1, n + 1):
                    p1, p2 = ((2 * j - 1) * x * p1 - (j - 1) * p2) / j, p1
                dp = n * (x * p1 - p2) / (x * x - 1)
                dx = p1 / dp
                x -= dx
                if abs(dx) < 1e-15:
                    break
            xs.append(x)
            ws.append(2 / ((1 - x * x) * dp * dp))
        _GL[n] = (xs, ws)
    return _GL[n]


def quad(f, a: float, b: float, n: int) -> float:
    xs, ws = gauleg(n)
    h, m = 0.5 * (b - a), 0.5 * (a + b)
    return h * sum(w * f(m + h * x) for x, w in zip(xs, ws))


def bvn(h: float, k: float, r: float) -> float:
    """P(X < h, Y < k) for a standard bivariate normal with correlation r: the independent product plus the integral
    of the density over the correlation (Plackett), with r = sin(t) so the integrand stays smooth."""
    pq = ncdf(h) * ncdf(k)
    if abs(r) < 1e-12:
        return pq
    r = max(-0.999, min(0.999, r))
    f = lambda t: math.exp(-(h * h + k * k - 2 * h * k * math.sin(t)) / (2 * math.cos(t) ** 2))
    return min(1.0, max(0.0, pq + quad(f, 0.0, math.asin(r), 20) / (2 * math.pi)))


MVN_NODES = {3: 16, 4: 12}      # Gauss-Legendre nodes for the outer integral, by dimension (5+: 8)


def mvn(z: list, R: list) -> float:
    """P(X_i < z_i for every i) for standard normals with correlation matrix R. One and two dimensions are closed
    forms; beyond that the first variable is integrated out (on the u = Phi(x) scale, so the range is finite) and the
    rest is the same problem one dimension smaller, given x."""
    n = len(z)
    if n == 0:
        return 1.0
    if n == 1:
        return ncdf(z[0])
    if n == 2:
        return bvn(z[0], z[1], R[0][1])
    p0 = ncdf(z[0])
    if p0 <= 0:
        return 0.0
    s = [math.sqrt(max(1e-9, 1 - R[i][0] ** 2)) for i in range(1, n)]
    R2 = [[1.0 if i == j else max(-0.999, min(0.999, (R[i][j] - R[i][0] * R[j][0]) / (s[i - 1] * s[j - 1])))
           for j in range(1, n)] for i in range(1, n)]

    def inner(u):
        x = ninv(u)
        return mvn([(z[i] - R[i][0] * x) / s[i - 1] for i in range(1, n)], R2)
    return min(1.0, max(0.0, quad(inner, 0.0, p0, MVN_NODES.get(n, 8))))


# ---------- how two legs in one game move together ----------
# RHO[pair type] = the correlation of the two STATS (both running high together). These starting values are the
# average of three full seasons of box scores (2023-24 to 2025-26, about 1,400 games each, measured with measure_rho);
# the seasons agree closely (shooter vs opposing goalie: 0.222, 0.229, 0.226; teammates' points: 0.222, 0.249, 0.212).
# Every build measures the current season and moves toward it as its games accumulate (blend_rho); the build ships
# the table in use in the payload. The sign of a pair of LEGS flips when exactly one of them is a LESS.
# Pair types: tm = teammates, opp = opponents, own_g / opp_g = the skater's own / the opposing goalie's saves.
RHO = {"sog_opp_g": 0.23, "sog_own_g": -0.04, "tm_sog": 0.03, "opp_sog": -0.01, "tm_pts": 0.23, "opp_pts": -0.01,
       "tm_sog_pts": 0.02, "opp_sog_pts": 0.02, "pts_opp_g": -0.06, "pts_own_g": 0.03, "g_g": -0.10}
RHO_TOP = {"sog_opp_g": 0.32, "tm_pts": 0.34}       # the same pair when the skater(s) are high-volume (TOP_SOG / TOP_PTS)
TOP_SOG, TOP_PTS = 2.5, 0.8                         # projection at or above this = high volume

# Pick6's own cut on same-game pairs it treats as correlated (its "correlationFactor"), keyed by pair type and whether
# the two legs point the SAME way (More/More, Less/Less) or OPPOSITE ways. These are the values the owner's research
# measured in the app on 2026-11-14; the app's entry screen is the authority, and anything not listed is 1.0.
P6_FACTOR = {("sog_opp_g", "same"): 0.82, ("tm_sog", "same"): 0.95, ("tm_sog_pts", "same"): 0.88, ("tm_pts", "same"): 0.90,
             ("pts_own_g", "same"): 0.94, ("sog_own_g", "opp"): 0.97}

# What an entry pays, per app and play type: {picks: {"all": x, "miss1": y, "miss2": z, "cap": c}}. Pick6's table is
# read from its page each build (pick6.payout_table) and replaces this default; PrizePicks' is its published table
# (Sept 2026: Power 3 / 6 / 10 / 20 / 37.5; Flex pays part on one or two misses). Both can differ by state and by
# entry: the entry screen is the authority.
PAYOUTS = {
    "Pick6": {"2": {"all": 3.0, "cap": 20.0}, "3": {"all": 6.0, "cap": 60.0}, "4": {"all": 10.0, "cap": 100.0},
              "5": {"all": 12.0, "cap": 150.0, "miss1": 1.0, "cap1": 6.0}, "6": {"all": 25.0, "cap": 300.0, "miss1": 1.5, "cap1": 10.0}},
    "PrizePicks Power": {"2": {"all": 3.0}, "3": {"all": 6.0}, "4": {"all": 10.0}, "5": {"all": 20.0}, "6": {"all": 37.5}},
    "PrizePicks Flex": {"3": {"all": 3.0, "miss1": 1.0}, "4": {"all": 6.0, "miss1": 1.5},
                        "5": {"all": 10.0, "miss1": 2.0, "miss2": 0.4}, "6": {"all": 25.0, "miss1": 2.0, "miss2": 0.4}},
}
PLAYS = {"Pick6": ("Pick6",), "PrizePicks": ("PrizePicks Power", "PrizePicks Flex")}     # app -> its play types
FALLBACK = {"PrizePicks Flex": "PrizePicks Power"}     # a play type with no level for what is left after a push
STRESS = 0.03               # the stress test: every leg's chance trimmed by this
MAX_LEGS = 6
SEARCH_TOP = {2: 15, 3: 15, 4: 15, 5: 12, 6: 12}        # legs considered (best chance first), by entry size
MIN_TEAMS = 2               # both apps: an entry needs players from at least two teams
MAX_PROMO = 1               # Pick6: at most one promo pick (Stat Slice / Power Up / Gimme) per entry
FILLERS = 5                 # partners added when an app cannot otherwise form an entry (props_board.slip_legs)
FILL_MIN_VALUE = 0.50       # ... each worth at least this (chance x multiplier; a 1x leg breaks even at 0.577)


def config() -> dict:
    """Everything the page needs to mirror this module."""
    return {"rho": RHO, "rho_top": RHO_TOP, "top_sog": TOP_SOG, "top_pts": TOP_PTS,
            "p6_factor": [[k[0], k[1], v] for k, v in P6_FACTOR.items()], "payouts": PAYOUTS, "plays": {k: list(v) for k, v in PLAYS.items()},
            "fallback": FALLBACK, "stress": STRESS, "max_legs": MAX_LEGS, "search_top": {str(k): v for k, v in SEARCH_TOP.items()},
            "min_teams": MIN_TEAMS, "max_promo": MAX_PROMO, "fillers": FILLERS, "fill_min": FILL_MIN_VALUE}


def pair_type(a: dict, b: dict) -> str | None:
    """The kind of same-game pair two legs are, or None (different games: independent)."""
    if a.get("game") is None or a["game"] != b.get("game"):
        return None
    same = a.get("team") == b.get("team")
    ms = tuple(sorted((a["market"], b["market"])))
    if ms == ("sog", "sog"):
        return "tm_sog" if same else "opp_sog"
    if ms == ("points", "points"):
        return "tm_pts" if same else "opp_pts"
    if ms == ("points", "sog"):
        return "tm_sog_pts" if same else "opp_sog_pts"
    if ms == ("saves", "sog"):
        return "sog_own_g" if same else "sog_opp_g"
    if ms == ("points", "saves"):
        return "pts_own_g" if same else "pts_opp_g"
    if ms == ("saves", "saves"):
        return "g_g"
    return None


def _top(leg: dict) -> bool:
    proj = leg.get("proj")
    if proj is None:
        return False
    return (leg["market"] == "sog" and proj >= TOP_SOG) or (leg["market"] == "points" and proj >= TOP_PTS)


def leg_rho(a: dict, b: dict, rho: dict | None = None, rho_top: dict | None = None) -> float:
    """The correlation between two LEGS (the events "this leg hits"): the pair type's stat correlation, the
    high-volume value when every skater in the pair is high volume, sign flipped when the legs point opposite ways."""
    t = pair_type(a, b)
    if t is None:
        return 0.0
    rho, rho_top = RHO if rho is None else rho, RHO_TOP if rho_top is None else rho_top
    r = rho.get(t, 0.0)
    if t in rho_top and all(_top(x) for x in (a, b) if x["market"] != "saves"):
        r = rho_top[t]
    return r if a["side"] == b["side"] else -r


def pair_factor(a: dict, b: dict, factor: dict | None = None) -> float:
    """Pick6's cut for one pair of legs (1.0 when it applies none)."""
    t = pair_type(a, b)
    if t is None:
        return 1.0
    f = P6_FACTOR if factor is None else factor
    return f.get((t, "same" if a["side"] == b["side"] else "opp"), 1.0)


def _joint_R(ps: list, R: list) -> float:
    """The chance every event happens, given each one's chance and the matrix of correlations between them.
    Independent groups multiply; a group that is tied together is one multivariate normal probability."""
    n = len(ps)
    seen, out = set(), 1.0
    for i in range(n):
        if i in seen:
            continue
        grp, todo = [], [i]
        while todo:                       # the legs tied to leg i, directly or through another leg
            k = todo.pop()
            if k in seen:
                continue
            seen.add(k)
            grp.append(k)
            todo += [j for j in range(n) if j not in seen and abs(R[k][j]) > 1e-12]
        grp.sort()
        if len(grp) == 1:
            out *= ps[grp[0]]
        else:
            out *= mvn([ninv(ps[g]) for g in grp], [[R[a][b] for b in grp] for a in grp])
    return out


def joint(legs: list, ps: list | None = None, rho: dict | None = None, rho_top: dict | None = None) -> float:
    """The chance every leg hits (given none pushes)."""
    ps = [l["p"] for l in legs] if ps is None else ps
    n = len(legs)
    return _joint_R(ps, [[1.0 if i == j else leg_rho(legs[i], legs[j], rho, rho_top) for j in range(n)] for i in range(n)])


def _clip(p: float) -> float:
    return min(0.999, max(0.001, p))


class Book:
    """One app's legs with everything about pairs of them worked out once (correlations, the app's cuts), and every
    joint chance remembered: the search values thousands of entries that share most of their sub-groups."""

    def __init__(self, legs: list, app: str, cfg: dict | None = None):
        cfg = cfg or {}
        self.legs, self.app, self.cfg = legs, app, cfg
        n = len(legs)
        self.R = [[1.0 if i == j else leg_rho(legs[i], legs[j], cfg.get("rho"), cfg.get("rho_top")) for j in range(n)] for i in range(n)]
        self.F = [[pair_factor(legs[i], legs[j], cfg.get("factor")) if app == "Pick6" and i != j else 1.0 for j in range(n)] for i in range(n)]
        self.tied = [any(abs(self.R[i][j]) > 1e-12 for j in range(n) if j != i) for i in range(n)]
        self.push = [min(0.95, max(0.0, float(l.get("push") or 0.0))) for l in legs]
        self.mult = [float(l.get("mult") or 1.0) for l in legs]
        self.memo = {}

    def J(self, idx: tuple, stress: float = 0.0) -> float:
        """The chance every leg in idx hits (given none of them pushes), each trimmed by `stress`."""
        key = (stress, idx)
        v = self.memo.get(key)
        if v is None:
            ps = [_clip(self.legs[i]["p"] - stress) for i in idx]
            if not any(self.tied[i] for i in idx):
                v = 1.0
                for p in ps:
                    v *= p
            else:
                v = _joint_R(ps, [[self.R[a][b] for b in idx] for a in idx])
            self.memo[key] = v
        return v

    def mults(self, idx: tuple):
        """(the legs' multipliers multiplied together, the app's own cut on its correlated pairs)."""
        m = f = 1.0
        for i in idx:
            m *= self.mult[i]
        for a, b in itertools.combinations(idx, 2):
            f *= self.F[a][b]
        return m, f

    def settle(self, idx: tuple, table: dict, fallback: dict | None, stress: float):
        """(expected return, chance of a cash) once the legs in idx are the ones left standing (none pushed)."""
        m = len(idx)
        if m < 2:
            return 1.0, 0.0               # one leg left: the stake comes back
        lvl = table.get(str(m)) or (fallback or {}).get(str(m))
        if lvl is None:
            return 1.0, 0.0               # no such level on this play type: treated as a refund
        mm, ff = self.mults(idx)
        pay = lvl["all"] * mm * ff
        if lvl.get("cap"):
            pay = min(pay, lvl["cap"])
        p_all = self.J(idx, stress)
        ret, cash = p_all * pay, p_all
        if lvl.get("miss1"):
            less1 = {i: self.J(tuple(x for x in idx if x != i), stress) for i in idx}
            p1 = sum(less1.values()) - m * p_all
            pay1 = lvl["miss1"] * mm * ff
            if lvl.get("cap1"):
                pay1 = min(pay1, lvl["cap1"])
            ret += p1 * pay1
            cash += p1 if pay1 >= 1 else 0.0
            if lvl.get("miss2"):
                p2 = 0.0
                for i, j in itertools.combinations(idx, 2):
                    p2 += self.J(tuple(x for x in idx if x != i and x != j), stress) - less1[i] - less1[j] + p_all
                ret += p2 * lvl["miss2"]
                cash += p2 if lvl["miss2"] >= 1 else 0.0
        return ret, cash

    def value(self, idx: tuple, table: dict, fallback: dict | None = None, stress: float = 0.0) -> dict:
        """What the entry made of the legs in idx is worth on one play type.
          ret      expected return per 1 staked (1.0 = break even), pushes included
          p_all    chance every leg hits and none pushes
          p_cash   chance the entry pays out at least the stake as winnings (a refund is not a cash)
          pays     what the full entry pays when every leg hits: base x leg multipliers x the app's cut, capped
          factor   the app's same-game cut (Pick6 only)"""
        lvl = table.get(str(len(idx)))
        mm, ff = self.mults(idx)
        pays = None
        if lvl is not None:
            pays = lvl["all"] * mm * ff
            if lvl.get("cap"):
                pays = min(pays, lvl["cap"])
        can = [i for i in idx if self.push[i] > 0]
        ret = cash = 0.0
        for k in range(len(can) + 1):
            for T in itertools.combinations(can, k):
                w = 1.0
                for i in can:
                    w *= self.push[i] if i in T else 1 - self.push[i]
                r_, c_ = self.settle(tuple(i for i in idx if i not in T), table, fallback, stress)
                ret += w * r_
                cash += w * c_
        no_push = 1.0
        for i in can:
            no_push *= 1 - self.push[i]
        return {"ret": ret, "p_all": no_push * self.J(idx, stress), "p_cash": cash, "pays": pays, "factor": ff, "mult": mm}

    def slip(self, idx: tuple, play: str, tables: dict) -> dict | None:
        """One entry on one play type, valued at the stated chances and at the stress test. None when the play type
        has no level for this many legs."""
        table = tables.get(play) or {}
        if str(len(idx)) not in table:
            return None
        fb = tables.get(FALLBACK.get(play, "")) if play in FALLBACK else None
        v = self.value(idx, table, fb, 0.0)
        st = self.value(idx, table, fb, STRESS)
        ind = 1.0
        for i in idx:
            ind *= self.legs[i]["p"]
        return {"app": self.app, "play": play, "n": len(idx), "legs": [self.legs[i]["id"] for i in idx], "pays": v["pays"],
                "factor": v["factor"], "p_all": v["p_all"], "p_cash": v["p_cash"], "joint": self.J(idx), "indep": ind,
                "ev": v["ret"] - 1, "ev_stress": st["ret"] - 1,
                "same_game": any(self.legs[a].get("game") == self.legs[b].get("game") for a, b in itertools.combinations(idx, 2)),
                "promo": any(self.legs[i].get("promo") for i in idx), "pushes": sum(1 for i in idx if self.push[i] > 0)}


def value(legs: list, table: dict, app: str, stress: float = 0.0, cfg: dict | None = None) -> dict:
    """What one entry is worth on one play type (see Book.value). cfg: rho, rho_top, factor, fallback (a table)."""
    return Book(legs, app, cfg).value(tuple(range(len(legs))), table, (cfg or {}).get("fallback"), stress)


def allowed(legs: list) -> str | None:
    """Why this set of legs cannot be one entry, or None: one pick per player, players from at least MIN_TEAMS teams,
    one app, at most MAX_PROMO promo picks."""
    if len({l.get("player_id") or l["name"] for l in legs}) < len(legs):
        return "one pick per player"
    if len({l.get("team") for l in legs}) < MIN_TEAMS:
        return f"needs players from {MIN_TEAMS} teams"
    if sum(1 for l in legs if l.get("promo")) > MAX_PROMO:
        return "one promo pick per entry"
    return None


def slip(legs: list, app: str, play: str, tables: dict | None = None, cfg: dict | None = None) -> dict | None:
    """One entry on one play type (see Book.slip)."""
    return Book(legs, app, cfg).slip(tuple(range(len(legs))), play, tables or PAYOUTS)


def slip_key(s: dict):
    """Best first: the higher stress-test value, then the higher stated value, then fewer legs, then a stable order."""
    return (-round(s["ev_stress"], 9), -round(s["ev"], 9), s["n"], s["play"], ",".join(s["legs"]))


def best_slips(legs: list, app: str, tables: dict | None = None, cfg: dict | None = None, sizes=(2, 3, 4, 5, 6), keep: int = 3) -> dict:
    """Search one app's legs for the best entries. Every combination of 2 to 6 legs among the best SEARCH_TOP by
    chance is valued on each of the app's play types; a combination that breaks a lineup rule is skipped.
    Returns {"top": the best `keep` (one play type per set of legs), "by_size": {n: the best of that size},
    "searched": how many entries were valued, "n_legs": how many legs were available}."""
    tables = tables or PAYOUTS
    pool = sorted(legs, key=lambda l: (-l["p"], l["id"]))[:max(SEARCH_TOP.values())]
    book = Book(pool, app, cfg)
    best, by_size, n_seen = [], {}, 0
    for n in sizes:
        for idx in itertools.combinations(range(min(len(pool), SEARCH_TOP.get(n, 12))), n):
            if allowed([pool[i] for i in idx]):
                continue
            top = None
            for play in PLAYS.get(app, (app,)):
                s = book.slip(idx, play, tables)
                if s is None:
                    continue
                n_seen += 1
                if top is None or slip_key(s) < slip_key(top):
                    top = s
            if top is None:
                continue
            best.append(top)
            if str(n) not in by_size or slip_key(top) < slip_key(by_size[str(n)]):
                by_size[str(n)] = top
        best.sort(key=slip_key)
        del best[max(keep, 1):]
    return {"top": best[:keep], "by_size": by_size, "searched": n_seen, "n_legs": len(legs)}


# ---------- measuring how legs move together (every build, from this season's box scores) ----------
RHO_PRIOR_GAMES = 1400      # this season's measurement counts as much as the starting value after about a season of games
MIN_TOI, MIN_GOALIE_TOI = 8.0, 55.0
AVG_SOG, AVG_PTS = 1.5, 0.5  # the skaters a line is likely to exist for


def implied_rho(p_a: float, p_b: float, p_ab: float) -> float | None:
    """The correlation at which two events with chances p_a and p_b happen together p_ab of the time."""
    if not (0 < p_a < 1 and 0 < p_b < 1) or not (0 <= p_ab <= min(p_a, p_b)):
        return None
    h, k = ninv(p_a), ninv(p_b)
    lo, hi = -0.99, 0.99
    for _ in range(50):
        mid = 0.5 * (lo + hi)
        if bvn(h, k, mid) < p_ab:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def measure_rho(skaters, starts, season=None) -> dict:
    """{pair type: {"rho", "n" pairs, "games"}} from one season of box scores, the way the owner's research did it
    (and an independent re-run confirmed, 2026-11-15): each stat less the player's own season mean; a "hit" is a game above
    his mean; the correlation is the one a Gaussian copula needs to reproduce how often two players hit together.
    Skaters with MIN_TOI+ minutes, goalies with MIN_GOALIE_TOI+. Shots pairs use skaters averaging AVG_SOG+ shots,
    points pairs AVG_PTS+ points (the players lines exist for); the *_top rows use TOP_SOG+ / TOP_PTS+."""
    import numpy as np
    import pandas as pd
    s = skaters if season is None else skaters[skaters.season == season]
    g = starts if season is None else starts[starts.season == season]
    s = s[s.toi_min >= MIN_TOI][["game_id", "team_abbrev", "player_id", "shots_on_goal", "points"]].copy()
    g = g[g.toi_min >= MIN_GOALIE_TOI][["game_id", "team_abbrev", "player_id", "saves"]].copy()
    if not len(s) or not len(g):
        return {}
    for col in ("shots_on_goal", "points"):
        m = s.groupby("player_id")[col].transform("mean")
        s[col + "_avg"], s[col + "_hit"] = m, (s[col] > m).astype(float)
    g["hit"] = (g.saves > g.groupby("player_id").saves.transform("mean")).astype(float)
    g = g.rename(columns={"team_abbrev": "g_team"})[["game_id", "g_team", "hit"]]

    def rho_of(x, ca, cb):
        n = len(x)
        if n < 50:
            return None
        a, b = x[ca], x[cb]
        r = implied_rho(float(a.mean()), float(b.mean()), float((a * b).mean()))
        # pairs in one game share that game's pace, so the games behind a number say how firm it is, not the pairs
        return None if r is None else {"rho": round(r, 4), "n": int(n), "games": int(x.game_id.nunique())}

    out = {}
    sog_ok, pts_ok = s[s.shots_on_goal_avg >= AVG_SOG], s[s.points_avg >= AVG_PTS]
    # skater vs goalie (every skater: a goalie leg pairs with whoever is on the slip)
    sg = s.merge(g, on="game_id")
    own, opp = sg[sg.team_abbrev == sg.g_team], sg[sg.team_abbrev != sg.g_team]
    out["sog_opp_g"] = rho_of(opp, "shots_on_goal_hit", "hit")
    out["sog_opp_g_top"] = rho_of(opp[opp.shots_on_goal_avg >= TOP_SOG], "shots_on_goal_hit", "hit")
    out["sog_own_g"] = rho_of(own, "shots_on_goal_hit", "hit")
    po, pw = opp[opp.points_avg >= AVG_PTS], own[own.points_avg >= AVG_PTS]
    out["pts_opp_g"], out["pts_own_g"] = rho_of(po, "points_hit", "hit"), rho_of(pw, "points_hit", "hit")
    # skater vs skater
    def pairs(a, b, same_team):
        x = a.merge(b, on="game_id", suffixes=("", "_b"))
        x = x[(x.team_abbrev == x.team_abbrev_b) if same_team else (x.team_abbrev != x.team_abbrev_b)]
        return x[x.player_id != x.player_id_b]
    for key, a, b, ca, cb in (("tm_sog", sog_ok, sog_ok, "shots_on_goal_hit", "shots_on_goal_hit_b"),
                              ("tm_pts", pts_ok, pts_ok, "points_hit", "points_hit_b"),
                              ("tm_sog_pts", sog_ok, pts_ok, "shots_on_goal_hit", "points_hit_b")):
        x = pairs(a, b, True)
        if key != "tm_sog_pts":
            x = x[x.player_id < x.player_id_b]              # each pair once
        out[key] = rho_of(x, ca, cb)
        if key == "tm_pts":
            out["tm_pts_top"] = rho_of(x[(x.points_avg >= TOP_PTS) & (x.points_avg_b >= TOP_PTS)], ca, cb)
    for key, a, b, ca, cb in (("opp_sog", sog_ok, sog_ok, "shots_on_goal_hit", "shots_on_goal_hit_b"),
                              ("opp_pts", pts_ok, pts_ok, "points_hit", "points_hit_b"),
                              ("opp_sog_pts", sog_ok, pts_ok, "shots_on_goal_hit", "points_hit_b")):
        x = pairs(a, b, False)
        if key != "opp_sog_pts":
            x = x[x.player_id < x.player_id_b]
        out[key] = rho_of(x, ca, cb)
    gg = g.merge(g, on="game_id", suffixes=("", "_b"))
    gg = gg[gg.g_team < gg.g_team_b]
    out["g_g"] = rho_of(gg, "hit", "hit_b")
    return {k: v for k, v in out.items() if v}


def blend_rho(measured: dict | None) -> tuple[dict, dict]:
    """(rho, rho_top) in use: each starting value pulled toward this season's measurement by how many GAMES it rests
    on (games / (games + RHO_PRIOR_GAMES)). Six weeks of a season moves a number about a fifth of the way; the
    starting values are three seasons deep and the seasons agree, so an early-season swing is mostly noise."""
    rho, top = dict(RHO), dict(RHO_TOP)
    for k, v in (measured or {}).items():
        g = v.get("games") or 0
        w = g / (g + RHO_PRIOR_GAMES)
        if k.endswith("_top") and k[:-4] in top:
            top[k[:-4]] = round(w * v["rho"] + (1 - w) * top[k[:-4]], 4)
        elif k in rho:
            rho[k] = round(w * v["rho"] + (1 - w) * rho[k], 4)
    return rho, top


def settings(measured: dict | None = None, pick6_payouts: dict | None = None) -> dict:
    """What the build ships for the page (and uses itself): config() with this season's correlations blended in
    and Pick6's own payout table when its page gave one."""
    out = config()
    out["rho"], out["rho_top"] = blend_rho(measured)
    out["measured"] = measured or {}
    ok = pick6_payouts and all(str(n) in pick6_payouts and pick6_payouts[str(n)].get("all") for n in (2, 3))
    if ok:
        out["payouts"] = {**out["payouts"], "Pick6": pick6_payouts}
    out["payouts_from"] = {"Pick6": "Pick6's page, this build" if ok else "default table (its page gave none this build)",
                           "PrizePicks": "its published table (Sept 2026)"}
    return out


def run_cfg(st: dict | None) -> tuple[dict, dict]:
    """(cfg, tables) for Book / best_slips from a settings() dict."""
    st = st or config()
    return ({"rho": st.get("rho"), "rho_top": st.get("rho_top"), "factor": {(a, b): v for a, b, v in st.get("p6_factor") or []}},
            st.get("payouts") or PAYOUTS)
