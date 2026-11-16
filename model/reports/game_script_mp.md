# Game script in MoneyPuck mode (`python model/fit_sa.py --gs-mp`)

Shots-against squared error on every start from 2025-26, engine in MoneyPuck mode (Corsi-mode gs 0.025).

| gs | 2025-26 | 2026-27 | all |
|---|---|---|---|
| 0.000 | 36.317 | 32.387 | 35.565 |
| 0.005 | 36.315 | 32.379 | 35.562 |
| 0.010 | 36.319 | 32.378 | 35.564 |
| 0.025 | 36.363 | 32.419 | 35.608 |
| 0.040 | 36.459 | 32.528 | 35.707 |

Walk-forward gs by week: 2026-06-08: 0.005, 2026-09-28: 0.005, 2026-10-05: 0.005, 2026-10-12: 0.005, 2026-10-19: 0.005, 2026-10-26: 0.010, 2026-11-02: 0.010, 2026-11-09: 0.005

Fitted on all of it: **gs_mp = 0.005**. Used whenever the engine runs in MoneyPuck mode (saves_dist.for_mode); the Corsi-mode gs is unchanged.

