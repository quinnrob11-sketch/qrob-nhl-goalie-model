# Accuracy review (2026-11-08)

What the out-of-sample tests say about the props board, and what changed because of them. Every number below
comes from walk-forward testing: anything that is fitted was fitted only on earlier dates, and every
DraftKings price is the last snapshot taken **before** puck drop (`model/prices.py`). Where something was
chosen on the same dates it is then scored on, that is said.

## The short version

* **No model beats DraftKings' own no-vig price by a reliable margin, in any market.** The best shots model
  is a little better than DK, but only by about 1.5 standard errors (below). Points and saves are not better.
* **The old "+ROI" numbers came from scoring DraftKings favourites as if they were free 1x pick'em legs.** The
  sides the old rule picked were juiced favourites, priced around 64% (SOG) and 68% (points) implied. At DK's
  real price the same picks lost: SOG -7.2% ± 2.6, points -3.4% ± 3.6 per leg.
* **DFS boards don't offer the sides the market favours.** Pick6 paid 1x or more on **0 of 295** sides DK
  priced at 52% or more (Nov 3-8). PrizePicks sets its lines where DK is 50/50.
* So the board is now strict. **Most nights it will show no shots play.** When one does appear, the market and
  the model both like the side, and a DFS board still pays at least 1x on it. That usually means a PrizePicks
  line that hasn't caught up with a DraftKings move.

## Shots on goal

**Projection.** Expected shots are now the player's **shot-attempt rate** (on goal + missed + blocked, from
play-by-play) times **his own shots-on-goal-per-attempt ratio**. Both are shrunk toward position averages.
Ice time is now **0.7 × a 3-game average + 0.3 × a 24-game average** (`sog.SogParams`: `w_att`, `toi_hl2`,
`toi_lam`; parameters in `output/sog_params.json`, fitted with `fit_props.py`).

| test | result |
|---|---|
| NB log-likelihood per player-game, 2025-26 (n=50,182) | +2.12e-3 ± 0.29 vs the old projection |
| NB log-likelihood per player-game, 2026-27 (n=9,503) | +2.05e-3 ± 0.72 |
| Months improved | 11 of 12 |
| Leak test (future rows deleted) | identical projections |
| Placebo (shots on goal treated as "attempts") | -0.06e-3 ± 0.03: the attempt data is real information |

**Probability: a 50/50 blend with the market, in expected shots.** DraftKings' price on the player's line nearest
50% is turned into the expected-shots number that reproduces it (`sog.implied_mean`). That number is averaged
50/50 with the projection, and the result is priced at every line with the model's own dispersion. The Platt
calibration step is no longer used for shots. It was fitted on DK's main lines and pushed every other line
toward 50%: on Pick6 ladder rungs it showed 12-17% for outcomes that happened 5-10% of the time (ECE 0.08,
against 0.007 for the blend).

| on 3,551 graded DK lines (walk-forward weeks) | log loss | Brier |
|---|---|---|
| DraftKings no-vig | 0.68592 | 0.24641 |
| raw model | 0.68612 | 0.24649 |
| **live: 50/50 mean blend** | **0.68458** | **0.24576** |

This is the only probability that scores better than DK, and it is not yet a reliable margin. The separate
experiment at DK's own line measured -0.88e-3 ± 0.88. Away from DK's line (±1 / ±2 and whole-number lines),
it beats the plain market transfer by -1.46e-3 ± 0.68.

**Rule (R1).** A shots TAKE needs all of the following:
* blended p of at least **62%** (Lock at 64%);
* the market's own probability for that side at least **55%**;
* the side offered at **1x or better** on a DFS board;
* the line and the price come from this build's pulls, not a reused cached board.

There is no separate "model alone agrees" check for shots: the blend already carries the model.

| R1 on graded DK lines, if each side were a 1x leg | n | hit | ROI at DK's price |
|---|---|---|---|
| warm walk-forward weeks (`reports/audit_backtest.md` §3) | 270 | **66.3% ± 2.9** | +2.4% ± 4.5 |
| test-period experiment (10-07..11-06) | 246 | 63.8% ± 3.1 | -1.5% ± 4.1 |

The 62% and 55% cut-offs were chosen on these same dates. A cut-off picked on the first half and tested on the
second lands at 60-63%, and every rule did better in the second half (market-only included). At DK's own price
the R1 picks are about break-even. They only make money where a DFS board pays 1x on the side, and none has done
that yet (0 such legs on 1,835 graded Pick6 legs). **Expect roughly 0 shots plays on a typical night.**

**Ladders.** Pick6's More-only rungs and other high-multiplier sides lose money even with accurate
probabilities. Per-leg EV was about -17% at 1x, falling to -46% at 8x and above. Pick6 pays a median 0.59 of
the fair multiplier at 3x and above. Betting every offered side realized -21%, -17%, -28% and -49% by multiplier
bucket, matching the predictions. The board never makes a ladder rung a play. It shows each rung's probability so
you can see this for yourself.

**Never from a cached board.** When a pull fails and the build reuses the last good board, its lines and prices
are still shown, but no row that leans on them can be a TAKE. A cached PrizePicks line paired with tonight's
DraftKings price produced 3 phantom plays in testing.

## Points

* A line priced at DraftKings' own odds is never a TAKE. Walk-forward, DK-priced points TAKEs hit exactly DK's
  no-vig (59.5% ± 3.9 vs 59.8%) and lost at every blend weight (-7% to -23%). The live record was 10-10,
  -21.9% at DK prices.
* The blend weight is a fixed 0.3 until 200 walk-forward lines exist. It is never fitted in-sample: the
  in-sample fits of 0.55-1.0 overstated the walk-forward optimum, which is about 0.3.
* No unders at 1.5 points or more: rated 65.6%, they hit 50.9% (n=55).
* Points still need the market's side at 55%+ and the model alone leaning the same way.

## Saves

* No overs: they lost at every edge threshold.
* A TAKE needs a market price on the line. The DK saves market is close to a coin flip (log loss 0.692), and
  the model ties it at best. So saves TAKEs are now very rare.
* Known gap: saves are calibrated on a probability without the rolling bias correction, while the page applies
  one. With no saves overs and a market requirement, this does not change any call today.

## Data fixes behind these numbers

* **Prices:** every reader now uses the last DraftKings snapshot before the scheduled start
  (`prices.last_pregame`). Before, about 5% of shots lines and 11% of points lines were priced from an in-game
  snapshot.
* **Weeks:** walk-forward splits used the ISO week number, which restarts in January (October-December would
  have trained on January). They now use a running week count (`calibrate.week_key`).
* **The results panel** counts only playable legs: graded, the game's last pre-game build, offered at 1x or
  better or priced, and one row per leg across sources. It settles each leg at its real price, so it no longer
  counts sides a board didn't offer.

## How to read the board

* **Chance** is the blended probability for the side shown. **Needs** is the higher of the play bar and the
  price's break-even. **Edge** is chance minus needs.
* **Proj** is the model's expected shots, and the signed number is projection minus line.
* A pass explains itself in one line, for example: no market price, the market only gives this side 52%, the
  side pays 0.8x, or a cached line.
* The Backtest tab's rule record replays exactly this rule on graded DK lines and settles it three ways: as a
  hypothetical 1x leg, at DK's price, and only where a DFS board would pay 1x.
