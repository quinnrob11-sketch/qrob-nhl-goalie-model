# Calibration and market blend (step 4)

What changed (`model/calibrate.py`, `model/pricing.py`, page mirror in `model/template.html`):

* **No intercept, side-split.** The single Platt fit (a + b × logit p) is gone. Lines the raw model leans OVER on and lines it leans UNDER on each get their own slope on logit(p), with no intercept, so a 50% line stays 50% and nothing can hand every under a free 2 points.
* **Minimum sample.** Below 500 graded lines (`pricing.MIN_CAL_N`), each slope is shrunk toward 1 (identity) by n / 500. Saves has 261 lines, so its fitted slopes (0.65 OVER-lean, 0.51 UNDER-lean) are used at about half strength (0.82 / 0.74). SOG has 2,537 lines and uses its fit in full.
* **Market blend.** For lines with both DraftKings prices: final P = 0.6 × calibrated model + 0.4 × no-vig market (`pricing.BLEND_W`, a config value exported to the page). DFS lines have no two-sided price, so they keep the calibrated model alone.
* **Walk-forward only.** Every replay week is calibrated on earlier weeks, then decided by the same `pricing.decide` the tracker and the page use.

Why the board still leans under after this step: with the step-2 model, the saves projection is unbiased against actual saves (+0.04). But DraftKings saves lines sit about 0.6 above where saves land, so an honest model leans UNDER on about 70% of lines (183 of 261). Unders really have been the right side more often (blind under 53.7%). The intercept is gone, but that market structure is not. Steps 5 and 6 deal with the side balance directly.

## Walk-forward replay, DraftKings lines with both prices

| market | rule | plays | OVER | UNDER | UNDER share | record | hit | units | ROI |
|---|---|---|---|---|---|---|---|---|---|
| saves | before (257 lines) | 158 | 14 (8-6, +1.41u) | 144 (80-64, +4.75u) | 91.1% | 88-70 | 55.7% | +6.16u | 3.9% |
| saves | after (261 lines) | 65 | 8 (3-5, -2.23u) | 57 (30-27, -1.20u) | 87.7% | 33-32 | 50.8% | -3.43u | -5.3% |
| sog | before (2506 lines) | 445 | 24 (16-8, +6.80u) | 421 (226-195, +13.29u) | 94.6% | 242-203 | 54.4% | +20.09u | 4.5% |
| sog | after (2537 lines) | 141 | 11 (6-5, +1.54u) | 130 (68-62, +8.08u) | 92.2% | 74-67 | 52.5% | +9.62u | 6.8% |

## Calibration fits

| market | before | after |
|---|---|---|
| saves | Platt a=-0.0834, b=0.3293, n=257 | side-split, no intercept: OVER-lean slope 0.8156 (fit 0.6468, 78 lines), UNDER-lean slope 0.7434 (fit 0.5084, 183 lines); shrunk 0.52 toward identity (n < 500) |
| sog | Platt a=0.0054, b=0.6712, n=2506 | side-split, no intercept: OVER-lean slope 0.6834 (fit 0.6834, 886 lines), UNDER-lean slope 0.6484 (fit 0.6484, 1651 lines); full |

## Buckets by side (after; walk-forward)

**saves**

| side | P(side) | raw n | raw pred | raw actual | cal n | cal pred | cal actual | final n | final pred | final actual |
|---|---|---|---|---|---|---|---|---|---|---|
| OVER | (0.5, 0.55] | 46 | 52.5% | 50.0% | 48 | 52.4% | 50.0% | 61 | 52.0% | 45.9% |
| OVER | (0.55, 0.6] | 23 | 57.2% | 60.9% | 23 | 57.4% | 60.9% | 18 | 56.6% | 55.6% |
| OVER | (0.6, 0.65] | 8 | 61.6% | 37.5% | 6 | 61.8% | 33.3% | 0 | – | – |
| OVER | (0.65, 0.7] | 1 | 66.4% | 100.0% | 1 | 66.4% | 100.0% | 0 | – | – |
| OVER | (0.7, 1.0] | 0 | – | – | 0 | – | – | 0 | – | – |
| UNDER | (0.5, 0.55] | 62 | 52.3% | 58.1% | 62 | 52.3% | 59.7% | 101 | 52.4% | 56.4% |
| UNDER | (0.55, 0.6] | 63 | 57.2% | 58.7% | 65 | 57.3% | 56.9% | 60 | 56.8% | 53.3% |
| UNDER | (0.6, 0.65] | 36 | 62.3% | 55.6% | 30 | 62.1% | 53.3% | 21 | 61.8% | 52.4% |
| UNDER | (0.65, 0.7] | 17 | 66.9% | 47.1% | 21 | 67.0% | 52.4% | 0 | – | – |
| UNDER | (0.7, 1.0] | 5 | 72.3% | 60.0% | 5 | 72.6% | 60.0% | 0 | – | – |

**sog**

| side | P(side) | raw n | raw pred | raw actual | cal n | cal pred | cal actual | final n | final pred | final actual |
|---|---|---|---|---|---|---|---|---|---|---|
| OVER | (0.5, 0.55] | 446 | 52.9% | 52.2% | 513 | 52.5% | 52.2% | 617 | 52.4% | 51.1% |
| OVER | (0.55, 0.6] | 240 | 57.8% | 52.9% | 241 | 57.0% | 55.6% | 308 | 57.0% | 56.5% |
| OVER | (0.6, 0.65] | 104 | 62.3% | 60.6% | 43 | 61.6% | 62.8% | 38 | 61.3% | 57.9% |
| OVER | (0.65, 0.7] | 10 | 66.8% | 70.0% | 3 | 67.0% | 33.3% | 0 | – | – |
| OVER | (0.7, 1.0] | 0 | – | – | 0 | – | – | 0 | – | – |
| UNDER | (0.5, 0.55] | 513 | 53.0% | 50.3% | 784 | 52.7% | 52.7% | 773 | 52.6% | 53.4% |
| UNDER | (0.55, 0.6] | 552 | 57.9% | 57.2% | 607 | 57.2% | 57.3% | 605 | 57.2% | 57.5% |
| UNDER | (0.6, 0.65] | 373 | 62.7% | 58.7% | 193 | 62.2% | 61.7% | 173 | 61.8% | 63.0% |
| UNDER | (0.65, 0.7] | 176 | 67.4% | 58.0% | 57 | 67.2% | 59.6% | 19 | 66.3% | 57.9% |
| UNDER | (0.7, 1.0] | 37 | 73.4% | 67.6% | 10 | 72.6% | 60.0% | 1 | 70.3% | 0.0% |

