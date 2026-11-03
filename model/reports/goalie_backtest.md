# Goalie saves backtest, 2026-27

Built 2026-11-03 17:32 UTC by `python model/backtest_goalie.py`. Walk-forward: every projection uses only games played before that date. Season is the regular season through the latest box score in the NHL feed. MoneyPuck.com goalie game logs and the 2026-27 shot file are the external source.

## Result

No MoneyPuck alternative beat the production projection by more than one standard error and 0.02 saves, so the formula is unchanged. The after column equals the before column (production projection plus the rolling bias).

## Projection accuracy (every regular-season start)

| model | starts | MAE | bias (projected − actual) |
|---|---|---|---|
| before (production, no rolling bias) | 470 | 5.006 | +0.205 |
| before (production + rolling bias) | 470 | 5.000 | -0.029 |
| after | 470 | 5.000 | -0.029 |

Shots the goalie is projected to face vs shots he faced: bias -0.050, MAE 5.010. Team shots against: bias +0.245. Mean shrunk save% 0.9000, actual save% 0.8905.

Full games (time on ice at least 55 minutes) are where a pull did not happen, so the time-in-net haircut makes the projection low there (bias -0.73 on 444 starts). The 18 starts under 40 minutes are high by +14.4 saves. Those two cancel, which is why the unconditional bias is about zero. Removing the haircut would make the average high.

### Slices of the production projection (with the rolling bias)

| slice | n | MAE | bias |
|---|---|---|---|
| all | 470 | 5.00 | -0.03 |
| home | 235 | 4.72 | +0.13 |
| away | 235 | 5.28 | -0.19 |
| b2b | 53 | 4.36 | -1.38 |
| opp b2b | 53 | 4.49 | -0.93 |
| full (TOI ≥ 55) | 444 | 4.58 | -0.73 |
| pull (TOI < 40) | 18 | 14.36 | +14.36 |

## MoneyPuck alternatives (not shipped)

Each one is walk-forward, then the same rolling bias is refit on its own residuals. `dMAE` is the paired change in absolute error versus the production projection (negative would be an improvement). A change is kept only when dMAE is better than both one standard error and 0.02 saves.

| alternative | MAE | bias | dMAE | SE | kept |
|---|---|---|---|---|---|
| GSAx save% (k=1500 shots) | 5.007 | -0.020 | +0.0072 | 0.0033 | no |
| Fenwick shot volume | 4.999 | +0.005 | -0.0010 | 0.0382 | no |
| Fenwick volume + GSAx save% | 5.007 | +0.013 | +0.0070 | 0.0387 | no |

GSAx is MoneyPuck expected goals against minus goals, per shot, shrunk by 1,500 shots and added to a .900 save%. Fenwick volume replaces team shots-on-goal with unblocked shot attempts faced, converted back to shots on goal at the league on-goal rate, with the same home, back-to-back and game-script multipliers. Neither the goalie's recent shot quality nor the opponent's unblocked volume moved the error by a meaningful amount. Back-to-back and opponent back-to-back multipliers were left as fitted: the 2024-25 and 2025-26 residuals are small, and the 2026-27 back-to-back sample is about 50 starts.

## Calibration of P(over) by line

Every 2026-27 regular-season start, at each half-point line. Predicted is the mean of the model's P(saves > line); actual is the share of starts over that line.

| line | n | predicted | actual | gap |
|---|---|---|---|---|
| 22.5 | 470 | 55.5% | 58.3% | +2.8 pts |
| 23.5 | 470 | 49.7% | 53.6% | +3.9 pts |
| 24.5 | 470 | 44.0% | 43.8% | -0.1 pts |
| 25.5 | 470 | 38.4% | 37.2% | -1.2 pts |
| 26.5 | 470 | 33.1% | 30.9% | -2.2 pts |
| 27.5 | 470 | 28.1% | 26.0% | -2.2 pts |
| 28.5 | 470 | 23.6% | 22.6% | -1.0 pts |
| 29.5 | 470 | 19.5% | 18.5% | -1.0 pts |
| 30.5 | 470 | 15.9% | 14.5% | -1.4 pts |

On graded real lines, the side the bias-corrected model leans to:

| projection | side | n | predicted | actual |
|---|---|---|---|---|
| bias-corrected | OVER | 101 | 54.0% | 52.5% |
| bias-corrected | UNDER | 286 | 58.6% | 57.3% |
| calibrated | OVER | 101 | 54.0% | 52.5% |
| calibrated | UNDER | 286 | 58.4% | 57.3% |

## Record and ROI

Graded real lines joined to the walk-forward projection: 387 lines (2026-09-29 to 2026-11-02), one row per date + goalie + line. Units below use the DraftKings price when that line has one, otherwise the 1x DFS price (2-pick at 3x).

| edge | side | n | record | hit % | units | ROI |
|---|---|---|---|---|---|---|
| 1.5 | OVER | 12 | 4-8 | 33.3% | -4.50 | -37.5% |
| 1.5 | UNDER | 118 | 71-47 | 60.2% | +10.81 | 9.2% |
| 2.0 | OVER | 3 | 1-2 | 33.3% | -1.09 | -36.4% |
| 2.0 | UNDER | 71 | 40-31 | 56.3% | +1.51 | 2.1% |
| 2.5 | OVER | 2 | 1-1 | 50.0% | -0.09 | -4.5% |
| 2.5 | UNDER | 40 | 21-19 | 52.5% | -2.05 | -5.1% |
| 3.0 | OVER | 0 | 0-0 | – | +0.00 | – |
| 3.0 | UNDER | 18 | 9-9 | 50.0% | -1.83 | -10.2% |

Play rule (the one the page uses for a TAKE): edge at least **2.5** saves on an over and **3.0** on an under, calibrated P(side) at least **58%**, priced at **1x**. Calibration is side-split and fit only on earlier weeks. Shots and points thresholds are unchanged.

Record: 10-10 (50.0%), units -2.68, ROI -13.4%, n=20, price 1x DFS (2-pick at 3x, break-even 57.7%). This record is the same before and after, because the projection did not change.

- OVER: 1-1, units -0.27, ROI -13.4%, n=2
- UNDER: 9-9, units -2.41, ROI -13.4%, n=18

## MoneyPuck cross-check

Goalie game logs versus NHL starter box scores: 8339 of 8854 matched (94.2%). Regular season 100.0% of 8342; the public game file is regular season only, so playoff starts in it are 0 of 512. Shots-against MAE 0.0112, saves MAE 0.0042, TOI MAE 0.0001, exact shots 98.9%. Team-abbrev disagreements other than Arizona/Utah: 0 (none). Regular-season starts in the NHL file and not in the MoneyPuck file: S. Knight CHI 2026-03-03; D. Wolf CGY 2026-11-02; Y. Askarov SJS 2026-11-02. Source {'2023': 'download', '2024': 'download', '2025': 'download', '2026': 'download'}, through 2026-11-02.

Shot file, 2026: 492 of 492 goalie games joined (`season * 1_000_000 + shot game_id`). On-goal MAE 0.2236 (the shot zip lags the game log and drops a few shots), goals MAE 0.0346, xGoals MAE 0.0596 against the sum of shot-level xGoal on unblocked attempts. The NHL box score matches the goalie game log, not the shot zip, so the model keeps the NHL counts.

## What changed in the pipeline

- Frozen calls now add the same rolling bias the page adds before they price a line, so the logged projection is the one on the slate.
- A DailyFaceoff starter who is Likely or otherwise not confirmed is the projected starter (still not a play), ahead of the back-to-back backup, matching the page.
- The build loads MoneyPuck goalie games, cross-checks shots, saves and time on ice, and raises if they disagree or if both the download and the committed snapshot are missing.

