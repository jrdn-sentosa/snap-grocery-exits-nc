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

### 2026-11-17: test-file feature columns read to build income reference distributions (no outcomes)
- **What was read:** `src/model/09_final_refit.py` opens `data/processed/store_year_test.parquet` with `columns=["year", "median_hh_income"]` only, so the
  deployed Pipeline (`store_prep.StoreFeaturePrep`) can convert tract income to a within-cohort-year percentile for cohorts 2022-2024.
  The same step in `05d_context_columns.py` adds the Jan-1 distance column to the test file without reading any label.
- **What was not read:** no label, outcome, `exit_*`, `qa_*` or `impact_*` column; no counts or rates by outcome. Only the income distribution of the
  cohort's store-years (a Jan-1 feature) is stored.
- **Use:** input preparation only. Nothing about the model, its settings, tiers or cutoffs was derived from these rows.


### 2026-11-19: 2024 Jan-1 feature columns exported for the website (no outcomes)
- **What was read:** `src/site/01_export_site_data.py` opens `data/processed/store_year_test.parquet` once, with the explicit column list `TEST_COLUMNS`
  and a `year == 2024` filter: `record_id`, `spell_id`, `county`, `store_name`, `latitude`, `longitude`, `tract_geoid_2020`, `acs_vintage`, `acs_tract_vintage`, and the
  Jan-1 features the API takes (`store_type`, `store_age_years`, `auth_date_placeholder`, `n_prior_spells_same_id`, `n_prior_ownership_changes`, `chain_size`, `n_grocery_05mi`,
  `n_grocery_1mi`, `n_convenience_1mi`, `convenience_to_grocery_ratio_1mi`, `n_grocery_ends_1mi_prior12m`, the ACS columns, `unemployment_rate`,
  `dist_other_grocery_jan1_mi`). Mecklenburg rows (224) are written to `frontend/public/data/stores.json` so the site can score them through the API.
- **Also read for 2024:** `data/interim/periods_spells.parquet` (including `auth_date` and `end_date`) only to decide which grocery authorizations were active on
  Jan 1, 2024 (the same rule as `05d_context_columns.py`), for the "nearest SNAP grocery" list; and `spells.parquet` street, city and start-date columns (no `spell_end`, no outcome
  flag). The dates are dropped before anything is written. The export holds no end date and no date after 2024-01-01.
- **What was not read:** no `exit_*`, `qa_*`, `impact_*` or `bias_*` column of the test file; no count, rate, plot or summary of any 2022-2024 outcome. The site shows the API's
  predictions for the 2024 cohort, which are model outputs, not outcomes. `02_check_export.py` fails if a forbidden key or any other date appears in the JSON.
- **Everything outcome-based on the site** (tract past-exit shading, store-type exit rates, the grocery pie, the share of past exits that left a gap) uses
  `store_year_trainval.parquet` (cohorts 2008-2021) and spells that ended on or before 2021-12-31; the export asserts the cut-off.
- **Use:** display and scoring only. The model, its settings, tiers and cutoffs stay frozen, and nothing about them was derived from these rows. The 2022-2024 test
  years are still evaluated once, in D6. Note that the 2024 12-month window has already elapsed, so the site labels the scores "as of Jan 1, 2024".
