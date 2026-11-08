# Audit backtest: before / after

Built 2026-11-08 13:25 UTC by `python model/backtest_audit.py`. Seasons: 2024-25, 2025-26, 2026-27 (every player-game), plus this season's real graded lines.

**Read sections 1-2 carefully:** the shipped shots parameters are fitted on 2025-26, so the 2024-25 and 2025-26 player-game rows are scored with parameters that saw 2025-26 (in-sample; an honest refit on 2024-25 alone shows a bias about 0.5 point larger at 1.5 / 2.5). Only the 2026-27 rows and the real-line sections are out of sample, with three exceptions chosen with this season's lines in view: the shots projection's design (attempt rate, two-scale ice time), the 50/50 mean-blend weight (the in-sample log-loss optimum; a weight chosen week by week on earlier weeks scores 0.68478 against DK's 0.68592 on the same lines) and the SOG rule's 62% / 55% bars (bars re-chosen each week from earlier weeks give the same record within one standard error).

## 1. Shots distribution (item 4): dispersion by position and volume tier

Randomized PIT deciles should each hold 10%; P(shots ≥ k) predicted vs actual. Old = one disp_k (size = 10 × mean); new = disp_k per position and projection tier, fitted on earlier seasons only.

**2025-26** (47230 player-games; tiers F [8.0, 9.0, 9.0, 5.0], D [13.0, 20.5, 4.5, 4.5])

| | log-lik | PIT max deviation | P(≥1) | P(≥2) | P(≥3) | P(≥4) |
|---|---|---|---|---|---|---|
| old | -1.53043 | 0.12 pts | 72.7% / 72.8% | 42.6% / 42.5% | 21.7% / 21.7% | 10.1% / 10.1% |
| new | -1.53024 | 0.29 pts | 72.7% / 72.8% | 42.5% / 42.5% | 21.7% / 21.7% | 10.1% / 10.1% |

PIT deciles (new): 10.2, 9.7, 10.0, 10.0, 9.9, 10.1, 10.0, 10.2, 9.9, 10.0

By projection tier (new; predicted / actual):

| tier | n | P(≥1) | P(≥2) | P(≥3) | P(≥4) |
|---|---|---|---|---|---|
| < 1.5 | 26561 | 62.4% / 62.5% | 28.4% / 28.2% | 10.5% / 10.3% | 3.3% / 3.2% |
| 1.5-2.5 | 15912 | 83.6% / 83.8% | 55.7% / 56.0% | 30.4% / 30.8% | 14.1% / 14.6% |
| 2.5-3.5 | 4236 | 93.1% / 92.9% | 76.0% / 76.3% | 53.5% / 53.4% | 32.7% / 31.7% |
| 3.5+ | 521 | 96.7% / 96.4% | 86.5% / 86.4% | 69.8% / 69.3% | 50.6% / 52.0% |

**2026-27** (9503 player-games; tiers F [8.5, 8.0, 9.0, 4.5], D [15.0, 23.5, 5.5, 5.5])

| | log-lik | PIT max deviation | P(≥1) | P(≥2) | P(≥3) | P(≥4) |
|---|---|---|---|---|---|---|
| old | -1.51640 | 0.87 pts | 72.4% / 72.5% | 42.1% / 41.6% | 21.4% / 21.4% | 9.9% / 9.6% |
| new | -1.51655 | 0.45 pts | 72.4% / 72.5% | 42.1% / 41.6% | 21.3% / 21.4% | 9.9% / 9.6% |

PIT deciles (new): 9.9, 10.4, 9.9, 10.0, 10.1, 9.8, 10.1, 9.8, 10.0, 9.9

By projection tier (new; predicted / actual):

| tier | n | P(≥1) | P(≥2) | P(≥3) | P(≥4) |
|---|---|---|---|---|---|
| < 1.5 | 5459 | 62.7% / 63.0% | 28.6% / 28.7% | 10.5% / 10.7% | 3.3% / 3.5% |
| 1.5-2.5 | 3058 | 83.0% / 82.3% | 54.9% / 52.6% | 29.8% / 29.3% | 13.8% / 12.9% |
| 2.5-3.5 | 866 | 93.1% / 93.9% | 75.7% / 77.0% | 53.1% / 53.0% | 32.3% / 30.7% |
| 3.5+ | 120 | 96.5% / 98.3% | 85.9% / 89.2% | 68.9% / 74.2% | 49.6% / 51.7% |

## 2. Calibration by side and line (item 2)

### Every player-game, book-style lines (model P(over) 25-75%)

| season | side | line | n | predicted | actual | gap |
|---|---|---|---|---|---|---|
| 2024-25 | More | 0.5 | 22050 | 64.3% | 64.1% | -0.2 |
| 2024-25 | Less | 0.5 | 2427 | 55.7% | 54.3% | -1.4 |
| 2024-25 | More | 1.5 | 13745 | 61.3% | 61.3% | +0.0 |
| 2024-25 | Less | 1.5 | 21662 | 63.5% | 63.9% | +0.3 |
| 2024-25 | More | 2.5 | 3597 | 58.4% | 56.3% | -2.1 |
| 2024-25 | Less | 2.5 | 13225 | 64.5% | 64.7% | +0.3 |
| 2024-25 | More | 3.5+ | 371 | 55.7% | 51.2% | -4.5 |
| 2024-25 | Less | 3.5+ | 5010 | 66.7% | 68.9% | +2.2 |
| 2025-26 | More | 0.5 | 22628 | 64.2% | 64.0% | -0.1 |
| 2025-26 | Less | 0.5 | 2804 | 55.3% | 53.0% | -2.2 |
| 2025-26 | More | 1.5 | 13229 | 61.2% | 61.6% | +0.4 |
| 2025-26 | Less | 1.5 | 21702 | 63.5% | 63.8% | +0.3 |
| 2025-26 | More | 2.5 | 3145 | 58.8% | 59.1% | +0.3 |
| 2025-26 | Less | 2.5 | 12777 | 64.5% | 64.0% | -0.5 |
| 2025-26 | More | 3.5+ | 216 | 54.9% | 51.4% | -3.5 |
| 2025-26 | Less | 3.5+ | 4465 | 66.2% | 66.8% | +0.6 |
| 2026-27 | More | 0.5 | 4691 | 64.3% | 64.8% | +0.5 |
| 2026-27 | Less | 0.5 | 560 | 55.4% | 56.8% | +1.4 |
| 2026-27 | More | 1.5 | 2528 | 61.1% | 59.3% | -1.8 |
| 2026-27 | Less | 1.5 | 4552 | 63.4% | 63.9% | +0.4 |
| 2026-27 | More | 2.5 | 606 | 59.6% | 62.0% | +2.4 |
| 2026-27 | Less | 2.5 | 2443 | 64.5% | 65.6% | +1.1 |
| 2026-27 | More | 3.5+ | 48 | 53.3% | 58.3% | +5.0 |
| 2026-27 | Less | 3.5+ | 917 | 66.4% | 67.7% | +1.4 |

### Real graded DraftKings lines, this season, walk-forward (SOG's 'mean blend 50/50 (live)' row: weight chosen on these lines)

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

Reliability, final = the board's probability (the fitted blend):

| side | line | n | predicted | actual | gap | ±3 pts (n ≥ 200) |
|---|---|---|---|---|---|---|
| More | 3.5+ | 114 | 51.6% | 50.9% | -0.8 | n < 200 |
| Less | 3.5+ | 183 | 51.6% | 49.2% | -2.4 | n < 200 |

Model's side where it and DK no-vig disagree (walk-forward): 71-53 (57.3%), against a 57.7% 1x break-even.

**sog**: 4070 lines 2026-10-01 to 2026-11-06. Model weight in the blend **0.14** (log-loss fit 0.55, shrink 0.255, walk-forward (3551 lines)); side-split slopes b 0.7136 / b_under 0.749; per-line intercepts not used (no walk-forward gain).

| probability | n | Brier | log loss |
|---|---|---|---|
| raw model | 3551 | 0.24649 | 0.68612 |
| calibrated model | 3551 | 0.24627 | 0.68562 |
| DK no-vig | 3551 | 0.24641 | 0.68592 |
| blend 0.6 (old) | 3551 | 0.24593 | 0.68492 |
| blend fitted (new) | 3551 | 0.24638 | 0.68586 |
| blend fitted + line intercepts | 3551 | 0.24638 | 0.68586 |
| mean blend 50/50 (live) | 3551 | 0.24576 | 0.68458 |

Reliability, raw:

| side | line | n | predicted | actual | gap | ±3 pts (n ≥ 200) |
|---|---|---|---|---|---|---|
| More | 0.5 | 6 | 65.6% | 83.3% | +17.7 | n < 200 |
| More | 1.5 | 1043 | 56.2% | 53.3% | -2.9 | ✓ |
| More | 2.5 | 284 | 55.8% | 57.4% | +1.6 | ✓ |
| More | 3.5+ | 39 | 53.3% | 53.8% | +0.6 | n < 200 |
| Less | 1.5 | 1110 | 57.3% | 55.4% | -1.9 | ✓ |
| Less | 2.5 | 884 | 58.5% | 58.3% | -0.2 | ✓ |
| Less | 3.5+ | 185 | 57.7% | 55.1% | -2.5 | n < 200 |

Reliability, final = the board's probability (the 50/50 mean blend):

| side | line | n | predicted | actual | gap | ±3 pts (n ≥ 200) |
|---|---|---|---|---|---|---|
| More | 0.5 | 6 | 64.5% | 83.3% | +18.8 | n < 200 |
| More | 1.5 | 1134 | 55.6% | 52.2% | -3.4 | ✗ |
| More | 2.5 | 294 | 54.8% | 55.4% | +0.7 | ✓ |
| More | 3.5+ | 37 | 53.0% | 54.0% | +1.1 | n < 200 |
| Less | 1.5 | 1019 | 55.7% | 55.0% | -0.7 | ✓ |
| Less | 2.5 | 874 | 57.3% | 57.8% | +0.5 | ✓ |
| Less | 3.5+ | 187 | 56.5% | 55.1% | -1.4 | n < 200 |

Model's side where it and DK no-vig disagree (walk-forward): 330-305 (52.0%), against a 57.7% 1x break-even.

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

Reliability, final = the board's probability (the fitted blend):

| side | line | n | predicted | actual | gap | ±3 pts (n ≥ 200) |
|---|---|---|---|---|---|---|
| More | 0.5 | 195 | 58.0% | 59.5% | +1.5 | n < 200 |
| More | 1.5 | 3 | 52.8% | 66.7% | +13.8 | n < 200 |
| Less | 0.5 | 404 | 61.1% | 63.6% | +2.5 | ✓ |
| Less | 1.5 | 33 | 62.2% | 51.5% | -10.7 | n < 200 |

Model's side where it and DK no-vig disagree (walk-forward): 30-29 (50.8%), against a 57.7% 1x break-even.

## 3. Rule-passing legs on real lines (items 3 and 9)

Walk-forward on every DK line the tracker logged with a pre-game price (one line per player and date: the line in the last pre-game call; an independent recompute on every DK quote, 4,358 SOG lines, gives the same SOG record within one standard error). New = the live TAKE rule choosing as if the side were a 1x DFS leg: market support (its own side ≥ 55%) and blended p over the bar (SOG: the 50/50 mean blend at ≥ 62%, no model-agrees check; its bars were chosen on these dates, so SOG 'new' is in-sample for the bars; points: the fitted blend at ≥ 58%, model agrees). Old = calibrated model blended 60/40 at p ≥ 58%. Both rules on the same warm weeks.
Each pick is settled three ways. **1x** is hypothetical: DFS boards discount exactly these sides (on Nov 3-8 Pick6 paid ≥1x on 0 sides DK priced at 54%+), so it overstates. **DK price** is DraftKings' own odds. **Real DFS** settles only the sides a Pick6-style board would offer at ≥ 1x, at that multiplier, using the measured map (DK no-vig under 50%: 1.00x, 50-54%: 0.94x, 54%+: 0.8x). A rule that needs the market's side at 55%+ therefore has 0 real DFS legs by construction; the data agrees (of 1,999 graded Pick6 SOG legs, none qualified at ≥ 1x). ± is one standard error.

| market | rule | legs | record | hit % | units 1x (hypothetical) | ROI at DK price | real DFS legs | ROI real DFS |
|---|---|---|---|---|---|---|---|---|
| sog | old | 711 | 433-278 | 60.9% ± 1.8 | +38.98 | -4.1% ± 2.9 | 0 (0 hit) | – |
| sog | old, MORE | 197 | 117-80 | 59.4% ± 3.5 | +5.65 | -7.2% ± 5.5 | 0 (0 hit) | – |
| sog | old, LESS | 514 | 316-198 | 61.5% ± 2.1 | +33.33 | -2.9% ± 3.4 | 0 (0 hit) | – |
| sog | new | 270 | 179-91 | 66.3% ± 2.9 | +40.04 | 2.4% ± 4.5 | 0 (0 hit) | – |
| sog | new, MORE | 60 | 38-22 | 63.3% ± 6.3 | +5.82 | -2.6% ± 9.7 | 0 (0 hit) | – |
| sog | new, LESS | 210 | 141-69 | 67.1% ± 3.2 | +34.22 | 3.8% ± 5.0 | 0 (0 hit) | – |
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

