# Skater prop models: walk-forward fit (season 2026-27 scored out of sample)

Fitted by `model/fit_props.py` on earlier seasons only; the current season is never used to fit.

### shots_on_goal

Start: log-lik -1.53488 on 2025-26.

- rate_hl = 60 (log-lik -1.53488)
- toi_hl = 8 (log-lik -1.53446)
- k_min = 100 (log-lik -1.53446)
- carry = 0.7 (log-lik -1.53431)
- c_opp = 1.0 (log-lik -1.53431)
- c_team = 0.0 (log-lik -1.53431)
- back-to-back x0.9738, opponent back-to-back x1.0201 (earlier seasons)
- mean recalibration: proj = -0.1132 + 1.0470 x raw (fit on 2025-26)
- dispersion: size = 10 x mean

Out of sample, 2026-27 (7271 player-games): log-lik -1.51895 vs -1.52191 with the previous settings; mean actual − projected -0.023 (was -0.057).

| line | Brier (new) | Brier (old) | predicted over | actual over |
|---|---|---|---|---|
| 0.5 | 0.17951 | 0.18018 | 72.8% | 72.8% |
| 1.5 | 0.21079 | 0.21122 | 42.5% | 41.7% |
| 2.5 | 0.14374 | 0.14402 | 21.6% | 21.1% |
| 3.5 | 0.07723 | 0.07739 | 10.0% | 9.6% |
| 4.5 | 0.03378 | 0.03384 | 4.3% | 3.8% |

### points

Start: log-lik -0.83567 on 2025-26.

- pass 1: rate_hl = 120 (log-lik -0.83567)
- pass 1: toi_hl = 4 (log-lik -0.83567)
- pass 1: k_min = 400 (log-lik -0.83528)
- pass 1: carry = 0.9 (log-lik -0.83526)
- pass 1: c_opp = 0.5 (log-lik -0.83526)
- pass 1: c_team = 0.0 (log-lik -0.83526)
- pass 2: rate_hl = 120 (log-lik -0.83526)
- pass 2: toi_hl = 4 (log-lik -0.83526)
- pass 2: k_min = 400 (log-lik -0.83526)
- pass 2: carry = 0.9 (log-lik -0.83526)
- pass 2: c_opp = 0.5 (log-lik -0.83526)
- pass 2: c_team = 0.0 (log-lik -0.83526)
- dispersion by tier (projection edges (0.4, 0.7, 1.0)): forwards (26.0, 100.0, 300.0, 300.0), defence (100.0, 300.0, 300.0, 300.0)
- back-to-back x0.9436, opponent back-to-back x1.0475 (earlier seasons)
- mean recalibration: proj = -0.0865 + 1.1694 x raw (fit on 2025-26)
- dispersion: size = 30 x mean

Out of sample, 2026-27 (11879 player-games): log-lik -0.83952 vs -0.84012 with the previous settings; mean actual − projected +0.003 (was +0.004).

| line | Brier (new) | Brier (old) | predicted over | actual over |
|---|---|---|---|---|
| 0.5 | 0.20158 | 0.20176 | 34.9% | 34.9% |
| 1.5 | 0.07648 | 0.0766 | 9.1% | 9.4% |
| 2.5 | 0.01911 | 0.01912 | 2.1% | 2.1% |

_Points refit 2026-11-16: candidates are now compared at their best linear calibration, as for shots (see fit_props.py). The shots section above is from the 2026-11-08 fit and is unchanged._
