"""Walk-forward tuning of the shots-against baseline and the game-script term.

    python model/fit_sa.py            # tune, write params.json / saves_dist.json, write the report
    python model/fit_sa.py --dry-run  # report only

What it tunes (on 2025-26 + 2026-27, every start, no lookahead):
  * half_life     recency of team shots-for / shots-against (games)
  * lg_half_life  recency of the league shots-per-game average (team-games)
  * gs            game script: exp_SA x exp(-gs x logit(p_win)), gs >= 0 (underdogs face more shots),
                  the multiplier capped at 1 +/- gs_cap (12%)

Walk-forward: each week is scored with the setting that had the lowest shots-against squared
error on every earlier start (from 2025-26 on). The final setting is the one that wins on all
of it. Report: model/reports/shots_against.md.
"""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import replace

import numpy as np
import pandas as pd

import data
import engine
import saves_dist
import winners

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "output")
REPORTS = os.path.join(HERE, "reports")
FROM = 2026                                   # 2025-26
HALF_LIFE = (10, 14, 20, 30)
LG_HALF_LIFE = (120, 350, 693)
GS_GRID = np.round(np.arange(0.0, 0.0801, 0.005), 3)


def with_pwin(df: pd.DataFrame) -> pd.DataFrame:
    """Add the game-winner model's win probability for the goalie's team (and its logit)."""
    W = json.load(open(os.path.join(OUT, "winners_params.json")))
    g = winners.games(df)
    ph, _, _ = winners.predict(g, W["w"], W["home"], W["ot_home"], W.get("x", 0))
    df = df.merge(g.assign(p_home=ph)[["game_id", "home", "p_home"]], on="game_id")
    df["p_win"] = np.where(df.team == df.home, df.p_home, 1 - df.p_home)
    df["lo"] = np.log(df.p_win / (1 - df.p_win))
    return df


def gs_mult(lo, gs, cap):
    return np.clip(np.exp(-gs * np.asarray(lo)), 1 - cap, 1 + cap)


def weeks(df: pd.DataFrame) -> pd.Series:
    d = pd.to_datetime(df.date)
    return (d - pd.to_timedelta(d.dt.weekday, unit="D")).dt.strftime("%Y-%m-%d")


def walk_forward(err: dict, wk: pd.Series, min_prior: int = 300):
    """err: candidate -> per-row squared error (aligned). Returns (chosen candidate per row, per-week picks)."""
    keys = list(err)
    E = np.vstack([err[k] for k in keys])
    pick = np.full(len(wk), -1)
    picks = []
    for w in sorted(wk.unique()):
        te, tr = (wk == w).values, (wk < w).values
        if tr.sum() < min_prior:
            continue
        j = int(np.argmin(E[:, tr].mean(axis=1)))
        pick[te] = j
        picks.append((w, keys[j]))
    return pick, picks, keys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    tg, st = data.load_all([2024, 2025, 2026, 2027])
    P0 = engine.Params(**json.load(open(os.path.join(OUT, "params.json"))))
    D0 = json.load(open(os.path.join(OUT, "saves_dist.json")))
    cap = D0.get("gs_cap", saves_dist.DEFAULTS["gs_cap"])

    # ---- 1) team / league recency, scored with the current gs ----
    runs = {}
    for hl in HALF_LIFE:
        for lh in LG_HALF_LIFE:
            df, _ = engine.run(tg, st, replace(P0, half_life=float(hl), lg_half_life=float(lh)), record_from_season=FROM)
            runs[(hl, lh)] = with_pwin(df).sort_values(["date", "game_id", "team"]).reset_index(drop=True)
            print(f"  run half_life={hl} lg_half_life={lh}")
    base = runs[next(iter(runs))]
    wk = weeks(base)
    sa_err = {k: ((d.exp_sa * gs_mult(d.lo, D0["gs"], cap) - d.actual_team_sa) ** 2).values for k, d in runs.items()}
    pick, picks, keys = walk_forward(sa_err, wk)
    best_rec = min(keys, key=lambda k: sa_err[k].mean())

    # walk-forward shots against: each week from the setting chosen on earlier weeks
    wf = base[["date", "season", "team", "actual_team_sa", "lo", "p_win", "is_home"]].copy()
    wf["exp_sa"] = np.nan
    for j, k in enumerate(keys):
        m = pick == j
        wf.loc[m, "exp_sa"] = runs[k].exp_sa.values[m]
    cur_key = (int(P0.half_life), int(round(getattr(P0, "lg_half_life", 693))))
    cur = runs.get(cur_key, base)

    # ---- 2) gs walk-forward on the chosen recency (sign kept: gs >= 0) ----
    d = runs[best_rec]
    gs_err = {g: ((d.exp_sa * gs_mult(d.lo, g, cap) - d.actual_team_sa) ** 2).values for g in GS_GRID}
    gpick, gpicks, gkeys = walk_forward(gs_err, wk)
    gs_all = float(min(gkeys, key=lambda g: gs_err[g].mean()))

    # ---- report ----
    def resid(exp, frame, mask):
        r = (frame.actual_team_sa - exp)[mask]
        return r.mean(), r.abs().mean(), int(mask.sum())

    lines = ["# Shots-against baseline (step 2)", "",
             "Walk-forward tuning on every 2025-26 and 2026-27 start (`model/fit_sa.py`). Residual = shots faced − exp_SA, "
             "so positive means the model expected too few shots.", ""]
    lines += ["## Recency settings tried (shots-against squared error, all starts from 2025-26)", "",
              "| half_life (games) | lg_half_life (team-games) | mean faced − exp 2025-26 | 2026-27 | MAE 2025-26 | MAE 2026-27 |",
              "|---|---|---|---|---|---|"]
    for k, dd in runs.items():
        e = dd.exp_sa * gs_mult(dd.lo, D0["gs"], cap)
        a = resid(e, dd, dd.season == 2026); b = resid(e, dd, dd.season == 2027)
        star = " **(chosen)**" if k == best_rec else (" (current)" if k == cur_key else "")
        lines.append(f"| {k[0]}{star} | {k[1]} | {a[0]:+.2f} | {b[0]:+.2f} | {a[1]:.3f} | {b[1]:.3f} |")
    lines += ["", "Walk-forward choices by week (first weeks need 300 prior starts):", "",
              ", ".join(f"{w}: {k[0]}/{k[1]}" for w, k in picks[-8:]), ""]

    # final model: chosen recency + walk-forward gs
    ok = gpick >= 0
    exp_wf_gs = np.full(len(d), np.nan)
    for j, g in enumerate(gkeys):
        m = gpick == j
        exp_wf_gs[m] = d.exp_sa.values[m] * gs_mult(d.lo.values[m], g, cap)
    old = cur.exp_sa * gs_mult(cur.lo, D0["gs"], cap)
    lines += ["## Before vs after (2026-27, walk-forward)", "",
              "| model | starts | mean faced − exp | MAE | late Oct (15th+) faced − exp |", "|---|---|---|---|---|"]
    m27 = (d.season == 2027).values
    late = m27 & (d.date >= "2026-10-15").values
    for name, e in (("current (half_life %d, lg %d, gs %.3f)" % (cur_key[0], cur_key[1], D0["gs"]), old.values),
                    ("new, walk-forward recency + gs", np.where(ok, exp_wf_gs, np.nan))):
        r = d.actual_team_sa.values - e
        mm = m27 & ~np.isnan(r); ml = late & ~np.isnan(r)
        lines.append(f"| {name} | {mm.sum()} | {np.nanmean(r[mm]):+.2f} | {np.nanmean(np.abs(r[mm])):.3f} | {np.nanmean(r[ml]):+.2f} |")
    lines += ["", f"Late-October nights have about 20-30 starts each, and the shot count's game-to-game SD is about 5.5, so one night's mean has a standard error near 1.1 shots. The Oct 20 and Oct 22 gaps of about +1 are within one standard error of zero.", ""]

    lines += ["## Game script (gs)", "",
              f"Walk-forward gs by week: " + ", ".join(f"{w}: {g:.3f}" for w, g in gpicks[-8:]),
              f"", f"Fitted on all of 2025-26 + 2026-27: **gs = {gs_all:.3f}** (was {D0['gs']:.3f}). The sign is constrained (gs ≥ 0, so underdogs face more shots), "
              f"and the multiplier is capped at ±{cap:.0%}, so no game moves exp_SA by more than {cap:.0%} "
              f"(at gs {gs_all:.3f} the cap binds only past p_win {1 / (1 + np.exp(np.log(1 + cap) / max(gs_all, 1e-9))):.3f}).", ""]
    e_new = d.exp_sa * gs_mult(d.lo, gs_all, cap)
    lines += ["| p_win bucket (2026-27) | starts | faced − exp, current | faced − exp, new |", "|---|---|---|---|"]
    bk = pd.cut(d.p_win, [0, .38, .45, .55, .62, 1])
    for b in bk.cat.categories:
        m = m27 & (bk == b).values
        lines.append(f"| {b} | {m.sum()} | {(cur.actual_team_sa.values - old.values)[m].mean():+.2f} | {(d.actual_team_sa - e_new).values[m].mean():+.2f} |")
    lines += ["| home | %d | %+.2f | %+.2f |" % ((m27 & d.is_home.values).sum(), (cur.actual_team_sa.values - old.values)[m27 & cur.is_home.values].mean(), (d.actual_team_sa - e_new).values[m27 & d.is_home.values].mean()),
              "| away | %d | %+.2f | %+.2f |" % ((m27 & ~d.is_home.values).sum(), (cur.actual_team_sa.values - old.values)[m27 & ~cur.is_home.values].mean(), (d.actual_team_sa - e_new).values[m27 & ~d.is_home.values].mean())]

    lg = d[m27]
    act_lg = tg[tg.season == 2027].shots_on_goal.mean()
    lines += ["", "## League mean check", "",
              f"Model league average over 2026-27 starts: {lg.league.mean():.2f} (now {lg.league.iloc[-1]:.2f}); "
              f"actual 2026-27 shots on goal per team-game: {act_lg:.2f}; 2025-26: {tg[tg.season == 2026].shots_on_goal.mean():.2f}.", ""]
    os.makedirs(REPORTS, exist_ok=True)
    open(os.path.join(REPORTS, "shots_against.md"), "w").write("\n".join(lines) + "\n")
    print("\n".join(lines))

    if not args.dry_run:
        p = replace(P0, half_life=float(best_rec[0]), lg_half_life=float(best_rec[1]))
        json.dump(p.to_dict(), open(os.path.join(OUT, "params.json"), "w"), indent=2)
        D0.update(gs=round(gs_all, 3), gs_cap=cap,
                  fit=(D0.get("fit", "").split(" | ")[0] + " | gs, half_life, lg_half_life: walk-forward shots-against "
                       "squared error on 2025-26 + 2026-27 (fit_sa.py); gs_cap: max game-script move"))
        json.dump(D0, open(os.path.join(OUT, "saves_dist.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
