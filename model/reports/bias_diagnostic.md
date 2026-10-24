# Bias diagnostic: why the board leans UNDER

Step 1 of the audit. This is a report only; no model code changed in this commit. Data: every graded real line through 2026-10-23, de-duplicated the way the tracker does it (one row per date + market + player + team, Pick6 > PrizePicks > quote > DraftKings), the nightly snapshots in `model/data/calls/`, and the walk-forward engine re-run on 2023-24 through 2026-27.

## Root cause, in plain words

1. **The saves calibration is the main reason almost every new-rule saves play is an UNDER (144 of 158).** The Platt fit (a = -0.083, b = 0.33, from only 257 lines) shrinks the model's opinion to a third of its size and then subtracts about 2 points: a raw 50% over becomes 47.9%, and a raw 60% over becomes only 51.3%. After that, the side with the cheaper break-even nearly always wins, and the intercept tips it to the under. On so few lines the intercept is mostly noise, but it decides the side on almost every line.
2. **The big saves "edges" were mostly model misses.** Played unders were projected 2.25 saves below the line but finished only 0.90 below it, so the projection was 1.35 saves too low. Unders where the model disagreed only a little (0 to 1 save below the line) hit 64-66%. Unders with a 1.5+ gap, the ones that became plays, hit 46-56%. That is why passed unders (68-49) beat played unders (38-34): the market leans under on its own (lines sit about 0.6 above the final saves), and a big gap mostly means the model's shot count was too low, not that the price was wrong.
3. **Shots against were too low on the recent nights, not on the season.** For the current walk-forward model, mean (exp_SA - faced) is +0.07 over all 2026-27 starts, but -1.15 on Oct 15, -1.32 on Oct 20 and -1.00 on Oct 22. Team shot volume has moved up since opening week, and the team form the model uses (half-life 20 games, carrying 35% of last season) is slow to follow. The game-script term is too weak: underdogs are under-projected (-0.4 to -0.6 shots), favourites over-projected (+0.4 to +0.9), and a refit gives gs = 0.030 vs 0.015 in production. Projected save % (0.900) is 0.008 above actual (0.892) and hides part of the shot shortfall in the saves number.
4. **SOG leans under because of discreteness and too much regression at the top end.** With a negative binomial, P(under) is 56.8% at a 1.5 line and 55.6% at a 2.5 line even when the projection equals the line exactly. So "no opinion" reads as a 1-2 point under edge. On 2.5 and 3.5 lines the model also projects 0.10 and 0.44 shots below what players actually take. High-volume shooters get pulled toward the mean too hard, and 89% / 98% of those sides come out UNDER. Projected TOI is fine overall (+0.14 min); PP1 players are slightly under-projected (-0.3 to -0.4 min).
5. **SOG plays beat SOG passes on hit rate but not on price.** Played unders hit 58.5% vs 51.0% for passed unders, but at a median price of -150 (60.0% break-even) vs -115. The model finds the right side but pays too much for it.

What the fixes target: a shots-against baseline that follows recent form (step 2); a fitted spread (step 3); a saves calibration that can't run on an intercept, blended with the market (step 4); a SOG margin plus a rule that the projection must actually disagree with the line (step 5); and an alarm whenever one side takes over the board (step 6).

## Numbers behind the headline

**New-rule walk-forward replay (calibration.json before this audit), DraftKings lines with both prices:**

| market | lines | plays | OVER plays | UNDER plays | UNDER share | plays record | blind UNDER |
|---|---|---|---|---|---|---|---|
| saves | 257 | 158 | 14 (8-6, +1.41u) | 144 (80-64, +4.75u) | 91.1% | 88-70, +6.16u, ROI +3.9% | 138-119, -0.60u |
| SOG | 2506 | 445 | 24 (16-8, +6.80u) | 421 (226-195, +13.29u) | 94.6% | 242-203, +20.09u, ROI +4.5% | 1317-1189, -81.91u |

**Calibration intercept effect (saves, a = -0.083, b = 0.33):**

| raw P(over) | calibrated P(over) | shift |
|---|---|---|
| 40% | 44.6% | +4.6 |
| 50% | 47.9% | -2.1 |
| 55% | 49.6% | -5.4 |
| 60% | 51.3% | -8.7 |
| 65% | 53.0% | -12.0 |

**Played vs passed, by side (graded real lines as logged):**

| market | side | set | n | hit | proj - line | actual - line | median price | avg calibrated p(side) |
|---|---|---|---|---|---|---|---|---|
| saves | OVER | play | 12 | 58.3% | +2.14 | -0.92 | -115 | 52.0% |
| saves | OVER | PASS | 82 | 50.0% | +0.61 | +0.21 | -120 | 49.1% |
| saves | UNDER | play | 72 | 52.8% | -2.25 | -0.90 | -120 | 56.3% |
| saves | UNDER | PASS | 117 | 58.1% | -0.78 | -1.06 | -120 | 53.6% |
| SOG | OVER | play | 378 | 56.6% | +0.58 | +0.51 | -165 | 56.2% |
| SOG | OVER | PASS | 463 | 52.3% | +0.32 | +0.34 | -135 | 51.8% |
| SOG | UNDER | play | 1153 | 58.5% | -0.20 | -0.10 | -150 | 57.4% |
| SOG | UNDER | PASS | 557 | 51.0% | +0.10 | +0.17 | -115 | 52.1% |

Saves UNDER hit rate by how far the projection sat below the line:

| line - proj | n | hit | share played |
|---|---|---|---|
| <= 0 | 8 | 25.0% | 12.5% |
| 0 to 0.5 | 32 | 65.6% | 0% |
| 0.5 to 1.0 | 36 | 63.9% | 2.8% |
| 1.0 to 1.5 | 41 | 53.7% | 2.4% |
| 1.5 to 2.5 | 48 | 56.3% | 95.8% |
| 2.5+ | 24 | 45.8% | 95.8% |

Nearly all of these rows were picked under the old rule (play = projection gap of 1.5+ saves). Only 4 saves rows carry a new-rule EV. The live tracker's 31-18 passed vs 41-42 played is the same pattern on its de-dup.

Note on the headline figures in the request: on this de-duplicated graded set the saves projection sits 0.63 below the line (median 0.60), and proj - actual is +0.02 (median +0.50). The request's -0.69 / -0.33 came from the site's graded rows, which mix books and model versions. The nightly pattern matches: Oct 19/20/22 are -1.3 / -1.5 / -2.8 vs actual, and the as-posted shots-against gap was -1.17 on Oct 20 and -1.01 on Oct 22.

---

## SAVES: graded real lines as logged at pick time (283 lines, 2026-09-29 to 2026-10-23)

Projection = the model's number at pick time. Before 10/23 that's the older model, so the current model's saves numbers are in the next section.

| night | lines | OVER | UNDER | OVER plays | UNDER plays | proj−line | proj−actual | actual−line | proj<line |
|---|---|---|---|---|---|---|---|---|---|
| 2026-09-29 | 10 | 5 | 5 | 0 | 0 | +0.04 | +0.94 | -0.90 | 50.0% |
| 2026-09-30 | 6 | 1 | 5 | 1 | 3 | -1.15 | -0.48 | -0.67 | 83.3% |
| 2026-10-01 | 12 | 3 | 9 | 0 | 0 | -0.95 | +2.30 | -3.25 | 75.0% |
| 2026-10-02 | 9 | 3 | 6 | 0 | 4 | -1.14 | +0.02 | -1.17 | 66.7% |
| 2026-10-03 | 18 | 7 | 11 | 2 | 7 | -0.81 | -1.03 | +0.22 | 61.1% |
| 2026-10-04 | 9 | 4 | 5 | 1 | 3 | -0.50 | -0.22 | -0.28 | 55.6% |
| 2026-10-05 | 7 | 3 | 4 | 0 | 0 | +0.13 | +3.20 | -3.07 | 57.1% |
| 2026-10-06 | 16 | 7 | 9 | 2 | 3 | -0.20 | +1.55 | -1.75 | 56.2% |
| 2026-10-07 | 6 | 2 | 4 | 0 | 1 | -0.47 | +1.70 | -2.17 | 66.7% |
| 2026-10-08 | 18 | 7 | 11 | 0 | 4 | -0.45 | +0.22 | -0.67 | 61.1% |
| 2026-10-09 | 5 | 1 | 4 | 1 | 2 | -0.58 | +3.52 | -4.10 | 80.0% |
| 2026-10-10 | 18 | 6 | 12 | 1 | 5 | -0.50 | +0.94 | -1.44 | 61.1% |
| 2026-10-11 | 5 | 1 | 4 | 0 | 0 | -0.24 | +2.26 | -2.50 | 80.0% |
| 2026-10-12 | 4 | 3 | 1 | 0 | 0 | +0.27 | +2.27 | -2.00 | 0.0% |
| 2026-10-13 | 31 | 11 | 20 | 2 | 11 | -0.82 | +0.15 | -0.97 | 67.7% |
| 2026-10-14 | 4 | 1 | 3 | 0 | 0 | -0.55 | +1.70 | -2.25 | 75.0% |
| 2026-10-15 | 18 | 6 | 12 | 0 | 4 | -0.59 | -0.87 | +0.28 | 55.6% |
| 2026-10-16 | 4 | 0 | 4 | 0 | 0 | -0.95 | -0.45 | -0.50 | 100.0% |
| 2026-10-17 | 24 | 9 | 15 | 1 | 6 | -0.63 | -1.09 | +0.46 | 62.5% |
| 2026-10-18 | 3 | 2 | 1 | 0 | 0 | +0.73 | -1.10 | +1.83 | 0.0% |
| 2026-10-19 | 8 | 2 | 6 | 0 | 2 | -1.06 | -1.31 | +0.25 | 75.0% |
| 2026-10-20 | 22 | 7 | 15 | 0 | 8 | -1.00 | -1.45 | +0.45 | 63.6% |
| 2026-10-21 | 4 | 1 | 3 | 0 | 1 | -0.55 | -0.30 | -0.25 | 75.0% |
| 2026-10-22 | 18 | 2 | 16 | 1 | 5 | -0.81 | -2.76 | +1.94 | 88.9% |
| 2026-10-23 | 4 | 0 | 4 | 0 | 3 | -0.66 | +0.84 | -1.50 | 50.0% |

**Overall**

| stat | mean | median |
|---|---|---|
| proj − line | -0.63 | -0.60 |
| proj − actual | +0.02 | +0.50 |
| actual − line | -0.64 | -0.50 |

Share of lines with proj < line: **64.3%**. Sides taken: OVER 94, UNDER 189; plays: OVER 12, UNDER 72.

| side | set | record |
|---|---|---|
| OVER | all lines | 48-46 (51.1%), -7.41u, ROI -10.0% on 74 priced |
| OVER | plays | 7-5 (58.3%), +0.48u, ROI 5.3% on 9 priced |
| OVER | PASS (not played) | 41-41 (50.0%), -7.89u, ROI -12.1% on 65 priced |
| UNDER | all lines | 106-83 (56.1%), -3.27u, ROI -2.1% on 155 priced |
| UNDER | plays | 38-34 (52.8%), -6.25u, ROI -10.4% on 60 priced |
| UNDER | PASS (not played) | 68-49 (58.1%), +2.98u, ROI 3.1% on 95 priced |

Average P(under): raw model **53.5%**, calibrated **53.3%**; actual under rate **53.7%**.


## SOG: graded real lines as logged at pick time (2551 lines, 2026-09-29 to 2026-10-23)

Projection = the model's number at pick time. Before 10/23 that's the older model, so the current model's saves numbers are in the next section.

| night | lines | OVER | UNDER | OVER plays | UNDER plays | proj−line | proj−actual | actual−line | proj<line |
|---|---|---|---|---|---|---|---|---|---|
| 2026-09-29 | 8 | 1 | 7 | 1 | 7 | -0.07 | -0.95 | +0.88 | 75.0% |
| 2026-09-30 | 6 | 0 | 6 | 0 | 4 | +0.02 | +0.02 | +0.00 | 50.0% |
| 2026-10-01 | 139 | 51 | 88 | 5 | 29 | +0.05 | -0.09 | +0.14 | 46.8% |
| 2026-10-02 | 70 | 20 | 50 | 6 | 38 | +0.00 | -0.03 | +0.03 | 48.6% |
| 2026-10-03 | 234 | 67 | 167 | 29 | 116 | +0.05 | +0.02 | +0.03 | 46.2% |
| 2026-10-04 | 76 | 25 | 51 | 11 | 33 | +0.09 | -0.12 | +0.21 | 38.2% |
| 2026-10-05 | 50 | 21 | 29 | 9 | 20 | +0.10 | +0.00 | +0.10 | 36.0% |
| 2026-10-06 | 155 | 56 | 99 | 30 | 75 | +0.09 | -0.04 | +0.13 | 41.9% |
| 2026-10-07 | 50 | 19 | 31 | 11 | 24 | +0.11 | -0.11 | +0.22 | 40.0% |
| 2026-10-08 | 169 | 63 | 106 | 30 | 72 | +0.11 | -0.07 | +0.18 | 35.5% |
| 2026-10-09 | 68 | 19 | 49 | 9 | 34 | +0.05 | +0.20 | -0.15 | 44.1% |
| 2026-10-10 | 185 | 59 | 126 | 28 | 92 | +0.06 | -0.19 | +0.25 | 42.2% |
| 2026-10-11 | 47 | 22 | 25 | 9 | 15 | +0.18 | -0.15 | +0.33 | 21.3% |
| 2026-10-12 | 33 | 16 | 17 | 12 | 13 | +0.20 | +0.40 | -0.20 | 39.4% |
| 2026-10-13 | 277 | 79 | 198 | 39 | 150 | +0.04 | -0.05 | +0.08 | 48.0% |
| 2026-10-14 | 33 | 14 | 19 | 6 | 13 | +0.10 | +0.14 | -0.05 | 33.3% |
| 2026-10-15 | 177 | 58 | 119 | 28 | 77 | +0.09 | -0.16 | +0.25 | 37.9% |
| 2026-10-16 | 36 | 10 | 26 | 6 | 16 | +0.06 | +0.11 | -0.06 | 38.9% |
| 2026-10-17 | 215 | 73 | 142 | 41 | 91 | +0.10 | -0.00 | +0.10 | 37.7% |
| 2026-10-18 | 36 | 11 | 25 | 1 | 17 | +0.06 | -0.19 | +0.25 | 41.7% |
| 2026-10-19 | 54 | 24 | 30 | 12 | 20 | +0.15 | +0.09 | +0.06 | 31.5% |
| 2026-10-20 | 172 | 50 | 122 | 20 | 83 | +0.06 | -0.14 | +0.20 | 44.2% |
| 2026-10-21 | 27 | 6 | 21 | 5 | 14 | -0.03 | +0.03 | -0.06 | 44.4% |
| 2026-10-22 | 203 | 71 | 132 | 29 | 90 | +0.09 | -0.09 | +0.18 | 39.9% |
| 2026-10-23 | 31 | 6 | 25 | 1 | 10 | +0.11 | +0.19 | -0.08 | 38.7% |

**Overall**

| stat | mean | median |
|---|---|---|
| proj − line | +0.08 | +0.07 |
| proj − actual | -0.05 | +0.19 |
| actual − line | +0.13 | -0.50 |

Share of lines with proj < line: **41.5%**. Sides taken: OVER 841, UNDER 1710; plays: OVER 378, UNDER 1153.

| side | set | record |
|---|---|---|
| OVER | all lines | 456-385 (54.2%), -62.76u, ROI -7.9% on 797 priced |
| OVER | plays | 214-164 (56.6%), -28.83u, ROI -7.7% on 374 priced |
| OVER | PASS (not played) | 242-221 (52.3%), -33.93u, ROI -8.0% on 423 priced |
| UNDER | all lines | 959-751 (56.1%), -38.58u, ROI -2.4% on 1616 priced |
| UNDER | plays | 675-478 (58.5%), -16.75u, ROI -1.5% on 1116 priced |
| UNDER | PASS (not played) | 284-273 (51.0%), -21.83u, ROI -4.4% on 500 priced |

Average P(under): raw model **53.9%**, calibrated **52.6%**; actual under rate **52.7%**.


## SAVES: shots against, current model (walk-forward, every 2026-27 start)

334 starts through 2026-10-23. exp_SA includes the game-script term (gs = 0.015). Negative = model expected fewer shots than the team faced.

| date | starts | exp_sa | faced | exp_sa − faced |
|---|---|---|---|---|
| 2026-10-05 | 8 | 27.1 | 24.9 | +2.20 |
| 2026-10-06 | 18 | 27.4 | 26.9 | +0.47 |
| 2026-10-07 | 6 | 28.5 | 26.7 | +1.85 |
| 2026-10-08 | 20 | 27.3 | 27.8 | -0.48 |
| 2026-10-09 | 8 | 27.4 | 27.0 | +0.44 |
| 2026-10-10 | 28 | 27.5 | 26.4 | +1.14 |
| 2026-10-11 | 6 | 26.5 | 26.3 | +0.14 |
| 2026-10-12 | 6 | 27.7 | 26.0 | +1.75 |
| 2026-10-13 | 32 | 27.2 | 27.4 | -0.20 |
| 2026-10-15 | 22 | 27.2 | 28.4 | -1.15 |
| 2026-10-17 | 28 | 27.1 | 26.9 | +0.16 |
| 2026-10-19 | 8 | 27.3 | 27.8 | -0.47 |
| 2026-10-20 | 22 | 27.5 | 28.8 | -1.32 |
| 2026-10-22 | 24 | 27.3 | 28.3 | -1.00 |

**Season mean (exp_sa − faced): +0.07** (median +0.57).


By the goalie's team win probability (underdog → favourite):

| bucket | starts | exp | faced | exp_sa − faced |
|---|---|---|---|---|
| (0.0, 0.38] | 49 | 30.9 | 31.3 | -0.39 |
| (0.38, 0.45] | 65 | 28.7 | 29.3 | -0.63 |
| (0.45, 0.55] | 106 | 27.4 | 27.4 | +0.07 |
| (0.55, 0.62] | 65 | 25.7 | 24.8 | +0.87 |
| (0.62, 1.0] | 49 | 24.1 | 23.7 | +0.41 |

| venue | starts | exp_sa − faced |
|---|---|---|
| away | 167 | -0.45 |
| home | 167 | +0.59 |

Save %: projected 0.9000 vs actual 0.8922 (shot-weighted) → projected − actual = **+0.0078**.


Projected saves vs actual, every 2026-27 start: mean (proj − actual) **-0.06**.


League shots per team-game: model's league average 27.63 (mean over 2026-27 starts; 27.61 now) vs actual 2026-27 27.28.


As posted in the nightly snapshots (what the tracker's shots-against bias column shows; sign flipped to exp − faced):

| date | n | exp_sa − faced (as posted) |
|---|---|---|
| 2026-10-01 | 16 | +0.73 |
| 2026-10-02 | 10 | +0.56 |
| 2026-10-03 | 26 | +0.27 |
| 2026-10-04 | 10 | -0.09 |
| 2026-10-05 | 8 | +2.28 |
| 2026-10-06 | 18 | +0.51 |
| 2026-10-07 | 6 | +1.84 |
| 2026-10-08 | 20 | -0.45 |
| 2026-10-09 | 8 | +0.42 |
| 2026-10-10 | 28 | +1.24 |
| 2026-10-11 | 6 | +0.55 |
| 2026-10-12 | 6 | +1.73 |
| 2026-10-13 | 32 | -0.05 |
| 2026-10-14 | 4 | +1.89 |
| 2026-10-15 | 22 | -1.16 |
| 2026-10-16 | 4 | +0.13 |
| 2026-10-17 | 28 | +0.21 |
| 2026-10-18 | 4 | -0.75 |
| 2026-10-19 | 8 | -0.48 |
| 2026-10-20 | 22 | -1.17 |
| 2026-10-21 | 4 | +0.47 |
| 2026-10-22 | 24 | -1.01 |
| 2026-10-23 | 4 | +0.72 |

**gs re-fit on 2025-26 + 2026-27** (shots-against MAE): **0.030** vs 0.015 in production.


## SOG: projected vs actual TOI (5698 player-games from the nightly snapshots)

| pos | role | n | toi_proj | toi_act | proj TOI − actual | sog_proj | sog_act |
|---|---|---|---|---|---|---|---|
| D | PP1 | 305 | 22.73 | 23.05 | -0.32 | 1.89 | 1.96 |
| D | PP2 | 269 | 20.2 | 20.0 | +0.20 | 1.43 | 1.49 |
| D | no PP | 1200 | 18.26 | 18.03 | +0.23 | 1.07 | 0.98 |
| D | unknown | 153 | 18.5 | 17.22 | +1.27 | 1.21 | 1.07 |
| F | PP1 | 1201 | 18.09 | 18.53 | -0.44 | 2.26 | 2.34 |
| F | PP2 | 881 | 15.1 | 14.81 | +0.28 | 1.65 | 1.59 |
| F | no PP | 1406 | 13.23 | 12.94 | +0.29 | 1.3 | 1.19 |
| F | unknown | 283 | 14.82 | 13.9 | +0.92 | 1.65 | 1.51 |

All skaters: proj TOI − actual **+0.14** min; proj SOG − actual **+0.04**.


**SOG proj vs actual by line value** (graded real lines):

| line | n | proj | actual | proj−actual | over rate | UNDER share of sides |
|---|---|---|---|---|---|---|
| 0.5 | 6 | 1.1 | 1.5 | -0.40 | 83.3% | 0.0% |
| 1.5 | 1535 | 1.71 | 1.69 | +0.02 | 48.2% | 52.1% |
| 2.5 | 843 | 2.4 | 2.5 | -0.10 | 44.6% | 88.6% |
| 3.5 | 164 | 3.21 | 3.66 | -0.44 | 51.2% | 98.2% |
| 4.5 | 3 | 3.82 | 6.33 | -2.51 | 66.7% | 100.0% |

Negative-binomial P(under) when the projection equals the line (the discreteness bias):

| line | P(under) when proj = line |
|---|---|
| 0.5 | 61.3% |
| 1.5 | 56.8% |
| 2.5 | 55.6% |
| 3.5 | 55.1% |