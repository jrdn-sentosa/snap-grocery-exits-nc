# Project: Predicting SNAP Grocery Store Exits in North Carolina (Charlotte–Mecklenburg focus)

Data Science project. D1 (proposal) is approved. We are now on **D2: data preparation and EDA**.

## Research question (approved, do not change)
Using only information available on January 1 of each year, can we predict which SNAP-authorized grocery stores in North Carolina will lose SNAP authorization within the next 12 months more accurately than the historical exit rate for their store type?

- **Observation:** one grocery store (Record ID) authorized on Jan 1 of year t (a store-year).
- **Grocery store types:** Supermarket, Super Store, Large Grocery Store, Medium Grocery Store, Small Grocery Store.
- **Outcome:** `exit_12m` = 1 if the store's authorization ends in [Jan 1 t, Dec 31 t], else 0. A new authorization (different Record ID) at the same standardized address, authorized from **30 days before to 90 days after** the end date (window −30/+90 days), is an **ownership change, not an exit**. (Replaces the earlier 0 to +90 day rule: new owners are sometimes authorized slightly before the old record ends.)
- **Cohorts:** 2008–2024.
- **Split (fixed, chronological):** train 2008–2018, validate 2019–2021, **test 2022–2024 (reserved)**.

## Hard rules
1. **Reserve the test set.** Write test-cohort rows (2022–2024) to a separate file/table. Never compute outcome statistics, plots, or summaries on test rows. EDA of the outcome uses train (and validation, if labeled as such) only. Descriptive counts of stores (not outcomes) may include all years.
2. **Predictor timing.** Any feature for year t uses only data available before Jan 1 of t: ACS 5-year vintage released before t (e.g., 2013–2017 ACS released Dec 2018 → usable for t ≥ 2019); latest Food Access Research Atlas release before t; nearby-store counts computed from stores active on Jan 1 of t.
3. **No credentials in code or git.** Supabase URL/keys come from environment variables (`.env` locally, Modal secrets when deployed). `.env` and `data/raw/` are in `.gitignore`.
4. **Reproducible.** Every step is a script that runs from raw files to outputs. Use `uv` for the environment. No manual edits to data files.
5. **Explain choices.** Every cleaning rule gets a comment explaining why, and is logged with row counts before/after (we report these in the data note).
6. Follow the conventions from our HW1–HW4 repos (file layout, Supabase loading, Modal deployment). Ask if unsure rather than inventing a different pattern.

## Labels and feature exclusions (decided after the batch-end profile, `docs/batch_end_profile.md`)
Batch ends (`qa_batch_end`) are ~32% of ended periods through 2021, ~33% of grocery ends, concentrated in 2013–2019, and almost never have a same-address successor (~3% vs ~35% for non-batch ends). They also are rarely re-authorized under the same Record ID (~2–3%). We keep both labels in 03/04 and report results under each.
- `exit_12m` (**primary**): 1 if a `true_exit` (an end that is not an ownership change) falls in [Jan 1 t, Dec 31 t], **including batch ends**; 0 otherwise.
- `exit_12m_strict`: same, but a batch-end exit makes the label **missing** (the row is excluded from strict analyses; it is not coded 0, because those stores did lose authorization).
- `exit_is_batch`: for exits only, whether the exit was a `qa_batch_end`; missing for non-exits. Never a feature.
- **Same-Record-ID periods** separated by ≤ 90 days (or overlapping) form one spell; a longer gap ends the spell (exit) and the later period starts a new spell.
- **ACS features exist from the 2012 cohort.** The first usable vintage (2006–2010, on 2010 tracts) was released 2011-12-08, so 2008–2011 store-years have no ACS features. The vintage for cohort t is the latest one released before Jan 1 of t (release dates and sources in `src/prep/reference/release_dates.csv` and `data/raw/acs/manifest.json`); e.g. 2016–2020 was released 2022-03-17, so the 2022 cohort uses 2015–2019. ACS tracts are on 2010 boundaries through the 2022 cohort and on 2020 boundaries from 2023.
- **D3: baseline and models must be compared on the same rows.** The historical-rate baseline and every model are evaluated on identical store-years, so the comparison sample is likely the 2012–2018 train rows (14,982 store-years, 678 `exit_12m` exits; 2008–2011 has 7,572 and 242). Do not compare a baseline fit on 2008–2018 with a model fit on 2012–2018 without saying so.
- **Never model features:** every `qa_*`, `impact_*`, `exit_*` and `bias_*` column (`bias_*` = race/ethnicity for group error analysis and the bias discussion only), and raw end dates. They describe the exit itself or data quality, not the state on Jan 1.
- **Calendar year is not a model feature**, nor any transform of it (year dummies, years since 2005, etc.). Batch ends cluster in particular years, so a year feature would let a model learn USDA's batch timing, which cannot be expected to carry into the test years. `year` is only the cohort index for the split.
- Implementation: label definitions live in `src/prep/store_years.py` (shared by 04 and EDA); spells and ownership changes in `src/prep/03_spells.py`.

## Known data issues (from D1 inspection)
- Raw file: USDA FNS Historical SNAP Retailer Locator Data (national CSV, 2005–2025). Columns: Record ID, Store Name, Store Type, Street Number, Street Name, Additional Address, City, State, Zip Code, Zip4, County, Latitude, Longitude, Authorization Date, End Date (blank = active).
- A row is an **authorization period**, not a store; the same Record ID can have several periods (re-authorizations).
- `1/1/1930` Authorization Date is a placeholder → set to missing, add flag `auth_date_placeholder`.
- City names are inconsistently spelled/capitalized (e.g., "CHARLOTTE", "Charltote"); some store names are malformed.
- End dates cluster on specific days (e.g., 27 Mecklenburg retailers on 2014-03-12) → likely administrative batch actions. Add flag `qa_batch_end` (threshold = 99th percentile of statewide daily end counts, computed from end dates through 2021-12-31 only; currently ≥ 40 retailers on one day). All `qa_*` and `impact_*` columns are excluded from model features.
- Not every exit reduces access: in Mecklenburg the median grocery exit had another SNAP grocery ~0.2 mi away. Compute `impact_dist_nearest_other_grocery_mi` at exit for an impact measure (never a predictor).
- Keep **all** NC SNAP retailers in a separate table: convenience stores are needed for the "convenience-to-grocery ratio" (partial food-swamp) feature even though they are not observations.
- The data ends Dec 2025; USDA's new stocking standards (compliance by Nov 4, 2026) are not reflected.

## Repository layout
```
data/sources.yaml    # manifest of data/raw: official URL, size, SHA-256, citation (src/prep/download_raw.py verifies it)
data/raw/            # downloaded files (gitignored); data/raw/acs/ is built by 00_download_acs.py
data/interim/        # cleaned retailer + spell tables
data/processed/      # store_year_trainval.parquet, store_year_test.parquet
src/prep/            # 01_load.py, 02_clean.py, 03_spells.py, 04_panel.py, 05_features.py, 06_load_supabase.py
src/eda/             # plots.py (writes figures/ PNGs)
app/                 # streamlit_app.py (reads from Supabase), modal_app.py
docs/                # data_dictionary.md, data_note.md, cleaning_log.md
figures/
```

## D2 deliverables checklist
- [ ] Preparation code (scripts above), runnable end to end
- [ ] Data dictionary (`docs/data_dictionary.md`): every column, type, source, definition, allowed values/units, missingness
- [ ] Cleaning log with row counts per step
- [ ] 3–5 interpreted plots (train/validation only for outcome plots)
- [ ] Data-quality and sampling concerns written up
- [ ] Test set reserved and documented
- [ ] Supabase tables loaded; Streamlit dashboard reads from Supabase; deployed on Modal
- [ ] 2–3 page data note
