# Predicting SNAP Grocery Store Exits in North Carolina

Using only information available on January 1 of each year, can we predict which SNAP-authorized grocery
stores in North Carolina will lose SNAP authorization within the next 12 months more accurately than the
historical exit rate for their store type? Charlotte-Mecklenburg is the focus area. Cohorts are 2008-2024
with a fixed chronological split (train 2008-2018, validation 2019-2021, test 2022-2024, reserved).

Project rules, labels and feature-timing rules are in [`CLAUDE.md`](CLAUDE.md); the cleaning log is in
[`docs/cleaning_log.md`](docs/cleaning_log.md). The data note is [`docs/data_note_d2.md`](docs/data_note_d2.md).
Model evaluation results are in [`docs/model_results.md`](docs/model_results.md) and
[`docs/model_error_analysis.md`](docs/model_error_analysis.md); the model evaluation note is
[`docs/model_note_d3.md`](docs/model_note_d3.md). Later fixes and their effect on the results are in
[`docs/changes_since_d3.md`](docs/changes_since_d3.md).

**Final model.** The model is frozen. Under the pre-set rule (mean rolling-fold PR-AUC inside 2012-2018, label `exit_12m`)
**gradient-boosted trees** are selected (fold PR-AUC 0.155 vs 0.147 for logistic regression), with the settings found in that rerun:
learning rate 0.1, `max_leaf_nodes` 2, `min_samples_leaf` 100, l2 0, 300 iterations, `unemployment_rate` median-imputed. Nothing was
re-tuned or re-selected on validation. The final model is **refit on cohorts 2012-2021** and saved as **one fitted sklearn Pipeline,
`StoreFeaturePrep` -> `HistGradientBoostingClassifier`** (`models/pipeline.joblib`, gitignored, rebuilt deterministically). The refit
model cannot be evaluated on validation; it is evaluated once, on the reserved 2022-2024 test years, after all modeling choices are fixed.
- Model spec (inputs, units, outputs, tiers, versions): [`docs/model_spec_d4.md`](docs/model_spec_d4.md)
- Fixed example inputs and expected outputs: [`docs/model_examples_d4.json`](docs/model_examples_d4.json)
- Changes after the model evaluation, and pre-registered follow-up analyses: [`docs/changes_since_d3.md`](docs/changes_since_d3.md)

## Repository structure

```
app/        Streamlit dashboard (streamlit_app.py) and Modal deployment (modal_app.py)
models/     pipeline.joblib and metadata.json: the final fitted Pipeline (gitignored; built by src/model/09_final_refit.py)
data/       sources.yaml: every raw file with its download URL and SHA-256 checksum
  raw/        downloaded source files (gitignored; fetched by src/prep/download_raw.py)
  interim/    cleaned retailer, spell and panel tables (gitignored; rebuilt by scripts)
  processed/  store-year train/validation and reserved test files (gitignored; rebuilt)
  reference/  successor_overrides.csv, the committed decision list of non-successor pairs
docs/       cleaning log, data dictionary, label-rule revisions, batch/gap/feature-association
            reports, plot interpretations, project proposal, test-reservation log
figures/    EDA plots (PNG); figures/data/ holds the CSV behind each plot
src/prep/   pipeline scripts 00-06 in run order (00_download_acs ... 06_load_supabase),
            plus shared modules; reference/release_dates.csv has the ACS release dates
src/eda/    plots and report scripts, and lookup.py (censors the test period)
src/model/  01-02 model evaluation (baseline vs logistic regression vs trees); 03-09 follow-up analyses and the final refit, plus shared modules:
              store_prep.py  StoreFeaturePrep, the input-preparation transformer (first step of the saved Pipeline; must be importable to unpickle it)
              explain.py     exact per-feature contributions and top reasons for the trees model
              impact.py      Jan-1 access-impact score (percentile ranks against a fixed reference)
              serving.py     loads models/pipeline.joblib, scores store-years, runs the startup self-check (used by 09 and the API)
              common_model.py, spec_writer.py   shared evaluation helpers; writer of docs/model_spec_d4.md
supabase/   schema.sql, the database schema
.streamlit/ Streamlit config (config.toml); secrets.toml is gitignored
.claude/    local Claude Code settings (settings.local.json is gitignored)
```

Root files: `CLAUDE.md` (project rules), `pyproject.toml` and `uv.lock` (uv environment),
`.env.example` (template for the gitignored `.env`), `.python-version`. Also gitignored: `.venv/`.

## Data

Raw data is not stored in git (`data/raw/` is gitignored). [`data/sources.yaml`](data/sources.yaml) is the manifest:
for every file it records the official download URL, the local filename, size, SHA-256, retrieval date and a
citation. [`src/prep/download_raw.py`](src/prep/download_raw.py) downloads missing files from the official URL,
falls back to the GitHub Release asset `raw-data-v2.zip` (tag `data-v2`) if that fails or serves different bytes,
and verifies the SHA-256 of every file. It exits non-zero on any mismatch and never overwrites a file silently.

| Dataset | File(s) in `data/raw/` | Source | Access |
|---|---|---|---|
| Historical SNAP Retailer Locator data, 2005-2025 | `Historical SNAP Retailer Locator Data 2005-2025.csv` | USDA FNS, [SNAP Retailer Locator data](https://www.fns.usda.gov/snap/retailer-locator/data) | Script (zip from FNS's content-delivery host; the landing page itself returns HTTP 403 to scripts) |
| Food Access Research Atlas 2010 (data + documentation) | `FoodAccessResearchAtlasData2010.xlsx`, `FoodAccessResearchAtlasDocumentation2010.pdf` | USDA ERS, [Food Access Research Atlas downloads](https://www.ers.usda.gov/data-products/food-access-research-atlas/download-the-data) | Script (zip) |
| Food Access Research Atlas 2015 (data + documentation) | `FoodAccessResearchAtlasData2015.xlsx`, `FoodAccessResearchAtlasDocumentation2015.pdf` | same page | Script (zip) |
| Large Retailer Access Map (LRAM) 2019, formerly the Food Access Research Atlas | `FoodAccessResearchAtlasData2019.xlsx` | same page | Script |
| Rural-Urban Commuting Area codes 2010, census tracts (revised 7/3/2019) | `ruca2010revised.xlsx` | USDA ERS, [RUCA codes](https://www.ers.usda.gov/data-products/rural-urban-commuting-area-codes) | Script |
| Rural-Urban Commuting Area codes 2020, census tracts | `RUCA-codes-2020-tract.xlsx` | same page | Script |
| TIGER/Line tract shapefile, 2010, NC | `tl_2010_37_tract10.*` (5 files) | U.S. Census Bureau, [TIGER/Line](https://www.census.gov/geographies/mapping-files/time-series/geo/tiger-line-file.html) | Script (zip) |
| TIGER/Line tract shapefile, 2020, NC | `tl_2020_37_tract.*` (7 files) | same page | Script (zip) |
| Proximity to a Grocery Store, Mecklenburg neighborhoods (Quality of Life Explorer) | `Proximity to a Grocery Store.csv` | [Quality of Life Explorer](https://explore.charlottenc.gov/), variable [m45](https://maps.mecklenburgcountync.gov/qol/data/meta/m45.html) | **Manual export, no stable URL**; Release fallback only |
| BLS Local Area Unemployment Statistics (LAUS), county annual averages 2006-2022 | `bls_laus/laucnty06.xlsx` ... `laucnty22.xlsx` (17 files) | U.S. Bureau of Labor Statistics, [LAUS county data](https://www.bls.gov/lau/tables.htm) | **Manual download, no stable URL**; Release fallback only |

Which files are read:
- **The pipeline (00-05)** reads the SNAP retailer CSV, both RUCA tract files, both tract shapefiles and the ACS tables below.
- **`05c_new_features.py`** also reads the three Food Access Research Atlas workbooks and the 17 BLS LAUS county files
  (`data/raw/bls_laus/`). These are candidate features tested in the pre-registered ablation and **not adopted into the frozen model**.
- **The two Atlas documentation PDFs** are documentation only; no script reads them.
- **`Proximity to a Grocery Store.csv`** (Mecklenburg only) is downloaded and verified but **not read by any script**. The dashboard does not use it.

The ZIP-level RUCA files, the 2025 SNAP-authorized Retailer Access Map and the tract relationship-file explanation were removed from
`data/raw/` and the manifest.

Hand-made reference files that are committed (they are decisions, not raw data): `data/reference/successor_overrides.csv`
(record pairs that are never ownership-change successors, each with a reason; read by `03_spells.py` and logged) and
`src/prep/reference/release_dates.csv` (release dates of the datasets, used by the feature-timing assertion in `05_features.py`).

ACS 5-year tract tables (2006-2010 through 2018-2022) are not in the manifest: `00_download_acs.py` pulls them from the
Census API into `data/raw/acs/` and records each vintage's release date and source in `data/raw/acs/manifest.json`
(it needs a free [Census API key](https://api.census.gov/data/key_signup.html) in `.env` as `CENSUS_API_KEY`).

### Fallback release (maintainers)

The QOL export and the BLS files have no stable URL and any official file can be re-issued upstream, so a `data-v2` release (v1 lacked the BLS files) holds a flat
zip of every file in the manifest. The repository must be pushed first (`git push -u origin main`); then, from PowerShell
at the repository root:

```powershell
# the zip goes to the temp folder, not the repo, so it cannot be committed by accident
# flat zip: the 17 BLS files from data\raw\bls_laus go at the zip root too (download_raw.py matches members by file name)
$files = @(Get-ChildItem data\raw -File | Where-Object { $_.Name -ne '.gitkeep' }) + @(Get-ChildItem data\raw\bls_laus -File)
$files | Compress-Archive -DestinationPath "$env:TEMP\raw-data-v2.zip" -Force
gh release create data-v2 "$env:TEMP\raw-data-v2.zip" --repo jrdn-sentosa/snap-grocery-exits-nc --title "Raw data v2" --notes "Raw inputs for the SNAP grocery exits project: a flat zip of the 38 files listed in data/sources.yaml. Verify with: uv run python src/prep/download_raw.py --check"
```

The release must be public for anyone to download it without credentials. Offline, download the asset by hand and
run `uv run python src/prep/download_raw.py --fallback-zip path\to\raw-data-v2.zip`.

## Reproduce

Requires [uv](https://docs.astral.sh/uv/). Every step is a script that reads raw files and writes to `data/interim/`,
`data/processed/` or `docs/`.

```bash
uv sync

# 1. raw inputs, verified against data/sources.yaml (add --check to verify without downloading)
uv run python src/prep/download_raw.py

# 2. ACS tract tables: copy .env.example to .env and set CENSUS_API_KEY first
uv run python src/prep/00_download_acs.py

# 3. prepare the data
uv run python src/prep/01_load.py       # SNAP CSV -> NC; RUCA tract tables
uv run python src/prep/02_clean.py      # cleaning rules, all NC retailers
uv run python src/prep/03_spells.py     # authorization periods -> spells, ownership changes (reads data/reference/successor_overrides.csv)
uv run python src/prep/04_panel.py      # store-years, tracts, labels, train/validation vs reserved test split
uv run python src/prep/05_features.py   # Jan-1 features -> data/processed/store_year_*.parquet
uv run python src/prep/05b_location_gaps.py   # days each store location went without SNAP after a grocery record ended (through 2021 only)
uv run python src/prep/05c_new_features.py   # candidate features (not in the frozen model)
uv run python src/prep/05d_context_columns.py   # Jan-1 distance to the nearest other grocery (role `context`, impact score only)

# 4. reports (outcome statistics use train and validation years only)
uv run python src/eda/batch_end_profile.py
uv run python src/eda/label_rates.py
uv run python src/eda/panel_summary.py
uv run python src/eda/exit_proximity.py
uv run python src/eda/reentry_gap.py
uv run python src/eda/location_gap_report.py
uv run python src/eda/successor_revision3.py   # what the ownership-change rule revision 3 changed (needs data/reference/successor_overrides.csv)
uv run python src/eda/feature_associations.py  # docs/feature_associations.md: univariate feature vs exit_12m, training rows 2012-2018 only
uv run python src/eda/plots.py                 # figures/*.png and figures/data/*.csv (train and validation rows only)
uv run python src/eda/data_dictionary.py       # docs/data_dictionary.md (from docs/column_inventory.csv, written by 05_features.py)

# look up one store or chain; everything after 2021-12-31 is censored (lifting that needs a reason and is logged in docs/test_reservation_log.md)
uv run python src/eda/lookup.py --name "earth fare"
uv run python src/eda/lookup.py --record 740603

# 5. Model evaluation: fit on train 2012-2018, score validation 2019-2021 (the test file is never read)
uv run python src/model/01_evaluate.py         # docs/model_results.md/.csv, figures/model_pr_curves.png
uv run python src/model/02_error_analysis.py   # docs/model_error_analysis.md/.csv (needs 01 first)

# 6. Follow-up analyses and final model (frozen trees; run in this order; needs 05d to have run)
uv run python src/model/03_feature_ablation.py   # candidate-feature ablation on the rolling folds inside 2012-2018 (validation not scored)
uv run python src/model/04_fairness_variant.py   # trees with vs without tract demographic features; group false-positive rates (report only)
uv run python src/model/05_calibration.py        # calibration diagnosis of the validation predictions (docs/calibration.md)
uv run python src/model/06_risk_tiers.py         # low/medium/high tier cutoffs from training base-rate multiples (docs/risk_tiers.json)
uv run python src/model/07_explanations.py       # exact per-feature contributions and top-3 reasons, with consistency checks
uv run python src/model/08_impact_score.py       # Jan-1 access-impact score and risk x impact ranking (docs/impact_reference.json)
uv run python src/model/09_final_refit.py        # refit on 2012-2021 -> models/pipeline.joblib + models/metadata.json, spec and examples
```

`models/` is gitignored and rebuilt deterministically by `09_final_refit.py` (fixed settings, `random_state` 2026), which also rewrites
`docs/model_spec_d4.md`, `docs/model_examples_d4.json` and `docs/refit_tier_shares.md`, and asserts that the Pipeline reproduces a bare
model's predictions and that a fresh process loads the bundle and passes the self-check.

The reserved test cohorts (2022-2024) are written to `data/processed/store_year_test.parquet`. That file stays local: it is
never loaded to Supabase and no outcome statistic, plot or summary is computed from it. The prep scripts 05, 05c and 05d also compute
feature and context columns for the test rows, using only information available on January 1 of each year; no feature code reads a
label, end date or outcome column (05 carries the panel's label columns through to the file without examining them). The one direct read
of the test file for modeling is `year` and `median_hh_income`, used by `09_final_refit.py` to build the income references for the
2012-2024 cohorts, logged in [`docs/test_reservation_log.md`](docs/test_reservation_log.md). The test years are evaluated once, after all modeling choices are fixed.

## Prediction API

- **API (canonical):** https://jrdn-sentosa--snap-grocery-exits-api.us-east.modal.run
- **Interactive docs:** https://jrdn-sentosa--snap-grocery-exits-api.us-east.modal.run/docs

Deploying from another Modal workspace gives a different URL (`https://<modal-workspace>--snap-grocery-exits-api.us-east.modal.run`).
- **Endpoints:** `GET /health` (startup self-check result), `GET /model-info` (bundle metadata and the model's limits),
  `POST /predict`

The request and response contract, input validation rules and examples are in
[`docs/model_spec_d4.md`](docs/model_spec_d4.md) and [`docs/model_examples_d4.json`](docs/model_examples_d4.json).

**Scoring.** [`app/api.py`](app/api.py) is a FastAPI app built on `serving.Bundle` (`src/model/serving.py`) and reimplements no
scoring. At startup it loads `models/pipeline.joblib` and runs `Bundle.self_check()`. `POST /predict` answers 503 until the check
passes, and `/health` reports the result and any failure messages.

**Requests.** `POST /predict` takes a JSON array of 1-1000 store-year records. Each record has every key in
`store_prep.FIELD_RULES`: `year` (the cohort year), the 20 inputs (`median_hh_income` in dollars) and
`dist_other_grocery_jan1_mi`. `null` is allowed only where the rule permits it.

**Responses.** For each record the API returns `raw_score`, `probability`, `tier`, `impact`, `priority` and `reasons`, exactly as
`Bundle.score` gives them. Invalid input gets a 422 that names the field.

[`app/modal_api.py`](app/modal_api.py) serves it on Modal (HW4 pattern, `@modal.asgi_app()`):
- The image contains `store_prep.py`, `serving.py`, `explain.py` and `impact.py` and the locally built `models/pipeline.joblib`.
- It pins `scikit-learn==1.9.1` and the other versions in spec section 8.
- No secret is attached.

FastAPI is in the `api` dependency group of `pyproject.toml` (locked in `uv.lock`), so the API commands use `uv run --group api`:

```bash
# 1. build the bundle (models/ is gitignored): the Reproduce steps above, through 09_final_refit.py

# 2. run locally, then open http://127.0.0.1:8000/docs
uv run --group api fastapi dev app/api.py

# 3. deploy on Modal (one-time setup: uv run python -m modal setup)
#    on Windows, set PYTHONUTF8=1 if modal deploy shows a cp932 encoding error
uv run python -m modal deploy app/modal_api.py

# 4. verify local and deployed against the fixed examples (writes docs/api_verification.md)
uv run --group api python app/verify_api.py --deployed-url <url>   # or set API_URL in .env
```

The verifier starts a local server itself; pass `--local-url http://127.0.0.1:8000` to use one that is already running. It checks
both servers:
- `/health` must show the self-check passed.
- All 9 fixed examples must match `expected` within 1e-9, with tier and reasons matching exactly.
- All 8 `invalid_examples` must return 422 (never 500).

**CORS.** The API allows browser calls (GET and POST only, no credentials) from `http://localhost:3000` and from one more origin
read from the `FRONTEND_ORIGIN` environment variable (our Vercel domain, e.g. `https://our-app.vercel.app`, no trailing slash). The
default is the inert placeholder `https://placeholder.invalid`. To set it on Modal, add it to the `@app.function` in
`app/modal_api.py` (`modal.Secret.from_dict({"FRONTEND_ORIGIN": ...})`; it is not a secret) and redeploy.

The verifier also starts a throwaway local server with `MODEL_DIR` pointing at an empty temporary folder and checks that
`/health` reports `self_check_passed = false` and that `POST /predict` returns 503, never 500. The deployed app is not touched for this.

The latest run is in [`docs/api_verification.md`](docs/api_verification.md): **PASS** locally and deployed, with 9/9 examples
identical to `expected` and 8/8 invalid requests rejected with 422.

## Dashboard (Supabase, Streamlit, Modal)

The dashboard shows data through 2021-12-31 only (train and validation cohorts; the 2022-2024 test cohorts are reserved and
never loaded). It reads from Supabase with the publishable key and refuses to run with a secret / service-role key.

```bash
# 1. once: run supabase/schema.sql in the Supabase SQL editor (creates store_year, snap_retailers_nc, cleaning_log, data_meta, location_gap; safe to re-run)
# 2. .env needs SUPABASE_URL, SUPABASE_KEY (publishable) and SUPABASE_SERVICE_ROLE_KEY (loader only); see .env.example
uv run python src/prep/06_load_supabase.py --dry-run   # check the tables without touching Supabase
uv run python src/prep/06_load_supabase.py             # load; run it again and it inserts 0 rows
uv run python src/prep/06_load_supabase.py --replace   # after the labels or the rule change: delete the rows first, then load
uv run python src/prep/06_load_supabase.py --tables location_gap   # load only some tables (comma-separated)
uv run python -m streamlit run app/streamlit_app.py    # http://localhost:8501
```

Deploy on Modal (the secret holds only the URL and the publishable key, never the service-role key):

```bash
uv run python -m modal setup
uv run python -m modal secret create snap-supabase SUPABASE_URL=https://<project>.supabase.co SUPABASE_KEY=<publishable key>
uv run python -m modal deploy app/modal_app.py
```

Windows: if Smart App Control blocks an .exe launcher, use `python -m <tool>` instead.
