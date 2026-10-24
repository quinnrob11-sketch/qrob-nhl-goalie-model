# Tier gate (step 9)

Tiers above LOW stay capped until a market has **150 forward-graded plays**, meaning plays picked live under the price-aware rule (logged with an EV, from 2026-10-23 on), with a **hit rate above 57.7%** (2-pick 1x DFS break-even) **and positive ROI**. The gate is computed on every build (`calibrate.forward_gate`) from the same de-duplicated set the Results tab uses, and shown on the Backtest tab. The old ordering test (HIGH > MED > LOW in the replay) is still reported but no longer opens tiers.

## Gate status (graded through 2026-10-23)

| market | forward plays | needed | record | hit | units | ROI | tiers |
|---|---|---|---|---|---|---|---|
| saves | 3 | 150 | 3-0 | 100.0% | +2.82u | 94.1% | capped at LOW |
| sog | 11 | 150 | 6-5 | 54.5% | +1.81u | 16.5% | capped at LOW |

## Forward-graded plays by tier and side

| market | split | record | hit | units | ROI |
|---|---|---|---|---|---|
| saves | HIGH | 0-0 | – | +0.00u | – |
| saves | MED | 0-0 | – | +0.00u | – |
| saves | LOW | 3-0 | 100.0% | +2.82u | 94.1% |
| saves | OVER | 0-0 | – | +0.00u | – |
| saves | UNDER | 3-0 | 100.0% | +2.82u | 94.1% |
| sog | HIGH | 0-0 | – | +0.00u | – |
| sog | MED | 0-0 | – | +0.00u | – |
| sog | LOW | 6-5 | 54.5% | +1.81u | 16.5% |
| sog | OVER | 0-1 | 0.0% | -1.00u | -100.0% |
| sog | UNDER | 6-4 | 60.0% | +2.81u | 28.1% |

## Walk-forward replay by tier and side (DraftKings lines, steps 4-6 rules, uncapped tiers)

| market | split | plays | record | hit | units | ROI |
|---|---|---|---|---|---|---|
| saves | HIGH | 14 | 10-4 | 71.4% | +4.56u | 32.6% |
| saves | MED | 9 | 5-4 | 55.6% | +0.54u | 6.0% |
| saves | LOW | 3 | 1-2 | 33.3% | -1.17u | -38.9% |
| saves | OVER | 5 | 1-4 | 20.0% | -3.09u | -61.8% |
| saves | UNDER | 21 | 15-6 | 71.4% | +7.03u | 33.5% |
| sog | HIGH | 16 | 13-3 | 81.2% | +11.85u | 74.1% |
| sog | MED | 7 | 7-0 | 100.0% | +7.72u | 110.3% |
| sog | LOW | 1 | 0-1 | 0.0% | -1.00u | -100.0% |
| sog | OVER | 4 | 3-1 | 75.0% | +2.06u | 51.5% |
| sog | UNDER | 20 | 17-3 | 85.0% | +16.51u | 82.5% |

Both markets stay capped at LOW: 3 saves and 11 SOG forward plays so far, a long way from 150.
