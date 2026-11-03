# Audit backtest: before / after

Built 2026-11-03 15:43 UTC by `python model/backtest_audit.py`. Seasons: 2024-25, 2025-26, 2026-27 (every player-game, walk-forward), plus this season's real graded lines.

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

**2026-27** (8459 player-games; tiers F [8.0, 7.5, 9.0, 5.0], D [14.0, 17.5, 7.0, 7.0])

| | log-lik | PIT max deviation | P(≥1) | P(≥2) | P(≥3) | P(≥4) |
|---|---|---|---|---|---|---|
| old | -1.51820 | 0.52 pts | 72.7% / 72.4% | 42.4% / 41.6% | 21.5% / 21.2% | 10.0% / 9.6% |
| new | -1.51820 | 0.51 pts | 72.6% / 72.4% | 42.3% / 41.6% | 21.5% / 21.2% | 10.0% / 9.6% |

PIT deciles (new): 10.4, 10.2, 10.1, 10.3, 10.5, 9.5, 9.8, 9.7, 9.9, 9.7

By projection tier (new; predicted / actual):

| tier | n | P(≥1) | P(≥2) | P(≥3) | P(≥4) |
|---|---|---|---|---|---|
| < 1.5 | 4766 | 62.8% / 62.7% | 28.7% / 28.6% | 10.6% / 10.6% | 3.4% / 3.5% |
| 1.5-2.5 | 2834 | 82.9% / 81.9% | 54.8% / 52.2% | 29.8% / 28.9% | 13.9% / 12.7% |
| 2.5-3.5 | 764 | 93.0% / 94.2% | 75.7% / 78.4% | 53.0% / 52.7% | 32.2% / 31.0% |
| 3.5+ | 95 | 96.6% / 97.9% | 86.0% / 85.3% | 68.9% / 68.4% | 49.5% / 49.5% |

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
| 2026-27 | More | 0.5 | 4102 | 64.3% | 64.4% | +0.1 |
| 2026-27 | Less | 0.5 | 478 | 55.3% | 55.6% | +0.3 |
| 2026-27 | More | 1.5 | 2318 | 61.1% | 59.0% | -2.1 |
| 2026-27 | Less | 1.5 | 4041 | 63.3% | 63.7% | +0.4 |
| 2026-27 | More | 2.5 | 513 | 59.5% | 62.6% | +3.0 |
| 2026-27 | Less | 2.5 | 2275 | 64.5% | 66.4% | +1.8 |
| 2026-27 | More | 3.5+ | 31 | 53.4% | 58.1% | +4.7 |
| 2026-27 | Less | 3.5+ | 807 | 66.4% | 67.4% | +1.0 |

### Real graded DraftKings lines, this season, walk-forward

**saves**: 358 lines 2026-10-01 to 2026-11-01. Model weight in the blend **0.0** (log-loss fit 0.0, shrink 1.0, walk-forward (237 lines)); side-split slopes b 0.9003 / b_under 0.7971; per-line intercepts not used (no walk-forward gain).

| probability | n | Brier | log loss |
|---|---|---|---|
| raw model | 237 | 0.25549 | 0.7048 |
| calibrated model | 237 | 0.25575 | 0.70535 |
| DK no-vig | 237 | 0.25064 | 0.69443 |
| blend 0.6 (old) | 237 | 0.25256 | 0.69838 |
| blend fitted (new) | 237 | 0.25522 | 0.70413 |
| blend fitted + line intercepts | 237 | 0.25723 | 0.70848 |

Reliability, raw:

| side | line | n | predicted | actual | gap | ±3 pts (n ≥ 200) |
|---|---|---|---|---|---|---|
| More | 3.5+ | 69 | 53.8% | 56.5% | +2.7 | n < 200 |
| Less | 3.5+ | 168 | 57.1% | 53.6% | -3.5 | n < 200 |

Reliability, final:

| side | line | n | predicted | actual | gap | ±3 pts (n ≥ 200) |
|---|---|---|---|---|---|---|
| More | 3.5+ | 70 | 53.2% | 54.3% | +1.1 | n < 200 |
| Less | 3.5+ | 167 | 55.9% | 52.7% | -3.2 | n < 200 |

Model's side where it and DK no-vig disagree (walk-forward): 56-33 (62.9%), against a 57.7% 1x break-even.

**sog**: 3528 lines 2026-10-01 to 2026-11-01. Model weight in the blend **0.0** (log-loss fit 0.4, shrink 0.0, walk-forward (3009 lines)); side-split slopes b 0.6379 / b_under 0.6742; per-line intercepts not used (no walk-forward gain).

| probability | n | Brier | log loss |
|---|---|---|---|
| raw model | 3009 | 0.24779 | 0.68876 |
| calibrated model | 3009 | 0.24716 | 0.6874 |
| DK no-vig | 3009 | 0.24676 | 0.68664 |
| blend 0.6 (old) | 3009 | 0.24659 | 0.68627 |
| blend fitted (new) | 3009 | 0.24654 | 0.68617 |
| blend fitted + line intercepts | 3009 | 0.24663 | 0.68635 |

Reliability, raw:

| side | line | n | predicted | actual | gap | ±3 pts (n ≥ 200) |
|---|---|---|---|---|---|---|
| More | 0.5 | 6 | 64.9% | 83.3% | +18.4 | n < 200 |
| More | 1.5 | 901 | 56.4% | 51.9% | -4.4 | ✗ |
| More | 2.5 | 225 | 55.5% | 55.6% | +0.1 | ✓ |
| More | 3.5+ | 21 | 53.0% | 57.1% | +4.1 | n < 200 |
| Less | 1.5 | 911 | 57.4% | 53.5% | -3.9 | ✗ |
| Less | 2.5 | 776 | 58.4% | 58.0% | -0.4 | ✓ |
| Less | 3.5+ | 169 | 57.5% | 55.6% | -1.9 | n < 200 |

Reliability, final:

| side | line | n | predicted | actual | gap | ±3 pts (n ≥ 200) |
|---|---|---|---|---|---|---|
| More | 0.5 | 6 | 64.0% | 83.3% | +19.4 | n < 200 |
| More | 1.5 | 1056 | 55.3% | 52.6% | -2.7 | ✓ |
| More | 2.5 | 251 | 54.3% | 51.4% | -2.9 | ✓ |
| More | 3.5+ | 26 | 52.9% | 57.7% | +4.7 | n < 200 |
| Less | 1.5 | 756 | 55.0% | 55.4% | +0.4 | ✓ |
| Less | 2.5 | 750 | 56.4% | 57.1% | +0.7 | ✓ |
| Less | 3.5+ | 164 | 55.7% | 56.1% | +0.4 | n < 200 |

Model's side where it and DK no-vig disagree (walk-forward): 265-272 (49.4%), against a 57.7% 1x break-even.

**points**: 488 lines 2026-10-29 to 2026-11-01. Model weight in the blend **0.75** (log-loss fit 0.75, shrink 1.0, in-sample (488 lines; walk-forward needs 200)); side-split slopes b 1.25 / b_under 0.9516; per-line intercepts not used (no walk-forward gain).

| probability | n | Brier | log loss |
|---|---|---|---|
| raw model | 0 | – | – |
| calibrated model | 0 | – | – |
| DK no-vig | 0 | – | – |
| blend 0.6 (old) | 0 | – | – |
| blend fitted (new) | 0 | – | – |
| blend fitted + line intercepts | 0 | – | – |

Reliability, raw:

| side | line | n | predicted | actual | gap | ±3 pts (n ≥ 200) |
|---|---|---|---|---|---|---|

Reliability, final:

| side | line | n | predicted | actual | gap | ±3 pts (n ≥ 200) |
|---|---|---|---|---|---|---|

Model's side where it and DK no-vig disagree (walk-forward): 0-0 (–), against a 57.7% 1x break-even.

## 3. Rule-passing legs on real lines (items 3 and 9)

Every graded DK line priced as a 1x DFS leg. New = TAKE rule (blended p ≥ 58% with the fitted weight, beats break-even, model alone agrees). Old = calibrated model blended 60/40 at p ≥ 58%.

| market | rule | legs | record | hit % | units (1x, 2-pick 3x) |
|---|---|---|---|---|---|
| sog | old | 584 | 345-239 | 59.1% | +13.56 |
| sog | old, MORE | 171 | 99-72 | 57.9% | +0.47 |
| sog | old, LESS | 413 | 246-167 | 59.6% | +13.08 |
| sog | new | 735 | 434-301 | 59.0% | +16.71 |
| sog | new, MORE | 282 | 161-121 | 57.1% | -3.14 |
| sog | new, LESS | 453 | 273-180 | 60.3% | +19.85 |
| points | old | 0 | 0-0 | – | +0.00 |
| points | old, MORE | 0 | 0-0 | – | +0.00 |
| points | old, LESS | 0 | 0-0 | – | +0.00 |
| points | new | 0 | 0-0 | – | +0.00 |
| points | new, MORE | 0 | 0-0 | – | +0.00 |
| points | new, LESS | 0 | 0-0 | – | +0.00 |

## 4. Saves (items 6 and 11)

Rolling bias correction (30-day half-life, shrunk by 20 starts), last 30 days (402 starts): mean actual − projected **-0.21 → +0.01** saves (MAE 5.15 → 5.15).

Real lines: 370 goalie-nights (DraftKings 348, PrizePicks 20, Pick6 1, user quote 1).

| projection | side | n | predicted | actual |
|---|---|---|---|---|
| before | OVER | 112 | 54.7% | 54.5% |
| before | UNDER | 258 | 57.5% | 58.5% |
| bias-corrected | OVER | 96 | 54.1% | 53.1% |
| bias-corrected | UNDER | 274 | 58.5% | 57.3% |

Record and ROI by edge threshold (projection − line in the pick direction; DK lines at their price, DFS at the 1x break-even):

| projection | edge | side | n | record | hit % | units | ROI |
|---|---|---|---|---|---|---|---|
| before | 1.5 | OVER | 18 | 8-10 | 44.4% | -3.36 | -18.7% |
| before | 1.5 | UNDER | 88 | 51-37 | 58.0% | +4.59 | 5.2% |
| before | 2.0 | OVER | 6 | 2-4 | 33.3% | -2.18 | -36.4% |
| before | 2.0 | UNDER | 50 | 27-23 | 54.0% | -0.94 | -1.9% |
| before | 2.5 | OVER | 2 | 1-1 | 50.0% | -0.09 | -4.5% |
| before | 2.5 | UNDER | 19 | 9-10 | 47.4% | -2.82 | -14.8% |
| before | 3.0 | OVER | 1 | 1-0 | 100.0% | +0.91 | 90.9% |
| before | 3.0 | UNDER | 9 | 5-4 | 55.6% | +0.07 | 0.8% |
| bias-corrected | 1.5 | OVER | 11 | 3-8 | 27.3% | -5.23 | -47.5% |
| bias-corrected | 1.5 | UNDER | 112 | 66-46 | 58.9% | +8.07 | 7.2% |
| bias-corrected | 2.0 | OVER | 3 | 1-2 | 33.3% | -1.09 | -36.4% |
| bias-corrected | 2.0 | UNDER | 67 | 37-30 | 55.2% | +0.28 | 0.4% |
| bias-corrected | 2.5 | OVER | 2 | 1-1 | 50.0% | -0.09 | -4.5% |
| bias-corrected | 2.5 | UNDER | 37 | 19-18 | 51.4% | -2.55 | -6.9% |
| bias-corrected | 3.0 | OVER | 0 | 0-0 | – | +0.00 | – |
| bias-corrected | 3.0 | UNDER | 18 | 9-9 | 50.0% | -1.65 | -9.2% |

## 5. Role changes (item 5)

Not measurable yet: there is no history of pre-game line combinations, so the role-change subset can't be backtested. From this build on every displayed leg is logged with its role-change tag (model/data/legs.csv), and the Results tab will show that subset once it grades.

