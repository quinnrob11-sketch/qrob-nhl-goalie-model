"""Walk-forward saves projection engine.

Projection for a starting goalie G on team T facing opponent O:

    exp_SA   = LG * (T_def / LG)^a * (O_off / LG)^b * home * playoff * b2b
    proj_sv  = exp_SA * share(G) * sv%(G)

    LG     league shots-on-goal per team-game (recency weighted)
    T_def  shots on goal T allows per game (recency weighted, shrunk to LG)
    O_off  shots on goal O generates per game (recency weighted, shrunk to LG)
    a, b   how much the defence vs the opponent's offence drives the count
           (the old sheet used a fixed 60/40 blend; here it's fitted)
    share  fraction of the game G is expected to stay in net (pull risk)
    sv%    G's save% shrunk toward league average

Every game is projected using ONLY games played on earlier dates, then the
state is updated with that date's results, so the backtest has no lookahead.
"""
from __future__ import annotations

import math
from collections import defaultdict, deque
from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd

LEAGUE_SV = 0.900


@dataclass
class Params:
    half_life: float = 20.0     # games; recency weighting of team shot rates
    k_team: float = 10.0        # prior strength (games at league average)
    carry: float = 0.35         # share of last season's evidence kept at a new season
    a: float = 0.85             # weight of own team's shots-against
    b: float = 0.65             # weight of opponent's shots-for
    k_sv: float = 1500.0        # save% prior strength, in shots
    sv_half_life: float = 60.0  # starts; recency weighting of save%
    k_share: float = 15.0       # prior strength for time-in-net share, in starts
    home: float = 1.0           # multiplier on exp_SA when the goalie is home (fitted)
    playoff: float = 1.0        # multiplier in playoffs (fitted)
    b2b: float = 1.0            # multiplier when goalie's team played yesterday (fitted)

    def to_dict(self):
        return asdict(self)


class Decayed:
    """Exponentially decayed running sum of values and weights."""
    __slots__ = ("s", "w")

    def __init__(self):
        self.s = 0.0
        self.w = 0.0

    def add(self, x, decay, weight=1.0):
        self.s = self.s * decay + x
        self.w = self.w * decay + weight

    def scale(self, c):
        self.s *= c
        self.w *= c


class State:
    def __init__(self, p: Params):
        self.p = p
        self.dec = 0.5 ** (1.0 / p.half_life)
        self.sv_dec = 0.5 ** (1.0 / p.sv_half_life)
        self.off = defaultdict(Decayed)    # team -> SOG for
        self.dfn = defaultdict(Decayed)    # team -> SOG against
        self.gf = defaultdict(Decayed)     # team -> goals for (game-winner model)
        self.ga = defaultdict(Decayed)     # team -> goals against
        self.xgf = defaultdict(Decayed)    # team -> expected goals for (play-by-play)
        self.xga = defaultdict(Decayed)
        self.lg_goals = Decayed()
        self.lg = Decayed()                # league SOG per team-game
        self.lg_share = Decayed()
        self.g_sv = defaultdict(Decayed)   # goalie -> saves / shots
        self.g_share = defaultdict(Decayed)
        self.g_hist = defaultdict(lambda: deque(maxlen=10))  # last 10 starts' saves
        self.g_team = {}
        self.g_name = {}
        self.last_played = {}
        self.season = None
        # seed league average so the very first games have a sane prior
        self.lg.add(30.0 * 50, 1.0, 50.0)
        self.lg_share.add(0.975 * 50, 1.0, 50.0)
        self.lg_goals.add(3.0 * 50, 1.0, 50.0)

    # --- rates -------------------------------------------------------
    def league(self):
        return self.lg.s / self.lg.w

    def team_rate(self, table, team):
        d = table.get(team)
        lg = self.league()
        k = self.p.k_team
        if d is None:
            return lg
        return (d.s + k * lg) / (d.w + k)

    def goalie_sv(self, gid):
        d = self.g_sv.get(gid)
        k = self.p.k_sv
        if d is None:
            return LEAGUE_SV
        return (d.s + k * LEAGUE_SV) / (d.w + k)

    def goalie_share(self, gid):
        d = self.g_share.get(gid)
        base = self.lg_share.s / self.lg_share.w
        k = self.p.k_share
        if d is None:
            return base
        return (d.s + k * base) / (d.w + k)

    # --- projection --------------------------------------------------
    def project(self, team, opp, gid, is_home, playoff, b2b):
        p = self.p
        lg = self.league()
        d = self.team_rate(self.dfn, team)
        o = self.team_rate(self.off, opp)
        exp_sa = lg * (d / lg) ** p.a * (o / lg) ** p.b
        exp_sa *= p.home if is_home else 1.0 / p.home
        if playoff:
            exp_sa *= p.playoff
        if b2b:
            exp_sa *= p.b2b
        sv = self.goalie_sv(gid)
        share = self.goalie_share(gid)
        return exp_sa, sv, share, exp_sa * share * sv, d, o

    # --- updates -----------------------------------------------------
    def new_season(self, season):
        if self.season is not None and season != self.season:
            c = self.p.carry
            for tbl in (self.off, self.dfn, self.gf, self.ga, self.xgf, self.xga):
                for v in tbl.values():
                    v.scale(c)
            # goalies keep more of their history than teams do (rosters change more)
            for v in self.g_sv.values():
                v.scale(min(1.0, c + 0.35))
        self.season = season

    def goal_rate(self, table, team):
        lg = self.lg_goals.s / self.lg_goals.w
        d = table.get(team)
        k = self.p.k_team
        return lg if d is None else (d.s + k * lg) / (d.w + k)

    def update_team(self, team, sog_for, sog_against, date, goals_for=None, goals_against=None,
                    xg_for=None, xg_against=None):
        self.off[team].add(sog_for, self.dec)
        self.dfn[team].add(sog_against, self.dec)
        if goals_for is not None:
            self.gf[team].add(goals_for, self.dec)
            self.ga[team].add(goals_against, self.dec)
            self.lg_goals.add(goals_for, 0.999)
        if xg_for is not None and xg_for == xg_for:  # skip NaN
            self.xgf[team].add(xg_for, self.dec)
            self.xga[team].add(xg_against, self.dec)
        self.lg.add(sog_for, 0.999)
        self.last_played[team] = date

    def update_goalie(self, gid, name, team, saves, shots, toi):
        self.g_sv[gid].add(saves, self.sv_dec, shots)
        share = min(toi, 60.0) / 60.0
        self.g_share[gid].add(share, self.sv_dec)
        self.lg_share.add(share, 0.999)
        self.g_hist[gid].append(saves)
        self.g_team[gid] = team
        self.g_name[gid] = name


def run(tg: pd.DataFrame, starts: pd.DataFrame, p: Params, record_from_season=None):
    """Walk forward through every game. Returns (projections DataFrame, final State)."""
    st = State(p)
    starts = starts.set_index(["game_id", "team_abbrev"])
    rows = []
    tg = tg.sort_values(["game_date", "game_id"])
    for date, day in tg.groupby("game_date", sort=True):
        season = int(day.season.iloc[0])
        st.new_season(season)
        dt = pd.Timestamp(date)
        # 1) project every start on this date with pre-game state
        for r in day.itertuples(index=False):
            key = (r.game_id, r.team_abbrev)
            if key not in starts.index:
                continue
            s = starts.loc[key]
            gid = int(s.player_id)
            last = st.last_played.get(r.team_abbrev)
            b2b = last is not None and (dt - pd.Timestamp(last)).days == 1
            exp_sa, sv, share, proj, d, o = st.project(
                r.team_abbrev, r.opp_team_abbrev, gid, r.is_home, r.game_type == "P", b2b)
            hist = st.g_hist.get(gid)
            if record_from_season is None or season >= record_from_season:
                rows.append({
                    "game_id": r.game_id, "date": date, "season": season, "game_type": r.game_type,
                    "team": r.team_abbrev, "opp": r.opp_team_abbrev, "is_home": bool(r.is_home),
                    "b2b": bool(b2b), "goalie_id": gid, "goalie": s.player_name,
                    "exp_sa": exp_sa, "sv": sv, "share": share, "proj": proj,
                    "team_def": d, "opp_off": o, "league": st.league(),
                    "l10": float(np.mean(hist)) if hist and len(hist) >= 5 else np.nan,
                    "saves": int(s.saves), "shots": int(s.shots_against), "toi": float(s.toi_min),
                    "actual_team_sa": int(r.opp_shots_on_goal),
                    "gf_rate": st.goal_rate(st.gf, r.team_abbrev), "ga_rate": st.goal_rate(st.ga, r.team_abbrev),
                    "lg_goals": st.lg_goals.s / st.lg_goals.w,
                    "xgf_rate": st.goal_rate(st.xgf, r.team_abbrev), "xga_rate": st.goal_rate(st.xga, r.team_abbrev),
                    "goals_for": int(r.goals), "goals_against": int(r.opp_goals),
                })
        # 2) update with this date's results
        for r in day.itertuples(index=False):
            st.update_team(r.team_abbrev, r.shots_on_goal, r.opp_shots_on_goal, date,
                           r.goals, r.opp_goals, getattr(r, "xgf", None), getattr(r, "opp_xgf", None))
            key = (r.game_id, r.team_abbrev)
            if key in starts.index:
                s = starts.loc[key]
                st.update_goalie(int(s.player_id), s.player_name, r.team_abbrev,
                                 s.saves, s.shots_against, s.toi_min)
    return pd.DataFrame(rows), st


# ---------------------------------------------------------------------------
# Proxy lines + grading
# ---------------------------------------------------------------------------

def proxy_line(avg: float) -> float:
    """Books hang saves lines on the half point. A naive book prices a goalie off
    his last-10-start average: floor(avg) + 0.5 (so there are no pushes)."""
    return math.floor(avg) + 0.5


def normal_over_prob(proj, line, sd):
    z = (line - proj) / sd
    return 0.5 * math.erfc(z / math.sqrt(2))


def grade(df: pd.DataFrame, sd: float, line_col="line"):
    out = df.copy()
    out["edge"] = out.proj - out[line_col]
    out["side"] = np.where(out.edge > 0, "OVER", "UNDER")
    out["p_side"] = [
        normal_over_prob(p, l, sd) if e > 0 else 1 - normal_over_prob(p, l, sd)
        for p, l, e in zip(out.proj, out[line_col], out.edge)
    ]
    went_over = out.saves > out[line_col]
    out["hit"] = np.where(out.side == "OVER", went_over, ~went_over)
    return out


def tier(abs_edge: float) -> str:
    """Confidence tiers, matching the edge markers used on the old sheet."""
    if abs_edge >= 2.5:
        return "HIGH"
    if abs_edge >= 1.5:
        return "MED"
    if abs_edge >= 1.0:
        return "LOW"
    return "PASS"
