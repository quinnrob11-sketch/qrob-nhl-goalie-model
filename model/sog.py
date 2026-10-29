"""Skater shots-on-goal props (and, with stat="points", the points model in points.py).

    raw  = rate/60 x expected TOI x (opponent allowed / league)^c_opp x (team for / league)^c_team
           x home x back-to-back x opponent back-to-back
    proj = cal_a + cal_b x raw      (linear recalibration fitted on the previous season, fit_props.py)

    shots/60  player's recency-weighted rate, shrunk to his position's average
    TOI       player's recency-weighted ice time, shrunk to his position's average
    opponent  how many shots the opponent allows per game vs league (team rate,
              same idea as the saves model), with fitted strength c
Probability of the OVER comes from a negative binomial with mean = proj. Dispersion scales with
the mean (size = disp_k x proj, so variance = proj x (1 + 1/disp_k)): measured shot counts vary about
1.05-1.1x their mean at every volume, while a fixed size over-spread high-volume shooters and made
unders on stars look better than they are. disp_k = 0 keeps the old fixed size `disp`.

    python model/sog.py     # fit on 2024-25, test on 2025-26 + real PrizePicks lines

Walk-forward: each game is projected only from games on earlier dates.
"""
from __future__ import annotations

import json
import math
import os
from collections import defaultdict, deque
from dataclasses import asdict, dataclass, replace

import numpy as np
import pandas as pd

import data
import prizepicks

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "output")
TRAIN, TEST = 2025, 2026


@dataclass
class SogParams:
    """Defaults are the fitted values in model/output/sog_params.json (a test keeps them equal)."""
    rate_hl: float = 60.0     # games; half-life of shots/60
    toi_hl: float = 8.0       # games; half-life of TOI (short, so a role change shows up fast)
    k_min: float = 100.0      # prior strength for shots/60, in minutes at position average
    k_toi: float = 1.0        # prior strength for TOI, in games
    carry: float = 0.7        # share of last season's evidence kept at a new season
    c_opp: float = 1.0        # weight of the opponent's shots-allowed factor
    home: float = 1.0195      # home multiplier (fitted from residuals)
    disp: float = 12.0        # negative-binomial size when disp_k = 0 (larger = closer to Poisson)
    disp_k: float = 10.0      # size = disp_k x mean when > 0 (variance = mean x (1 + 1/disp_k))
    b2b: float = 0.9738       # multiplier when the player's team played yesterday
    opp_b2b: float = 1.0201   # multiplier when the opponent played yesterday
    c_team: float = 0.0       # weight of the player's own team rate (points: team scoring)
    cal_a: float = -0.1132    # linear recalibration of the mean: proj = cal_a + cal_b x raw
    cal_b: float = 1.047

    def to_dict(self):
        return asdict(self)

    @classmethod
    def load(cls, path: str) -> "SogParams":
        import engine
        return cls(**engine.load_fields(cls, path))


class D:
    __slots__ = ("s", "w")

    def __init__(self):
        self.s = 0.0
        self.w = 0.0

    def add(self, x, dec, wt=1.0):
        self.s = self.s * dec + x
        self.w = self.w * dec + wt


def _minutes(toi: pd.Series) -> pd.Series:
    parts = toi.fillna("0:00").str.split(":", expand=True).astype(float)
    return parts[0] + parts[1] / 60.0


def load(years):
    frames = []
    for y in years:
        p = data.fetch("skater", y)
        if not p:
            continue
        s = pd.read_parquet(p, columns=["game_id", "game_date", "team_abbrev", "home_away", "player_id",
                                        "player_name", "position", "shots_on_goal", "points", "goals", "assists", "toi"])
        s["season"] = y
        frames.append(s)
    s = pd.concat(frames, ignore_index=True)
    s["toi_min"] = _minutes(s.toi)
    s["pos"] = np.where(s.position == "D", "D", "F")
    s["game_type"] = s.game_id.astype(str).str[4:6].map({"02": "R", "03": "P"})
    s = s[s.game_type.notna() & (s.toi_min > 0)]
    # opponent per game
    teams = s.groupby(["game_id", "team_abbrev"]).size().reset_index()[["game_id", "team_abbrev"]]
    opp = teams.rename(columns={"team_abbrev": "opp"})
    pair = teams.merge(opp, on="game_id")
    pair = pair[pair.team_abbrev != pair.opp]
    s = s.merge(pair, on=["game_id", "team_abbrev"])
    return s.sort_values(["game_date", "game_id"]).reset_index(drop=True)


class State:
    def __init__(self, p: SogParams, stat: str = "shots_on_goal"):
        self.p = p
        self.rdec = 0.5 ** (1 / p.rate_hl)
        self.tdec = 0.5 ** (1 / p.toi_hl)
        self.shots = defaultdict(D)   # player -> decayed shots (weight = minutes)
        self.toi = defaultdict(D)     # player -> decayed TOI per game
        self.hist = defaultdict(lambda: deque(maxlen=10))
        self.pos_rate = {"F": D(), "D": D()}
        self.pos_toi = {"F": D(), "D": D()}
        self.team_sa = defaultdict(D)  # stat allowed per game (shots or points against)
        self.team_for = defaultdict(D)  # stat for per game
        self.lg_sa = D()
        self.last_played = {}
        r0, lg0 = (dict(F=1.9, D=1.0), 6.9) if stat == "points" else (dict(F=7.0, D=4.5), 28.5)
        for pos, r, t in (("F", r0["F"], 15.5), ("D", r0["D"], 20.5)):
            self.pos_rate[pos].add(r / 60 * 1000, 1, 1000)
            self.pos_toi[pos].add(t * 20, 1, 20)
        self.lg_sa.add(lg0 * 20, 1, 20)
        self.season = None
        self.name, self.team, self.posn = {}, {}, {}

    def new_season(self, season):
        if self.season is not None and season != self.season:
            for tbl in (self.shots, self.toi, self.team_sa, self.team_for):
                for v in tbl.values():
                    v.s *= self.p.carry
                    v.w *= self.p.carry
        self.season = season

    def rate60(self, pid, pos):
        base = self.pos_rate[pos].s / self.pos_rate[pos].w
        d = self.shots.get(pid)
        k = self.p.k_min
        return (base * k if d is None else d.s + base * k) / ((0 if d is None else d.w) + k) * 60

    def exp_toi(self, pid, pos):
        base = self.pos_toi[pos].s / self.pos_toi[pos].w
        d = self.toi.get(pid)
        k = self.p.k_toi
        return base if d is None else (d.s + base * k) / (d.w + k)

    def opp_factor(self, opp):
        lg = self.lg_sa.s / self.lg_sa.w
        d = self.team_sa.get(opp)
        rate = lg if d is None else (d.s + 10 * lg) / (d.w + 10)
        return (rate / lg) ** self.p.c_opp

    def team_factor(self, team):
        if not self.p.c_team:
            return 1.0
        lg = self.lg_sa.s / self.lg_sa.w
        d = self.team_for.get(team)
        rate = lg if d is None else (d.s + 10 * lg) / (d.w + 10)
        return (rate / lg) ** self.p.c_team

    def raw(self, pid, pos, opp, is_home, team=None, b2b=False, opp_b2b=False):
        mult = self.p.home if is_home else 1 / self.p.home
        mult *= (self.p.b2b if b2b else 1.0) * (self.p.opp_b2b if opp_b2b else 1.0)
        return self.rate60(pid, pos) / 60 * self.exp_toi(pid, pos) * self.opp_factor(opp) * self.team_factor(team) * mult

    def project(self, pid, pos, opp, is_home, team=None, b2b=False, opp_b2b=False):
        return calibrated(self.raw(pid, pos, opp, is_home, team, b2b, opp_b2b), self.p)


def calibrated(raw: float, p: SogParams) -> float:
    """The linear mean recalibration (fit_props.py), floored so a projection stays positive."""
    return max(0.02, p.cal_a + p.cal_b * raw)


def size_for(mean: float, p: SogParams) -> float:
    """Negative-binomial size for this mean: disp_k x mean when fitted, else the fixed size."""
    return max(p.disp_k * max(mean, 0.02), 0.5) if p.disp_k else p.disp


def _yesterday(st, team, date) -> bool:
    last = st.last_played.get(team)
    return last is not None and (pd.Timestamp(date) - pd.Timestamp(last)).days == 1


def run(s: pd.DataFrame, p: SogParams, record_from=None, stat: str = "shots_on_goal"):
    """Walk forward through every skater-game. `stat` is the box-score column projected
    (shots_on_goal for SOG, points for the points model); the `shots` output column holds it."""
    st = State(p, stat)
    rows = []
    for date, day in s.groupby("game_date", sort=True):
        st.new_season(int(day.season.iloc[0]))
        pid, pos, opp, home = day.player_id.values, day.pos.values, day.opp.values, (day.home_away == "home").values
        team, val = day.team_abbrev.values, day[stat].values
        if record_from is None or day.season.iloc[0] >= record_from:
            b2b = {t: _yesterday(st, t, date) for t in set(team) | set(opp)}
            for i in range(len(day)):
                h = st.hist.get(pid[i])
                raw = st.raw(pid[i], pos[i], opp[i], home[i], team[i], b2b[team[i]], b2b[opp[i]])
                rows.append((date, int(day.season.iloc[0]), day.game_type.iloc[i], int(pid[i]), day.player_name.iloc[i],
                             team[i], opp[i], bool(home[i]), pos[i], calibrated(raw, p), raw,
                             bool(b2b[team[i]]), bool(b2b[opp[i]]),
                             float(np.mean(h)) if h and len(h) >= 10 else np.nan, int(val[i])))
        # updates
        for r, v in zip(day.itertuples(index=False), val):
            st.shots[r.player_id].add(v, st.rdec, r.toi_min)
            st.toi[r.player_id].add(r.toi_min, st.tdec)
            st.pos_rate[r.pos].add(v, 0.9999, r.toi_min)
            st.pos_toi[r.pos].add(r.toi_min, 0.9999)
            st.hist[r.player_id].append(v)
            st.name[r.player_id], st.team[r.player_id], st.posn[r.player_id] = r.player_name, r.team_abbrev, r.pos
        team_tot = day.groupby(["game_id", "team_abbrev", "opp"])[stat].sum()
        for (gid, t, o), n in team_tot.items():
            st.team_sa[o].add(n, 0.5 ** (1 / 20))
            st.team_for[t].add(n, 0.5 ** (1 / 20))
            st.lg_sa.add(n, 0.999)
            st.last_played[t] = date
    cols = ["date", "season", "game_type", "player_id", "player", "team", "opp", "is_home", "pos", "proj", "raw",
            "b2b", "opp_b2b", "l10", "shots"]
    return pd.DataFrame(rows, columns=cols), st


# ---- distribution --------------------------------------------------------

def nb_cdf(k, mean, size):
    """P(X <= k) for a negative binomial with the given mean and size."""
    if k < 0:
        return 0.0
    p = size / (size + mean)
    term = p ** size
    tot = term
    for i in range(1, int(k) + 1):
        term *= (i - 1 + size) / i * (1 - p)
        tot += term
    return min(tot, 1.0)


def p_over(mean, line, size):
    """P(over | no push). Over = X > line; on a whole-number line X == line pushes,
    so both sides are renormalised over the non-push outcomes."""
    over = 1 - nb_cdf(math.floor(line), mean, size)
    if line == int(line):
        under = nb_cdf(int(line) - 1, mean, size)
        return over / (over + under) if over + under > 0 else 0.5
    return over


def nb_logpmf(x, mean, size):
    return (math.lgamma(x + size) - math.lgamma(size) - math.lgamma(x + 1)
            + size * math.log(size / (size + mean)) + x * math.log(mean / (size + mean)))


# ---- proxy line + grading ------------------------------------------------

def fair_proxy_line(avg, size):
    """The x.5 line a naive book would hang from a player's last-10 average:
    the one whose over probability is closest to 50%."""
    best = None
    for L in (0.5, 1.5, 2.5, 3.5, 4.5, 5.5):
        d = abs(p_over(max(avg, 0.05), L, size) - 0.5)
        if best is None or d < best[0]:
            best = (d, L)
    return best[1]


def grade(df, size, line_col="line"):
    g = df.copy()
    g["p_over"] = [p_over(max(m, 0.05), L, size) for m, L in zip(g.proj, g[line_col])]
    g["side"] = np.where(g.p_over >= 0.5, "OVER", "UNDER")
    g["p_side"] = np.where(g.side == "OVER", g.p_over, 1 - g.p_over)
    push = g.shots == g[line_col]
    over = g.shots > g[line_col]
    g["result"] = np.where(push, "push", np.where((g.side == "OVER") == over, "hit", "miss"))
    return g


PROB_BUCKETS = [0.52, 0.55, 0.58, 0.60, 0.62, 0.65]


def bucket_table(g):
    out = []
    for lo in PROB_BUCKETS:
        s = g[(g.p_side >= lo) & (g.result != "push")]
        if not len(s):
            continue
        hit = (s.result == "hit")
        o, u = s[s.side == "OVER"], s[s.side == "UNDER"]
        out.append({"min_p": lo, "n": int(len(s)), "hit": float(hit.mean()),
                    "over_n": int(len(o)), "over_hit": float((o.result == "hit").mean()) if len(o) else None,
                    "under_n": int(len(u)), "under_hit": float((u.result == "hit").mean()) if len(u) else None,
                    "units": float(hit.sum() * 100 / 115 - (~hit).sum())})
    return out


def fit(s):
    p = SogParams()

    def score(pp):
        df, _ = run(s, pp, record_from=TRAIN)
        d = df[df.season == TRAIN]
        return float((d.proj - d.shots).abs().mean()), d

    best, d = score(p)
    grid = {"rate_hl": [15, 30, 60, 120], "toi_hl": [4, 8, 16], "k_min": [100, 200, 400, 800],
            "k_toi": [1, 3, 8], "carry": [0.3, 0.5, 0.8], "c_opp": [0, 0.5, 1.0]}
    for name, vals in grid.items():
        for v in vals:
            cand = replace(p, **{name: v})
            sc, dd = score(cand)
            if sc < best - 1e-5:
                best, p, d = sc, cand, dd
        print(f"  {name:>8} = {getattr(p, name):<6} train MAE {best:.4f}")
    # home multiplier and NB size from train residuals
    r = d.shots.sum() / d.proj.sum()
    hr = (d[d.is_home].shots.sum() / d[d.is_home].proj.sum()) / (d[~d.is_home].shots.sum() / d[~d.is_home].proj.sum())
    p = replace(p, home=round(float(math.sqrt(hr)) * p.home, 4))
    _, d = score(p)
    best_size = max((sum(nb_logpmf(x, max(m, 0.05), k) for x, m in zip(d.shots, d.proj)), k)
                    for k in (2, 3, 5, 8, 12, 20, 50, 200))[1]
    return replace(p, disp=float(best_size)), r


def real_line_test(df, size):
    pp = json.load(open(os.path.join(HERE, "data", "pp_sog_2026_playoffs.json")))["props"]
    d = df[(df.season == TEST) & (df.game_type == "P")].copy()
    d["key"] = d.player.map(prizepicks.name_key)
    # The old scraper ran ~8pm ET, after that night's games had started, so a
    # saved prop is for the player's NEXT game: the first one on or after the
    # scrape date, within two days.
    d["d"] = pd.to_datetime(d.date)
    rows = []
    for r in pp:
        d0 = pd.Timestamp(r["date"])
        m = d[(d.key == prizepicks.name_key(r["player"])) & (d.d >= d0) & (d.d <= d0 + pd.Timedelta(days=2))]
        if len(m):
            x = m.sort_values("d").iloc[0].to_dict()
            x["line"] = r["line"]
            rows.append(x)
    g = grade(pd.DataFrame(rows), size)
    return {"props": len(pp), "matched": len(g), "buckets": bucket_table(g),
            "mae_model": float((g.proj - g.shots).abs().mean()),
            "line_avg": float(g.line.mean()), "shots_avg": float(g.shots.mean()), "proj_avg": float(g.proj.mean())}, g


def main():
    import sys
    os.makedirs(OUT, exist_ok=True)
    s = load([2024, TRAIN, TEST])
    ppath = os.path.join(OUT, "sog_params.json")
    if "--no-fit" in sys.argv and os.path.exists(ppath):
        p = SogParams.load(ppath)
    else:
        print("Fitting SOG model on 2024-25 ...")
        p, _ = fit(s)
        json.dump(p.to_dict(), open(ppath, "w"), indent=2)
    print("Params:", p)
    df, _ = run(s, p, record_from=TRAIN)
    report = {"params": p.to_dict(), "line_proxy": "x.5 line nearest a 50% over for the player's last-10 average"}
    for season in (TRAIN, TEST):
        d = df[(df.season == season) & df.l10.notna() & (df.l10 >= 1.0)].copy()
        d["line"] = d.l10.apply(lambda a: fair_proxy_line(a, p.disp))
        g = grade(d, p.disp)
        rep = {"season": season, "props": int(len(g)),
               "mae_model": float((d.proj - d.shots).abs().mean()), "mae_l10": float((d.l10 - d.shots).abs().mean()),
               "buckets": bucket_table(g)}
        report[str(season)] = rep
        print(f"\n{season}: {rep['props']} player-games (L10 avg >= 1) | MAE {rep['mae_model']:.3f} vs L10 {rep['mae_l10']:.3f}")
        for b in rep["buckets"]:
            print(f"  P>={b['min_p']:.2f}  n={b['n']:6d}  hit {b['hit']:.1%}  OVER {b['over_n']} {b['over_hit'] or 0:.1%}  "
                  f"UNDER {b['under_n']} {b['under_hit'] or 0:.1%}  {b['units']:+.0f}u")
    real, g = real_line_test(df, p.disp)
    g[["date", "player", "team", "opp", "line", "proj", "p_over", "side", "p_side", "shots", "result"]].round(3).to_csv(
        os.path.join(OUT, "sog_real_pp_graded.csv"), index=False)
    report["real_pp_2026_playoffs"] = real
    print(f"\nREAL PrizePicks lines (2026 playoffs): {real['matched']}/{real['props']} matched | "
          f"avg line {real['line_avg']:.2f}, avg shots {real['shots_avg']:.2f}, avg proj {real['proj_avg']:.2f}")
    print(f"  model bias vs real lines: mean proj - line = {(g.proj - g.line).mean():+.2f}, "
          f"mean shots - line = {(g.shots - g.line).mean():+.2f}")
    for b in real["buckets"]:
        print(f"  P>={b['min_p']:.2f}  n={b['n']:4d}  hit {b['hit']:.1%}  OVER {b['over_n']} {b['over_hit'] or 0:.1%}  "
              f"UNDER {b['under_n']} {b['under_hit'] or 0:.1%}  {b['units']:+.1f}u")
    json.dump(report, open(os.path.join(OUT, "sog_backtest.json"), "w"), indent=2)


if __name__ == "__main__":
    main()


def live_proj(rate60: float, toi: float, opp_f: float, team_f: float, is_home: bool, b2b: bool, opp_b2b: bool,
              p: SogParams) -> float:
    """Tonight's projection from exported per-player rates (mirrors State.project; the page has a JS copy)."""
    mult = (p.home if is_home else 1 / p.home) * (p.b2b if b2b else 1.0) * (p.opp_b2b if opp_b2b else 1.0)
    return calibrated(rate60 / 60 * toi * opp_f * team_f * mult, p)
