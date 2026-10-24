# Saves spread floor (step 3)

The spread is sd = max(sqrt(sv²(μ + μ²/K) + μ·sv(1−sv)), sd_floor). The floor was a hard 6.0. It is now fitted by maximum likelihood of the actual saves (integer bins of the normal), walk-forward by week on 2025-26 + 2026-27 (`model/fit_sa.py`), with the step-2 shots model (gs 0.025) and K = 30. It stays a config value: `sd_floor` in `model/output/saves_dist.json`.

| sd_floor | mean log-lik 2025-26 | 2026-27 | all | share of starts at the floor |
|---|---|---|---|---|
| 0 | -3.3365 | -3.2665 | -3.3290 | 0% |
| 4 | -3.3365 | -3.2665 | -3.3290 | 0% |
| 4.5 | -3.3365 | -3.2665 | -3.3290 | 0% |
| 5 | -3.3365 | -3.2665 | -3.3290 | 0% |
| 5.5 **(fitted)** | -3.3365 | -3.2665 | -3.3290 | 0% |
| 6 (current) | -3.3365 | -3.2678 | -3.3292 | 7% |
| 6.5 | -3.3367 | -3.2734 | -3.3299 | 42% |
| 7 | -3.3387 | -3.2813 | -3.3325 | 82% |
| 7.5 | -3.3471 | -3.2964 | -3.3417 | 97% |
| 8 | -3.3618 | -3.3170 | -3.3570 | 100% |

Walk-forward (each week scored with the floor chosen on earlier weeks): 2026-05-18: 0, 2026-05-25: 0, 2026-06-01: 0, 2026-06-08: 0, 2026-09-28: 0, 2026-10-05: 0, 2026-10-12: 0, 2026-10-19: 0

| | starts | walk-forward log-lik | current floor 6.0 log-lik | difference (total) |
|---|---|---|---|---|
| 2025-26 (after the first 300 starts) | 2392 | -3.3429 | -3.3428 | -0.0 |
| 2026-27 | 334 | -3.2665 | -3.2678 | +0.4 |

Fitted on all of it: **sd_floor = 5.5** (was 6). Floors from 0 to 5.5 tie (the model's own spread is almost never below them), so the fit takes the largest floor within 0.0001 of the best mean log-likelihood. Typical spread at the median workload: 6.59 saves before the floor.

