# Goalie saves model: backtest and MoneyPuck check (2026-11-03)

Every regular-season start, walk-forward: each game projected only from games before it, with every fitted weight taken from the season before. Data through 2026-11-02. Reproduce: `python model/fit_sa.py --corsi` (weights) and the tables below.

## 1. Data check against MoneyPuck

- Team shots on goal per game (this season, every team-game): 93-97% identical to MoneyPuck, never more than 2 shots apart (official-scorer differences). Shot attempts correlate 0.996; goals 0.998.
- Goalie season totals differ only by relief appearances (the model's starts table leaves them out on purpose).
- Our play-by-play expected goals correlate 0.85 with MoneyPuck's xG per game; xG of either kind did not improve the shots-against model, so it isn't used there.

## 2. What changed in the projection

`exp_SA` (shots the goalie's team faces) now uses shot attempts as well as shots on goal: MoneyPuck's score-adjusted unblocked attempts (Fenwick) when MoneyPuck covers the season (it does: 100% of this season's team-games), otherwise our own Corsi from the play-by-play. Weights are a Poisson GLM on the previous season (`fit_sa.fit_corsi`); for 2026-27: shots on goal a 0.46 / b 0.38, Fenwick against 0.50 / opponent Fenwick for 0.59 (Corsi fallback: a 0.83, b 0.59, 0.13, 0.38). The old model was shots on goal only (a 0.85, b 0.90).

| season | model | starts | saves MAE | saves RMSE | corr | shots-against MAE | shots-against corr | log-lik |
|---|---|---|---|---|---|---|---|---|
| 2025-26 | old (shots on goal only) | 2624 | 5.297 | 6.779 | 0.2956 | 4.836 | 0.3717 | -3.3296 |
| 2025-26 | Corsi (ours) | 2624 | 5.296 | 6.771 | 0.2986 | 4.834 | 0.3745 | -3.3285 |
| 2025-26 | MoneyPuck score-adj Fenwick | 2624 | 5.293 | 6.77 | 0.2992 | 4.827 | 0.378 | -3.3281 |
| 2026-27 | old (shots on goal only) | 470 | 5.006 | 6.439 | 0.2547 | 4.543 | 0.3766 | -3.274 |
| 2026-27 | Corsi (ours) | 470 | 4.999 | 6.435 | 0.2626 | 4.523 | 0.3874 | -3.2728 |
| 2026-27 | MoneyPuck score-adj Fenwick | 470 | 5.003 | 6.439 | 0.2644 | 4.509 | 0.3941 | -3.2739 |

Shots against improves in both seasons with MoneyPuck's attempts (corr .372 -> .378 and .377 -> .394). Saves improve on every measure in 2025-26; in 2026-27 (470 starts) MoneyPuck and our Corsi are within 0.004 saves of each other.

## 3. Against the real saves lines this season

Graded DraftKings / DFS saves lines, one per goalie-night, bias-corrected projection (30-day half-life).

| model | lines | record leaning with the model | Brier | edge 1.5+ | edge 2.5+ | edge 3.0+ |
|---|---|---|---|---|---|---|
| old (shots on goal only) | 376 | 210-166 (55.9%) | 0.2482 | 70-54 (56.5%) | 20-19 (51.3%) | 8-8 (50.0%) |
| new (MoneyPuck Fenwick) | 376 | 211-165 (56.1%) | 0.248 | 77-58 (57.0%) | 26-20 (56.5%) | 11-10 (52.4%) |

## 4. Tested and left as is

- Save% shrinkage (k_sv 600-4000 shots) and its half-life: within +/- 0.005 saves of MAE; unchanged.
- Shot quality (team xG allowed per shot, opponent xG per shot) in save%: about 0.015 saves; not worth the extra term.
- MoneyPuck high-danger shots, expected shots on goal, score/venue-adjusted xG as shots-against inputs: no consistent gain.

## 5. MoneyPuck in the build

`model/moneypuck.py` refreshes goalie / team season summaries and all 32 team game logs at most once every 20 hours, in its own workflow step capped at 5 minutes (4 downloads at a time), cached in `model/data/moneypuck/`. If MoneyPuck is missing or covers less than 90% of the season, the engine falls back to our own Corsi automatically. Data from MoneyPuck.com.
