# Audit fixes: what changed and why

Your betting rules (shots and points at 58%+ at 1x or better) are unchanged. The saves threshold moved from 1.5 to 2.5 saves of edge (3.0 for unders) because item 11 asked for that, and all the thresholds are now settings in `model/pricing.py`. Evidence for every change is in `model/reports/audit_backtest.md` (run `python model/backtest_audit.py`).

## Parameter changes

| Setting | Before | After | Why |
|---|---|---|---|
| Market blend weight on the model (`cal.w`, per market) | fixed 0.6 | fitted by log loss each build: **SOG 0.0, saves 0.0, points 0.75** | Fitted on walk-forward probabilities once there are 200 graded lines (points: in-sample until then). The weight is shrunk by (hit − 50%) / (57.7% − 50%) when the model's record on lines where it disagrees with DK is below the 1x break-even. For SOG that record is 265-272 (49.4%), so the weight goes to 0. For saves, DK no-vig had the lowest log loss out of sample, so the fit itself is 0. |
| TAKE rule | shown as "your rule", not enforced | `pricing.verdict`: blended p ≥ `TAKE_P` 0.58, multiplier ≥ `MIN_MULT` 1x, beats break-even, player MATCHED, **model alone leans the same way** | Items 3 and 9. The last condition is what stops market echoing: with weight 0 the blended p is the DK price, so a TAKE needs DK and the model to agree. |
| Saves play threshold | edge ≥ 1.5 | **edge ≥ 2.5 over, ≥ 3.0 under** (`SAVES_EDGE_OVER` / `SAVES_EDGE_UNDER`), plus calibrated p ≥ 0.58 (`SAVES_TAKE_P`) | Item 11. The backtest so far favours 1.5 unders (66-46 bias-corrected, +7.2% ROI), while 2.5 unders went 19-18 and 3.0 unders 9-9. Samples are small, and you can change the settings. |
| Saves projection | model only | + rolling bias (`SAVES_BIAS_HL` 30-day half-life, shrunk by 20 starts) | Item 6. Last 30 days: mean error −0.21 → +0.01 saves. |
| SOG dispersion (`sog_params.json`) | one `disp_k` 10 | `disp_edges` (1.5, 2.5, 3.5); forwards `disp_f` (8, 7.5, 9, 5); defence `disp_d` (14, 17.5, 7, 7) | Item 4. MLE on player-games of earlier seasons (`fit_props.fit_disp_tiers`). The gain is tiny (log-lik −1.53303 → −1.53283 on 2025-26, unchanged on 2026-27) because the old fit was already flat. PIT deciles are 9.5–10.5%, and P(≥k) for k = 1–4 is within ±1.2 pts overall. |
| Points dispersion (`points_params.json`) | `disp_k` 30 | `disp_edges` (0.4, 0.7, 1.0); forwards (28.5, 60, 300, 300); defence (100, 300, 300, 300) | Same fit. Points are nearly Poisson. |
| Calibration slopes (`calibrate.side_fit`) | shrunk by total lines; no bounds | shrunk **per side** by that side's lines / 500, and kept in [0.5, 1.25] | Bug found during the audit: the live points-over slope was 2.24 (fitted on 135 lean-over lines near 50%). It turned a raw 82% over into 96%, so points MORE legs on the live page were overstated. |
| Per-line intercepts (`cal.line_a`) | none | fitted per line bucket, **used only if they beat walk-forward log loss** | Item 2. They don't help yet (SOG 0.68635 with vs 0.68617 without), so they're off. |
| Role-change TOI | ±50% toward the slot whenever the listed line is 2+ slots away | **badge only**, unless DailyFaceoff updated the combination within 6 h (`CONFIRM_H`); then half-way toward the slot, capped at ±15% (`TOI_CAP`) | Item 5. Props are never dropped for a role change. |

## Data plumbing

- **Player matching** (`model/players.py`). Every board is matched on (name, team, game) to one NHL playerId, within the row's team or game, never across the league.
  - Names are normalized: accents and punctuation stripped, Stützle = Stuetzle, initials, nicknames and two-letter first names handled.
  - If 0 or 2+ players match, the row is UNMATCHED and excluded, and the count is shown.
  - Rosters come from `api-web.nhle.com/v1/roster/{team}/current` every build, falling back to the last saved roster and then to box scores.
  - Used for DraftKings saves, shots and points rows; DailyFaceoff combos; PrizePicks and pasted boards (JS mirror); and leg grading (by playerId).
- **Pick6** (`model/pick6.py`).
  - The build pulls the board itself and decodes the loader data embedded in the page (`__remixContext` / `__reactRouterContext` JSON, or single-fetch turbo-stream `enqueue` chunks).
  - Rows missing playerId, team, game, market, line, either multiplier, source or fetch time are dropped and counted. Started games are removed.
  - A 0-row parse shows a red banner instead of an empty board.
  - DraftKings shots, points and saves lines fill in players Pick6 doesn't list.
- **Refresh**. Builds run every 15 minutes from 9 AM to 1:45 AM CT. DraftKings is re-pulled at most every 55 minutes (`model/data/odds_cache.json`) to protect the Odds API quota.
- **Slate day** (`model/slate.py`). The slate is today in America/Chicago until all of today's games are FINAL. The old build used the UTC date, which dropped tonight's games after 6–7 PM CT. Started games show in a Live & final list with the stat so far and HIT/MISS.
- **Leg log** (`model/data/legs.csv`).
  - Every displayed leg is stored: build time, playerId, team, line, side, multiplier, model p, market p, blended p, verdict, role change.
  - Legs are graded by playerId.
  - The Results tab shows a reliability table and records by side, line, multiplier and TAKE legs.

## Page

- Today's plays box: TAKE legs only, ranked by p, conflicts flagged.
- Every prop row ends in TAKE MORE, TAKE LESS or PASS with a reason. A player's best line (highest EV at ≥1x) is the only TAKE; his other lines sit greyed under it.
- Conflicts demote the lower-p leg: teammates on opposite sides of a prop, or a goalie's saves against the opposing skaters' shots.
- New columns: model p, market p, blended p, and edge vs the multiplier's break-even.
- Saves rows show bias-corrected edge, calibrated p and the call.
- New Calibration tab: walk-forward Brier and log loss vs DK no-vig and the old blend, reliability by side and line, the blend weight and the disagreement record.

## What could not be verified from here

- The session that built this could not reach api-web.nhle.com, pick6.draftkings.com, DailyFaceoff or the Odds API. GitHub Actions can, and its first build will be the real test.
- The Pick6 parser was tested against a synthetic page shaped like a Remix / React Router page, not a captured one. If the banner says "parse failed: 0 rows", save the page as `model/tests/fixtures/pick6.html` and the parser can be fixed against it (`test_real_saved_page` then runs).
- Your audit's numbers (1,116 Pick6 legs, 55-57 at 1x) came from your own records. The repo has 139 graded Pick6 rows, so the backtest uses the 3,528 graded DraftKings SOG lines instead.
- The role-change subset can't be backtested: there is no history of pre-game line combinations. The leg log records it from now on.
- Points have 4 days of graded lines (Oct 29 to Nov 1), so their blend weight is still in-sample and there is no walk-forward score yet.
