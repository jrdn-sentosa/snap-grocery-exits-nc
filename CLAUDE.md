# Project: Predicting SNAP Grocery Store Exits in North Carolina (Charlotte–Mecklenburg focus)

Data Science project. D1 (proposal) is approved; D2 (data preparation and EDA) and D3 (baseline and models) are done. We are now on **D4**.

**D4 status.** The two post-D3 fixes are done (unemployment_rate year-proxy indicator dropped and the column imputed for both models; tuning grids widened), recorded in `docs/changes_since_d3.md`. **The model choice is frozen after this rerun** (selected by mean rolling-fold PR-AUC inside 2012–2018). **Under that rule on `exit_12m`, gradient-boosted trees are now the selected model (fold 0.155 vs 0.147 for logistic regression); the D4 pipeline uses them with the settings found here: learning rate 0.1, `max_leaf_nodes` 2, `min_samples_leaf` 100, l2 0, 300 iterations, `unemployment_rate` median-imputed.** (On `exit_12m_strict` logistic regression remains ahead on folds, 0.066 vs 0.059.). Do not re-tune or re-select on validation. **The test years (2022–2024) are evaluated once, in D6.**

## Research question (approved, do not change)
Using only information available on January 1 of each year, can we predict which SNAP-authorized grocery stores in North Carolina will lose SNAP authorization within the next 12 months more accurately than the historical exit rate for their store type?

- **Observation:** one grocery store (Record ID) authorized on Jan 1 of year t (a store-year).
- **Grocery store types:** Supermarket, Super Store, Large Grocery Store, Medium Grocery Store, Small Grocery Store.
- **Outcome:** `exit_12m` = 1 if the store's authorization ends in [Jan 1 t, Dec 31 t], else 0. An end is an **ownership change, not an exit** if a different Record ID is a successor (revision 3): (a) within **0.15 mile** with a matching store name (cleaned-name similarity ≥ 0.80, **or one name contains the other, or token-set similarity ≥ 0.90**; store numbers removed), authorized from **365 days before to 90 days after** the end, or (b) the identical standardized street address (same ZIP; a unit listed on only one side counts as a match, two different units do not) at **any distance** (a far geocode for an identical address is a geocoding error), authorized from **30 days before to 90 days after**, or (c) **the same store registered twice**: a strong name match (containment, token-set ≥ 0.90 or similarity ≥ 0.90) within **0.05 mile** or at the identical address, authorized any time up to 90 days after the end **however long the two records overlapped**, provided it is still authorized after the end. The 365-day co-tenant exclusion therefore applies only when the names do not match strongly. Record pairs listed in **`data/reference/successor_overrides.csv`** (a committed, reasoned decision list) are never successors; `03` logs each one. `qa_successor_type_change` marks ownership changes whose successor has a different store type (QA, never a feature). Same-Record-ID periods ≤ 90 days apart are one spell. Implemented in `src/prep/03_spells.py` (constants in `src/prep/matching.py`); before/after in `docs/label_rule_change.md` (revisions 1-3; revision 3 changes in `docs/successor_revision3_changes.md`). (Replaces the earlier same-address-key −30/+90-day rule, which missed re-registrations authorized months before the old record ended, e.g. Earth Fare 120; revision 3 adds Compare Foods, 4316 N Tryon St.)
- **Cohorts:** 2008–2024.
- **Split (fixed, chronological):** train 2008–2018, validate 2019–2021, **test 2022–2024 (reserved)**.

## Hard rules
1. **Reserve the test set.** Write test-cohort rows (2022–2024) to a separate file/table. Never compute outcome statistics, plots, or summaries on test rows. EDA of the outcome uses train (and validation, if labeled as such) only. Descriptive counts of stores (not outcomes) may include all years. **Look stores up with `src/eda/lookup.py`**, which censors everything after 2021-12-31 by default; any glimpse of the test period is recorded in `docs/test_reservation_log.md`.
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
- **D3: baseline and models must be compared on the same rows.** The historical-rate baseline and every model are evaluated on identical store-years, so the comparison sample is likely the 2012–2018 train rows (14,982 store-years, 632 `exit_12m` exits; 2008–2011 has 7,572 and 214). Do not compare a baseline fit on 2008–2018 with a model fit on 2012–2018 without saying so.
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
data/reference/      # committed decision lists (successor_overrides.csv)
data/interim/        # cleaned retailer + spell tables
data/processed/      # store_year_trainval.parquet, store_year_test.parquet (test reserved)
src/prep/            # 00-05d, 06_load_supabase.py; common.py, matching.py, store_years.py; reference/release_dates.csv
src/eda/             # EDA reports, plots.py (figures/), lookup.py (censored store lookup), data_dictionary.py
src/model/           # 01-09 (evaluate ... 09_final_refit.py); store_prep.py, serving.py, explain.py, impact.py, common_model.py
models/              # pipeline.joblib + metadata.json (gitignored; built by 09_final_refit.py)
src/site/             # D5: 01_export_site_data.py (JSON for the website, 2024 cohort features only), 02_check_export.py
frontend/            # D5: Next.js (App Router, TypeScript, Tailwind, shadcn/ui) site on Vercel; public/data/ is the committed export
app/                 # api.py (FastAPI), modal_api.py, verify_api.py; streamlit_app.py, modal_app.py (dashboard)
supabase/            # schema.sql
docs/                # data dictionary, cleaning log, model_spec_d4.md, model_examples_d4.json, api_verification.md, change logs
figures/
pyproject.toml       # uv; dependency groups: dev (modal), api (fastapi[standard]==0.163.1, requests)
```
API commands use `uv run --group api ...` (never `uv run --with`). CORS allows GET/POST from http://localhost:3000 and `FRONTEND_ORIGIN`.

## D4 checklist
- [x] Model frozen (gradient-boosted trees, selected on 2012-2018 rolling folds); refit on 2012-2021 (`src/model/09_final_refit.py`)
- [x] Spec (`docs/model_spec_d4.md`) and fixed examples (`docs/model_examples_d4.json`: 9 scored, 8 invalid)
- [x] Risk tiers, reasons, impact score and priority (`serving.Bundle`)
- [x] FastAPI `app/api.py` (/health, /model-info, POST /predict; 422 on invalid input, 503 until the self-check passes), CORS
- [x] Deployed on Modal (`app/modal_api.py`), no secrets
- [x] `app/verify_api.py`: local and deployed 9/9 and 8/8, plus the empty-MODEL_DIR 503 check -> `docs/api_verification.md`
- [x] Reproducible environment (`api` dependency group, `uv.lock`)
- [ ] Test years (2022-2024) evaluated once, in D6; never before
