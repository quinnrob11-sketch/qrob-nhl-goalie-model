# Validation (step 10): before vs after

Everything below is walk-forward, with no lookahead, on graded lines through 2026-10-23. Grading did not change. Each line is graded at the price and line it had at pick time; the only change is which lines the rules pick.

## Walk-forward replay: DraftKings lines with both prices

| market | rule | lines | plays | OVER plays | UNDER plays | UNDER share | hit | units | ROI |
|---|---|---|---|---|---|---|---|---|---|
| saves | before (pre-audit) | 257 | 158 | 14 (8-6, +1.41u) | 144 (80-64, +4.75u) | 91.1% | 55.7% | +6.16u | 3.9% |
| saves | after, before night alarm | 261 | 65 | 8 (3-5, -2.23u) | 57 (30-27, -1.20u) | 87.7% | 50.8% | -3.43u | -5.3% |
| saves | after (all steps) | 261 | 26 | 5 (1-4, -3.09u) | 21 (15-6, +7.03u) | 80.8% | 61.5% | +3.94u | 15.1% |
| sog | before (pre-audit) | 2506 | 445 | 24 (16-8, +6.80u) | 421 (226-195, +13.29u) | 94.6% | 54.4% | +20.09u | 4.5% |
| sog | after, before night alarm | 2537 | 62 | 4 (3-1, +2.06u) | 58 (33-25, +8.46u) | 93.5% | 58.1% | +10.52u | 17.0% |
| sog | after (all steps) | 2537 | 24 | 4 (3-1, +2.06u) | 20 (17-3, +16.51u) | 83.3% | 83.3% | +18.57u | 77.4% |

## Live tracker, as graded (unchanged)

These are the real logged plays, graded the same way as before. The new rules apply going forward. Pick6 / PrizePicks legs now carry a leg price (step 7), so the units include them; book-only units are shown separately.

| market | side | record | hit | units (all) | ROI |
|---|---|---|---|---|---|
| saves | OVER / MORE | 7-5 | 58.3% | +0.94u | 7.9% |
| saves | UNDER / LESS | 38-34 | 52.8% | -2.66u | -3.7% |
| sog | OVER / MORE | 214-164 | 56.6% | -27.64u | -7.3% |
| sog | UNDER / LESS | 675-478 | 58.5% | -11.49u | -1.0% |
| all plays | | 934-681 | 57.8% | -40.84u (book -51.35u, DFS legs +10.51u) | -2.5% |

## Saves projection bias (graded saves lines, all books, de-duplicated)

| | proj − actual | proj − line | proj < line |
|---|---|---|---|
| before (as logged) | +0.02 | -0.63 | 64.3% |
| after (current model, walk-forward) | +0.03 | -0.61 | 68.9% |
| actual − line | | -0.64 | |

Since Oct 15 (105 lines), the current model's proj − actual is -1.22. On these nights goalies faced more shots and stopped more of them than projected. Over all 2026-27 starts, shots against are unbiased (step 2), so this is a stretch to watch, not a settled bias.

## Success criteria

| criterion | result | |
|---|---|---|
| saves mean (proj − actual) within ±0.5 | +0.03 (unit test: +0.04 on 2026-27 graded starts) | ✅ |
| saves mean (proj − line) within ±0.5 | -0.61 | ❌ lines sit 0.64 above actual saves, so an unbiased projection can't also be within 0.5 of the line. Moving the projection up to the line would add a 0.6-save over bias. |
| UNDER share of plays ≤ 75% per market | saves 80.8%, SOG 83.3% (from 91% / 95%) | ❌ per market overall; ✅ enforced per night by the alarm. What's left is real: blind saves unders beat blind overs on every line band, and SOG overs only pay at 3.5+. |
| saves calibration not driven by intercept | side-split, no intercept (a = 0); shrunk toward identity below 500 lines | ✅ |
| no test regressions | 16 unit tests pass (new Tests workflow on PRs) | ✅ |
| every tab renders, no console errors | all 8 tabs rendered in headless Chromium, 0 errors (only the blocked PrizePicks fetch, which is expected) | ✅ |

## Which overs and unders to take (evidence)

🟢 = profitable at the real DraftKings price, 🔴 = losing, ⚪ = fewer than 5 plays. "Model" means plays picked by the new rule (walk-forward, before the night alarm, for sample size). "Blind" means every line on that side. Samples are small: treat 🟢 as "keep doing this", not as proof.

| market | line | side | model plays | model units / ROI | blind record | blind ROI | verdict |
|---|---|---|---|---|---|---|---|
| saves | ≤23.5 | OVER | 🔴 1-5 | -4.09u / -68.2% | 🔴 51-68 | -19.6% | avoid |
| saves | ≤23.5 | UNDER | 🟢 15-6 | +6.69u / 31.9% | 🟢 68-51 | 6.2% | **take** (best saves spot) |
| saves | 24.5-26.5 | OVER | ⚪ 2-0 | +1.86u / 93.1% | 🔴 56-59 | -9.3% |  |
| saves | 24.5-26.5 | UNDER | 🔴 14-17 | -4.79u / -15.5% | 🔴 59-56 | -4.5% |  |
| saves | 27.5+ | OVER | ⚪ 0 | – | 🔴 13-14 | -8.3% |  |
| saves | 27.5+ | UNDER | 🔴 1-4 | -3.09u / -61.8% | 🔴 14-13 | -4.0% |  |
| sog | 0.5 | OVER | ⚪ 0 | – | 🟢 5-1 | 31.8% |  |
| sog | 0.5 | UNDER | ⚪ 0 | – | 🔴 1-5 | -65.8% |  |
| sog | 1.5 | OVER | ⚪ 3-1 | +2.06u / 51.5% | 🔴 739-790 | -12.0% | avoid blind |
| sog | 1.5 | UNDER | 🟢 23-16 | +9.68u / 24.8% | 🔴 790-739 | -0.9% | **take** when the model agrees |
| sog | 2.5 | OVER | ⚪ 0 | – | 🔴 371-464 | -10.9% | avoid |
| sog | 2.5 | UNDER | 🔴 10-8 | -0.22u / -1.2% | 🔴 464-371 | -3.4% |  |
| sog | 3.5+ | OVER | ⚪ 0 | – | 🟢 86-81 | 6.1% | **lean over**: the model under-projects top shooters |
| sog | 3.5+ | UNDER | ⚪ 0-1 | -1.00u / -100.0% | 🔴 81-86 | -17.1% | avoid |
