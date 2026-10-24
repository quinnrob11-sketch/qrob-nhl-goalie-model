# SOG discreteness and the projection-gap rule (step 5)

On a half-point line, a negative binomial gives P(under) above 50% when the projection equals the line: 56.8% at 1.5 and 55.6% at 2.5 (dispersion 12). Before this step, those unders could be plays with no real disagreement from the line. Below: the step-4 walk-forward replay (calibrated, market-blended, 2% margin), where "no real disagreement" means the projection is above line − 0.15.

| line | UNDER plays | of which proj > line − 0.15 | share | their record | hit | units | ROI | proj ≥ line (model at or above the line) |
|---|---|---|---|---|---|---|---|---|
| 1.5 | 78 | 60 | 76.9% | 33-27 | 55.0% | +13.13u | 21.9% | 40 |
| 2.5 | 44 | 20 | 45.5% | 9-11 | 45.0% | -0.69u | -3.5% | 12 |

With `MARGIN_SOG` = 0.03 and the projection-gap rule (under only if proj ≤ line − 0.15, over only if proj ≥ line + 0.15, unless EV ≥ 5%):

| rule | plays | OVER | UNDER | UNDER share | record | hit | units | ROI |
|---|---|---|---|---|---|---|---|---|
| step 4 (2% margin, no gap rule) | 141 | 11 (6-5, +1.54u) | 130 (68-62, +8.08u) | 92.2% | 74-67 | 52.5% | +9.62u | 6.8% |
| step 5 (3% margin + gap rule) | 66 | 3 (2-1, +1.11u) | 63 (32-31, +1.34u) | 95.5% | 34-32 | 51.5% | +2.45u | 3.7% |

Reading it: on 1.5 lines, about three in four under plays came from the count model's lean, not from a real projection gap (40 of 78 had the projection at or above the line). On 2.5 lines it was under half. Those 1.5 unders happened to win at the prices taken (+13u on 60 plays), but the rule removes them because nothing in the projection supported them. They were a bet on the shape of the distribution plus a price. The rule cuts SOG plays from 141 to 66. It does not fix the side balance (95% unders): what remains are genuine projection gaps, and on 2.5/3.5 lines the projection runs low for high-volume shooters (step-1 report). Step 6 caps the side balance per night.

Config (`model/pricing.py`, exported to the page): `MARGIN_SOG = 0.03`, `SOG_GAP = 0.15`, `SOG_GAP_EV = 0.05`.
