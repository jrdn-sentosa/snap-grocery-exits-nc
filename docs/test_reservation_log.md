# Test-reservation log

The 2022-2024 cohorts are the reserved test set (CLAUDE.md hard rule 1). This file records every time information from the
test period (anything dated after the 2021-12-31 data cut-off) was seen during development, so the reservation can be audited.
Entries are added by hand, or automatically when `src/eda/lookup.py` is called with `include_test_period=True`.

Default practice: look stores up with `src/eda/lookup.py`, which censors everything after 2021-12-31. The dashboard database holds
no row after the cut-off (the schema's CHECK constraints refuse them).

## Entries

### 2026-10-27: one record's later history seen (Earth Fare 120, Record ID 1429066)
- **What was seen:** while investigating a store the project owner pointed out (Earth Fare 120, Record ID 740603, exit 2021-07-19),
  an exploratory lookup printed the authorization history of both Earth Fare Record IDs, including the **end date of its successor,
  Record ID 1429066 (a date in 2025, after the cut-off; the value is deliberately not repeated here)**. A panel print a few minutes later
  showed the same date in the `qa_spell_end` column of that record's 2021 store-year. Seeing it implies that Record ID 1429066 has
  `exit_12m = 0` in the test years 2022-2024 (it was still authorized through 2024).
- **How it happened:** the lookup was written before this rule existed and did not censor; the exposure was one record, noticed
  immediately, and reported to the project owner in the same session. From then on its later history was withheld in all reports.
- **Use:** none. No label, rule, threshold, feature, figure, statistic or model choice was derived from it. The ownership-change
  rule that now classifies Earth Fare 120 as an ownership change was specified from the 2021 facts only (the successor was
  authorized 2020-11-09, before the cut-off).

### 2026-10-27: events after the cut-off used for labels and flags of TRAIN/VALIDATION stores (disclosure, not a glimpse of test labels)
- **Successor starts up to 90 days after the end:** the ownership-change rule looks up to 90 days past an exit, so a 2021 exit can be
  classified using an authorization that began in Jan-Mar 2022. That is how the label is defined (the 2021 label needs the next 90
  days), and it touches no test-cohort row.
- **`qa_reentered_later` / `qa_reentry_gap_days`** count re-authorizations of train/validation exits through the end of the data
  (Dec 2025). They are QA columns (never features), not loaded to Supabase, and reveal no test-cohort label. The reentry
  analysis reports numbers both through the end of the data and through 2021-12-31 only.
