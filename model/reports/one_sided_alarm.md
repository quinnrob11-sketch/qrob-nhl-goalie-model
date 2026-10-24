# One-sided board alarm (step 6)

Rule (`pricing.night_alarm`, mirrored on the page): per market and night, if more than 75% of the plays are on one side (2+ plays), a red banner shows the split and only the night's top 10% of plays by EV stay plays (at least one). The rest move to PASS. The tracker counts every game on the night but only demotes plays in games that haven't started, so frozen calls are never rewritten. The split is stored in each night's calls file (`alarm`) and in `tracking.json` (`board_split`), and the Results tab shows it night by night.

Also in this step: **SOG season carry-over 0.3 → 0.5** (`sog_params.json`). Early-season SOG projections for high-volume shooters ran low: in 2026-27 the 3.0+ projection buckets finished +0.46 to +0.60 shots above projection. Keeping more of last season fixes part of that. Early-season log-likelihood improves in all three seasons tested (2024-25, 2025-26, 2026-27), and the high-shooter early bias drops from +0.26 to +0.14. The replay now recomputes SOG probabilities with the current SOG model (walk-forward), the same way it already did for saves. With carry 0.3 it reproduces the logged probabilities exactly.

## Walk-forward replay with steps 4-6 (DraftKings lines with both prices)

| market | stage | plays | OVER | UNDER | UNDER share | record | hit | units | ROI |
|---|---|---|---|---|---|---|---|---|---|
| saves | before alarm | 65 | 8 (3-5, -2.23u) | 57 (30-27, -1.20u) | 87.7% | 33-32 | 50.8% | -3.43u | -5.3% |
| saves | after alarm | 26 | 5 (1-4, -3.09u) | 21 (15-6, +7.03u) | 80.8% | 16-10 | 61.5% | +3.94u | 15.1% |
| sog | before alarm | 62 | 4 (3-1, +2.06u) | 58 (33-25, +8.46u) | 93.5% | 36-26 | 58.1% | +10.52u | 17.0% |
| sog | after alarm | 24 | 4 (3-1, +2.06u) | 20 (17-3, +16.51u) | 83.3% | 20-4 | 83.3% | +18.57u | 77.4% |

## Nights where the alarm fired

| market | night | before (OVER/UNDER) | after |
|---|---|---|---|
| saves | 2026-10-01 | 0/2 | 0/1 |
| saves | 2026-10-02 | 0/4 | 0/1 |
| saves | 2026-10-03 | 2/8 | 0/1 |
| saves | 2026-10-08 | 0/4 | 0/1 |
| saves | 2026-10-10 | 0/4 | 0/1 |
| saves | 2026-10-13 | 1/9 | 0/1 |
| saves | 2026-10-15 | 0/3 | 0/1 |
| saves | 2026-10-17 | 0/6 | 0/1 |
| saves | 2026-10-19 | 0/2 | 0/1 |
| saves | 2026-10-20 | 0/4 | 0/1 |
| sog | 2026-10-01 | 0/12 | 0/2 |
| sog | 2026-10-02 | 0/3 | 0/1 |
| sog | 2026-10-03 | 0/22 | 0/3 |
| sog | 2026-10-08 | 0/2 | 0/1 |
| sog | 2026-10-09 | 0/2 | 0/1 |
| sog | 2026-10-10 | 0/4 | 0/1 |
| sog | 2026-10-13 | 0/2 | 0/1 |
| sog | 2026-10-17 | 0/2 | 0/1 |

What the alarm can and can't do: it stops a lopsided night from turning into ten correlated bets on one side. It can't push the whole market's share under 75% by itself. The plays it keeps are that night's dominant side, and nights with a single play are one-sided by definition. After the alarm, the saves UNDER share is about 80% and the SOG share about 83%. On saves the lean matches the data: the step-2 model is unbiased against actual saves, DraftKings lines sit about 0.6 above where saves land, and the no-vig market prices overs at 50% while they hit 46%. On SOG the remaining lean comes from 2.5/3.5 lines, where the model still sits 3-4 points below the market.
