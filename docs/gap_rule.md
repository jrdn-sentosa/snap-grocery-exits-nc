# The "gap" rule (D5 website, to be stated once in the D6 report)

**A gap means the next SNAP grocery is more than 1.00 mile away, rounded to two decimals.**

The website shows every distance with two decimals, so the label has to agree with the number on the screen: a store that shows "1.00 mi" is never also marked "leaves a gap".
Example: Diana's Market and Food Lion 2667 are 1.0007 mi apart (about 4 feet over a mile). They display as 1.00 mi and count as "SNAP store nearby".

Where it is implemented
- Site, per store (Jan 1, 2024 distance, `dist_other_grocery_jan1_mi`): `isGap()` in `frontend/lib/format.ts`; used by the receipt, shelf tags, the "high risk and would leave a gap" tile, the "Where to start" callout and the CSV column `leaves_gap_over_1mi`.
- Site, past exits (exit-time distance, `impact_dist_nearest_other_grocery_mi`, train and validation cohorts 2008-2021 only): `src/site/01_export_site_data.py` writes `past_exit_gap` to `frontend/public/data/meta.json` with the same rounding.

Effect on the figures already reported (earlier documents used the unrounded rule, distance > 1)

| Figure | Unrounded (> 1) | Rounded to 2 decimals (> 1.00) | Source |
|---|---|---|---|
| Statewide exits 2008-2021 with no other SNAP grocery within a mile | 250 of 1,071 (23.3%) | 248 of 1,071 (23.2%) | `docs/data_note_d2.md`, `docs/label_rule_change.md`, `docs/panel_summary.md` |
| Mecklenburg exits 2008-2021 | 7 of 131 (5.3%) | 7 of 131 (5.3%) | same |
| Statewide validation exits 2019-2021 | 44 of 225 (19.6%) | 44 of 225 (19.6%) | `docs/impact_score.md` |

Only the statewide 2008-2021 count changes (two exits sit between 1.000 and 1.005 mi). Those documents were not edited. The D6 report should use the rounded rule and give 23.2% (248 of 1,071), or say explicitly that the D2 figure used the unrounded rule.

The website's high-risk and gap count (1 of 28 high-risk stores on Jan 1, 2024; 1 of the top 10 by priority) is computed live from the data with this rule.
