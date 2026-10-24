# Shots-against baseline (step 2)

Walk-forward tuning on every 2025-26 and 2026-27 start (`model/fit_sa.py`). Residual = shots faced − exp_SA, so positive means the model expected too few shots.

## Recency settings tried (shots-against squared error, all starts from 2025-26)

| half_life (games) | lg_half_life (team-games) | mean faced − exp 2025-26 | 2026-27 | MAE 2025-26 | MAE 2026-27 |
|---|---|---|---|---|---|
| 10 | 120 | -0.05 | +0.03 | 4.891 | 4.521 |
| 10 | 350 | -0.02 | +0.07 | 4.892 | 4.521 |
| 10 | 693 | +0.01 | +0.11 | 4.891 | 4.519 |
| 14 | 120 | -0.07 | -0.07 | 4.872 | 4.521 |
| 14 | 350 | -0.05 | -0.02 | 4.872 | 4.519 |
| 14 | 693 | -0.01 | +0.03 | 4.872 | 4.516 |
| 20 | 120 | -0.11 | -0.19 | 4.859 | 4.524 |
| 20 | 350 | -0.08 | -0.14 | 4.860 | 4.521 |
| 20 (current) | 693 | -0.04 | -0.07 | 4.859 | 4.517 |
| 30 | 120 | -0.18 | -0.34 | 4.855 | 4.535 |
| 30 | 350 | -0.14 | -0.27 | 4.855 | 4.530 |
| 30 **(chosen)** | 693 | -0.10 | -0.20 | 4.854 | 4.525 |

Walk-forward choices by week (first weeks need 300 prior starts):

2026-05-18: 30/350, 2026-05-25: 30/120, 2026-06-01: 30/120, 2026-06-08: 30/120, 2026-09-28: 30/120, 2026-10-05: 30/120, 2026-10-12: 30/693, 2026-10-19: 30/693

## Before vs after (2026-27, walk-forward)

| model | starts | mean faced − exp | MAE | late Oct (15th+) faced − exp |
|---|---|---|---|---|
| current (half_life 20, lg 693, gs 0.015) | 334 | -0.07 | 4.517 | +0.64 |
| new, walk-forward recency + gs | 334 | -0.20 | 4.522 | +0.51 |

Late-October nights have about 20-30 starts each, and the shot count's game-to-game SD is about 5.5, so one night's mean has a standard error near 1.1 shots. The Oct 20 and Oct 22 gaps of about +1 are within one standard error of zero.

## Game script (gs)

Walk-forward gs by week: 2026-05-18: 0.020, 2026-05-25: 0.020, 2026-06-01: 0.020, 2026-06-08: 0.020, 2026-09-28: 0.020, 2026-10-05: 0.020, 2026-10-12: 0.020, 2026-10-19: 0.020

Fitted on all of 2025-26 + 2026-27: **gs = 0.025** (was 0.015). The sign is constrained (gs ≥ 0, so underdogs face more shots), and the multiplier is capped at ±12%, so no game moves exp_SA by more than 12% (at gs 0.025 the cap binds only past p_win 0.011).

| p_win bucket (2026-27) | starts | faced − exp, current | faced − exp, new |
|---|---|---|---|
| (0.0, 0.38] | 49 | +0.42 | +0.15 |
| (0.38, 0.45] | 68 | +0.81 | +0.55 |
| (0.45, 0.55] | 100 | -0.12 | -0.26 |
| (0.55, 0.62] | 68 | -0.96 | -1.01 |
| (0.62, 1.0] | 49 | -0.46 | -0.38 |
| home | 167 | -0.59 | -0.64 |
| away | 167 | +0.45 | +0.22 |

## League mean check

Model league average over 2026-27 starts: 27.63 (now 27.62); actual 2026-27 shots on goal per team-game: 27.28; 2025-26: 27.85.

