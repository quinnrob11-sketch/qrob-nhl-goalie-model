# Audit backtest: before / after

Built 2026-11-08 08:35 UTC by `python model/backtest_audit.py`. Seasons: 2024-25, 2025-26, 2026-27 (every player-game, walk-forward), plus this season's real graded lines.

## 1. Shots distribution (item 4): dispersion by position and volume tier

Randomized PIT deciles should each hold 10%; P(shots ≥ k) predicted vs actual. Old = one disp_k (size = 10 × mean); new = disp_k per position and projection tier, fitted on earlier seasons only.

**2025-26** (47230 player-games; tiers F [8.0, 8.0, 9.0, 5.0], D [11.5, 17.0, 5.5, 5.5])

| | log-lik | PIT max deviation | P(≥1) | P(≥2) | P(≥3) | P(≥4) |
|---|---|---|---|---|---|---|
| old | -1.53303 | 0.24 pts | 72.8% / 72.8% | 42.6% / 42.5% | 21.8% / 21.7% | 10.1% / 10.1% |
| new | -1.53283 | 0.19 pts | 72.6% / 72.8% | 42.5% / 42.5% | 21.8% / 21.7% | 10.2% / 10.1% |

PIT deciles (new): 10.2, 9.8, 9.9, 10.0, 9.9, 10.1, 10.0, 10.2, 10.0, 10.0

By projection tier (new; predicted / actual):

| tier | n | P(≥1) | P(≥2) | P(≥3) | P(≥4) |
|---|---|---|---|---|---|
| < 1.5 | 26445 | 62.4% / 62.7% | 28.5% / 28.3% | 10.5% / 10.3% | 3.4% / 3.2% |
| 1.5-2.5 | 16115 | 83.4% / 83.4% | 55.6% / 55.7% | 30.5% / 30.6% | 14.3% / 14.5% |
| 2.5-3.5 | 4180 | 93.1% / 93.0% | 76.0% / 76.3% | 53.4% / 53.8% | 32.6% / 32.1% |
| 3.5+ | 490 | 96.8% / 96.3% | 86.7% / 86.3% | 70.1% / 69.0% | 50.9% / 50.8% |

**2026-27** (9503 player-games; tiers F [8.0, 7.5, 9.0, 5.0], D [14.0, 17.5, 7.0, 7.0])

| | log-lik | PIT max deviation | P(≥1) | P(≥2) | P(≥3) | P(≥4) |
|---|---|---|---|---|---|---|
| old | -1.51862 | 0.49 pts | 72.7% / 72.5% | 42.4% / 41.6% | 21.5% / 21.4% | 9.9% / 9.6% |
| new | -1.51860 | 0.32 pts | 72.6% / 72.5% | 42.3% / 41.6% | 21.5% / 21.4% | 10.0% / 9.6% |

PIT deciles (new): 10.1, 10.2, 10.1, 10.2, 10.0, 10.0, 9.7, 10.1, 10.1, 9.7

By projection tier (new; predicted / actual):

| tier | n | P(≥1) | P(≥2) | P(≥3) | P(≥4) |
|---|---|---|---|---|---|
| < 1.5 | 5356 | 62.7% / 62.9% | 28.7% / 28.6% | 10.6% / 10.6% | 3.4% / 3.5% |
| 1.5-2.5 | 3189 | 82.9% / 82.0% | 54.7% / 52.2% | 29.8% / 29.2% | 13.8% / 12.7% |
| 2.5-3.5 | 848 | 93.0% / 94.1% | 75.7% / 77.8% | 53.0% / 53.1% | 32.2% / 31.4% |
| 3.5+ | 110 | 96.6% / 98.2% | 86.0% / 85.5% | 68.8% / 70.0% | 49.3% / 50.9% |

## 2. Calibration by side and line (item 2)

### Every player-game, book-style lines (model P(over) 25-75%)

| season | side | line | n | predicted | actual | gap |
|---|---|---|---|---|---|---|
| 2024-25 | More | 0.5 | 21733 | 64.3% | 64.2% | -0.2 |
| 2024-25 | Less | 0.5 | 2422 | 56.3% | 54.3% | -2.0 |
| 2024-25 | More | 1.5 | 14007 | 61.1% | 60.9% | -0.2 |
| 2024-25 | Less | 1.5 | 21518 | 63.4% | 64.5% | +1.0 |
| 2024-25 | More | 2.5 | 3576 | 58.6% | 56.3% | -2.2 |
| 2024-25 | Less | 2.5 | 13656 | 64.6% | 65.2% | +0.5 |
| 2024-25 | More | 3.5+ | 396 | 56.1% | 50.5% | -5.6 |
| 2024-25 | Less | 3.5+ | 4982 | 66.6% | 69.0% | +2.4 |
| 2025-26 | More | 0.5 | 22508 | 64.2% | 64.1% | -0.2 |
| 2025-26 | Less | 0.5 | 2916 | 55.4% | 52.0% | -3.4 |
| 2025-26 | More | 1.5 | 13433 | 61.0% | 61.3% | +0.4 |
| 2025-26 | Less | 1.5 | 21730 | 63.6% | 64.0% | +0.4 |
| 2025-26 | More | 2.5 | 3112 | 58.4% | 58.5% | +0.1 |
| 2025-26 | Less | 2.5 | 13071 | 64.7% | 64.3% | -0.4 |
| 2025-26 | More | 3.5+ | 217 | 55.3% | 52.1% | -3.2 |
| 2025-26 | Less | 3.5+ | 4364 | 66.3% | 66.6% | +0.2 |
| 2026-27 | More | 0.5 | 4617 | 64.3% | 64.6% | +0.3 |
| 2026-27 | Less | 0.5 | 536 | 55.4% | 55.6% | +0.2 |
| 2026-27 | More | 1.5 | 2594 | 61.0% | 58.8% | -2.2 |
| 2026-27 | Less | 1.5 | 4535 | 63.3% | 63.7% | +0.5 |
| 2026-27 | More | 2.5 | 579 | 59.5% | 63.2% | +3.7 |
| 2026-27 | Less | 2.5 | 2541 | 64.6% | 66.2% | +1.7 |
| 2026-27 | More | 3.5+ | 36 | 53.2% | 58.3% | +5.1 |
| 2026-27 | Less | 3.5+ | 898 | 66.4% | 66.8% | +0.5 |

### Real graded DraftKings lines, this season, walk-forward

**saves**: 418 lines 2026-10-01 to 2026-11-06. Model weight in the blend **0.047** (log-loss fit 0.05, shrink 0.939, walk-forward (297 lines)); side-split slopes b 0.9026 / b_under 0.8172; per-line intercepts not used (no walk-forward gain).

| probability | n | Brier | log loss |
|---|---|---|---|
| raw model | 297 | 0.25362 | 0.70097 |
| calibrated model | 297 | 0.25404 | 0.70192 |
| DK no-vig | 297 | 0.24945 | 0.69205 |
| blend 0.6 (old) | 297 | 0.25092 | 0.69509 |
| blend fitted (new) | 297 | 0.24946 | 0.69207 |
| blend fitted + line intercepts | 297 | 0.2495 | 0.69215 |

Reliability, raw:

| side | line | n | predicted | actual | gap | ±3 pts (n ≥ 200) |
|---|---|---|---|---|---|---|
| More | 3.5+ | 89 | 54.1% | 58.4% | +4.3 | n < 200 |
| Less | 3.5+ | 208 | 57.2% | 52.4% | -4.8 | ✗ |

Reliability, final:

| side | line | n | predicted | actual | gap | ±3 pts (n ≥ 200) |
|---|---|---|---|---|---|---|
| More | 3.5+ | 114 | 51.6% | 50.9% | -0.8 | n < 200 |
| Less | 3.5+ | 183 | 51.6% | 49.2% | -2.4 | n < 200 |

Model's side where it and DK no-vig disagree (walk-forward): 71-53 (57.3%), against a 57.7% 1x break-even.

**sog**: 4070 lines 2026-10-01 to 2026-11-06. Model weight in the blend **0.0** (log-loss fit 0.35, shrink 0.0, walk-forward (3551 lines)); side-split slopes b 0.6672 / b_under 0.6865; per-line intercepts not used (no walk-forward gain).

| probability | n | Brier | log loss |
|---|---|---|---|
| raw model | 3551 | 0.24745 | 0.68806 |
| calibrated model | 3551 | 0.2469 | 0.68689 |
| DK no-vig | 3551 | 0.24641 | 0.68592 |
| blend 0.6 (old) | 3551 | 0.24632 | 0.68571 |
| blend fitted (new) | 3551 | 0.24642 | 0.68594 |
| blend fitted + line intercepts | 3551 | 0.24642 | 0.68594 |

Reliability, raw:

| side | line | n | predicted | actual | gap | ±3 pts (n ≥ 200) |
|---|---|---|---|---|---|---|
| More | 0.5 | 6 | 64.9% | 83.3% | +18.4 | n < 200 |
| More | 1.5 | 1059 | 56.3% | 51.8% | -4.5 | ✗ |
| More | 2.5 | 265 | 55.4% | 57.0% | +1.6 | ✓ |
| More | 3.5+ | 28 | 53.0% | 53.6% | +0.6 | n < 200 |
| Less | 1.5 | 1094 | 57.3% | 54.1% | -3.1 | ✗ |
| Less | 2.5 | 903 | 58.4% | 57.8% | -0.6 | ✓ |
| Less | 3.5+ | 196 | 57.5% | 54.6% | -2.9 | n < 200 |

Reliability, final:

| side | line | n | predicted | actual | gap | ±3 pts (n ≥ 200) |
|---|---|---|---|---|---|---|
| More | 0.5 | 6 | 63.4% | 83.3% | +19.9 | n < 200 |
| More | 1.5 | 1269 | 55.3% | 52.6% | -2.7 | ✓ |
| More | 2.5 | 314 | 54.1% | 53.8% | -0.3 | ✓ |
| More | 3.5+ | 41 | 53.0% | 53.7% | +0.7 | n < 200 |
| Less | 1.5 | 884 | 54.8% | 56.6% | +1.7 | ✓ |
| Less | 2.5 | 854 | 56.4% | 57.5% | +1.1 | ✓ |
| Less | 3.5+ | 183 | 55.6% | 55.2% | -0.5 | n < 200 |

Model's side where it and DK no-vig disagree (walk-forward): 310-321 (49.1%), against a 57.7% 1x break-even.

**points**: 1123 lines 2026-10-29 to 2026-11-06. Model weight in the blend **0.4** (log-loss fit 0.4, shrink 1.0, walk-forward (635 lines)); side-split slopes b 1.25 / b_under 0.9139; per-line intercepts not used (no walk-forward gain).

| probability | n | Brier | log loss |
|---|---|---|---|
| raw model | 635 | 0.2326 | 0.65764 |
| calibrated model | 635 | 0.23202 | 0.6564 |
| DK no-vig | 635 | 0.23147 | 0.65545 |
| blend 0.6 (old) | 635 | 0.23131 | 0.65494 |
| blend fitted (new) | 635 | 0.23121 | 0.6548 |
| blend fitted + line intercepts | 635 | 0.23135 | 0.65508 |

Reliability, raw:

| side | line | n | predicted | actual | gap | ±3 pts (n ≥ 200) |
|---|---|---|---|---|---|---|
| More | 0.5 | 177 | 57.5% | 61.6% | +4.1 | n < 200 |
| More | 1.5 | 3 | 53.2% | 33.3% | -19.8 | n < 200 |
| Less | 0.5 | 422 | 62.3% | 63.5% | +1.2 | ✓ |
| Less | 1.5 | 33 | 65.8% | 48.5% | -17.3 | n < 200 |

Reliability, final:

| side | line | n | predicted | actual | gap | ±3 pts (n ≥ 200) |
|---|---|---|---|---|---|---|
| More | 0.5 | 195 | 58.0% | 59.5% | +1.5 | n < 200 |
| More | 1.5 | 3 | 52.8% | 66.7% | +13.8 | n < 200 |
| Less | 0.5 | 404 | 61.1% | 63.6% | +2.5 | ✓ |
| Less | 1.5 | 33 | 62.2% | 51.5% | -10.7 | n < 200 |

Model's side where it and DK no-vig disagree (walk-forward): 30-29 (50.8%), against a 57.7% 1x break-even.

## 3. Rule-passing legs on real lines (items 3 and 9)

Walk-forward on every graded DK line with a pre-game price. New = the live TAKE rule (market support, blended p over the bar, model agrees) choosing as if the side were a 1x DFS leg. Old = calibrated model blended 60/40 at p ≥ 58%.
Each pick is settled three ways. **1x** is hypothetical: DFS boards discount exactly these sides (on Nov 3-8 Pick6 paid ≥1x on 0 sides DK priced at 54%+), so it overstates. **DK price** is DraftKings' own odds. **Real DFS** settles only the sides a Pick6-style board would offer at ≥ 1x, at that multiplier. ± is one standard error.

| market | rule | legs | record | hit % | units 1x (hypothetical) | ROI at DK price | real DFS legs | ROI real DFS |
|---|---|---|---|---|---|---|---|---|
| sog | old | 673 | 401-272 | 59.6% ± 1.9 | +21.55 | -6.5% ± 3.0 | 0 (0 hit) | – |
| sog | old, MORE | 197 | 117-80 | 59.4% ± 3.5 | +5.65 | -7.1% ± 5.5 | 0 (0 hit) | – |
| sog | old, LESS | 476 | 284-192 | 59.7% ± 2.3 | +15.90 | -6.2% ± 3.5 | 0 (0 hit) | – |
| sog | new | 833 | 491-342 | 58.9% ± 1.7 | +17.44 | -8.4% ± 2.7 | 0 (0 hit) | – |
| sog | new, MORE | 334 | 189-145 | 56.6% ± 2.7 | -6.64 | -11.9% ± 4.2 | 0 (0 hit) | – |
| sog | new, LESS | 499 | 302-197 | 60.5% ± 2.2 | +24.08 | -6.0% ± 3.4 | 0 (0 hit) | – |
| points | old | 381 | 254-127 | 66.7% ± 2.4 | +58.94 | -1.9% ± 3.6 | 0 (0 hit) | – |
| points | old, MORE | 89 | 62-27 | 69.7% ± 4.9 | +18.39 | 5.4% ± 7.4 | 0 (0 hit) | – |
| points | old, LESS | 292 | 192-100 | 65.8% ± 2.8 | +40.55 | -4.1% ± 4.1 | 0 (0 hit) | – |
| points | new | 357 | 243-114 | 68.1% ± 2.5 | +63.89 | -0.2% ± 3.7 | 0 (0 hit) | – |
| points | new, MORE | 92 | 64-28 | 69.6% ± 4.8 | +18.85 | 5.2% ± 7.3 | 0 (0 hit) | – |
| points | new, LESS | 265 | 179-86 | 67.5% ± 2.9 | +45.04 | -2.0% ± 4.2 | 0 (0 hit) | – |

## 4. Saves (items 6 and 11)

Rolling bias correction (30-day half-life, shrunk by 20 starts), last 30 days (418 starts): mean actual − projected **-0.14 → +0.08** saves (MAE 5.17 → 5.18).

Real lines: 430 goalie-nights (DraftKings 408, PrizePicks 19, Pick6 2, user quote 1).

| projection | side | n | predicted | actual |
|---|---|---|---|---|
| before | OVER | 133 | 54.9% | 54.1% |
| before | UNDER | 297 | 57.8% | 56.2% |
| bias-corrected | OVER | 110 | 54.6% | 52.7% |
| bias-corrected | UNDER | 320 | 58.6% | 55.0% |

Record and ROI by edge threshold (projection − line in the pick direction; DK lines at their price, DFS at the 1x break-even):

| projection | edge | side | n | record | hit % | units | ROI |
|---|---|---|---|---|---|---|---|
| before | 1.5 | OVER | 24 | 13-11 | 54.2% | -0.37 | -1.5% |
| before | 1.5 | UNDER | 96 | 60-36 | 62.5% | +13.27 | 13.8% |
| before | 2.0 | OVER | 10 | 5-5 | 50.0% | -0.63 | -6.3% |
| before | 2.0 | UNDER | 66 | 38-28 | 57.6% | +3.55 | 5.4% |
| before | 2.5 | OVER | 2 | 1-1 | 50.0% | -0.09 | -4.5% |
| before | 2.5 | UNDER | 28 | 14-14 | 50.0% | -2.67 | -9.5% |
| before | 3.0 | OVER | 2 | 1-1 | 50.0% | -0.09 | -4.5% |
| before | 3.0 | UNDER | 14 | 8-6 | 57.1% | +0.41 | 2.9% |
| bias-corrected | 1.5 | OVER | 16 | 8-8 | 50.0% | -1.36 | -8.5% |
| bias-corrected | 1.5 | UNDER | 130 | 80-50 | 61.5% | +15.97 | 12.3% |
| bias-corrected | 2.0 | OVER | 7 | 2-5 | 28.6% | -3.18 | -45.5% |
| bias-corrected | 2.0 | UNDER | 74 | 43-31 | 58.1% | +4.45 | 6.0% |
| bias-corrected | 2.5 | OVER | 2 | 1-1 | 50.0% | -0.09 | -4.5% |
| bias-corrected | 2.5 | UNDER | 46 | 27-19 | 58.7% | +3.47 | 7.6% |
| bias-corrected | 3.0 | OVER | 1 | 0-1 | 0.0% | -1.00 | -100.0% |
| bias-corrected | 3.0 | UNDER | 22 | 11-11 | 50.0% | -2.08 | -9.4% |

## 5. Role changes (item 5)

Not measurable yet: there is no history of pre-game line combinations, so the role-change subset can't be backtested. From this build on every displayed leg is logged with its role-change tag (model/data/legs.csv), and the Results tab will show that subset once it grades.

