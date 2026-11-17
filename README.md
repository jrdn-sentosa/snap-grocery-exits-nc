# Predicting SNAP Grocery Store Exits in North Carolina

Using only information available on January 1 of each year, can we predict which SNAP-authorized grocery
stores in North Carolina will lose SNAP authorization within the next 12 months more accurately than the
historical exit rate for their store type? Charlotte-Mecklenburg is the focus area. Cohorts are 2008-2024
with a fixed chronological split (train 2008-2018, validation 2019-2021, test 2022-2024, reserved).

Project rules, labels and feature-timing rules are in [`CLAUDE.md`](CLAUDE.md); the cleaning log is in
[`docs/cleaning_log.md`](docs/cleaning_log.md). The D2 data note is [`docs/data_note_d2.md`](docs/data_note_d2.md).
D3 model results are in [`docs/model_results.md`](docs/model_results.md) and
[`docs/model_error_analysis.md`](docs/model_error_analysis.md); the D3 model note is
[`docs/model_note_d3.md`](docs/model_note_d3.md). Post-D3 fixes and their effect on the results are in
[`docs/changes_since_d3.md`](docs/changes_since_d3.md). The D4 prediction API is described under
[Prediction API (D4)](#prediction-api-d4).

**Live API:** https://hgmccall--snap-grocery-exits-api.us-east.modal.run ·
**Docs:** https://hgmccall--snap-grocery-exits-api.us-east.modal.run/docs

## Repository structure

```
app/        Streamlit dashboard (streamlit_app.py, deployed by modal_app.py) and the D4
            prediction API (api.py, FastAPI; deployed by modal_api.py)
data/       sources.yaml: every raw file with its download URL and SHA-256 checksum
  raw/        downloaded source files (gitignored; fetched by src/prep/download_raw.py)
  interim/    cleaned retailer, spell and panel tables (gitignored; rebuilt by scripts)
  processed/  store-year train/validation and reserved test files (gitignored; rebuilt)
  reference/  successor_overrides.csv, the committed decision list of non-successor pairs
docs/       cleaning log, data dictionary, label-rule revisions, batch/gap/feature-association
            reports, plot interpretations, D1 proposal, test-reservation log
figures/    EDA plots (PNG); figures/data/ holds the CSV behind each plot
src/prep/   pipeline scripts 00-06 in run order (00_download_acs ... 06_load_supabase),
            plus shared modules; reference/release_dates.csv has the ACS release dates
src/eda/    plots and report scripts, and lookup.py (censors the test period)
src/model/  D3 model evaluation: store-type baseline vs logistic regression vs gradient-boosted trees;
            D4: transformers.py (custom preprocessing), 04_fit_final.py, 05_verify_api.py
models/     exit_model.joblib (the fitted D4 Pipeline, committed) and exit_model.json (its metadata)
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

Not every file in the manifest is used yet. The pipeline reads the SNAP retailer CSV, the two RUCA tract files and the two
tract shapefiles (plus the ACS tables below). The three Food Access Research Atlas workbooks, their two documentation PDFs and
`Proximity to a Grocery Store.csv` are downloaded and verified but **not read by any script** (the Atlas features are deferred;
the Charlotte proximity file covers Mecklenburg only). The ZIP-level RUCA files, the 2025 SNAP-authorized Retailer Access Map and
the tract relationship-file explanation were removed from `data/raw/` and the manifest.

Hand-made reference files that are committed (they are decisions, not raw data): `data/reference/successor_overrides.csv`
(record pairs that are never ownership-change successors, each with a reason; read by `03_spells.py` and logged) and
`src/prep/reference/release_dates.csv` (release dates of the datasets, used by the feature-timing assertion in `05_features.py`).

ACS 5-year tract tables (2006-2010 through 2018-2022) are not in the manifest: `00_download_acs.py` pulls them from the
Census API into `data/raw/acs/` and records each vintage's release date and source in `data/raw/acs/manifest.json`
(it needs a free [Census API key](https://api.census.gov/data/key_signup.html) in `.env` as `CENSUS_API_KEY`).

### Fallback release (maintainers)

The QOL export has no stable URL and any official file can be re-issued upstream, so a `data-v2` release (v1 lacked the BLS files) holds a flat
zip of every file in the manifest. The repository must be pushed first (`git push -u origin main`); then, from PowerShell
at the repository root:

```powershell
# the zip goes to the temp folder, not the repo, so it cannot be committed by accident
# flat zip: the 17 BLS files from data\raw\bls_laus go at the zip root too (download_raw.py matches members by file name)
$files = @(Get-ChildItem data\raw -File | Where-Object { $_.Name -ne '.gitkeep' }) + @(Get-ChildItem data\raw\bls_laus -File)
$files | Compress-Archive -DestinationPath "$env:TEMP\raw-data-v2.zip" -Force
gh release create data-v2 "$env:TEMP\raw-data-v2.zip" --repo jrdn-sentosa/snap-grocery-exits-nc --title "Raw data v2" --notes "Raw inputs for the SNAP grocery exits project: a flat zip of the 38 files listed in data/sources.yaml. Verify with: uv run python src/prep/download_raw.py --check"
```

The release must be public for graders to download it without credentials. Offline, download the asset by hand and
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

# 4. reports (outcome statistics use train and validation years only)
uv run python src/eda/batch_end_profile.py
uv run python src/eda/label_rates.py
uv run python src/eda/panel_summary.py
uv run python src/eda/exit_proximity.py
uv run python src/eda/reentry_gap.py
uv run python src/eda/location_gap_report.py
uv run python src/eda/successor_revision3.py   # what the ownership-change rule revision 3 changed (needs data/reference/successor_overrides.csv)
uv run python src/eda/plots.py                 # figures/*.png and figures/data/*.csv (train and validation rows only)
uv run python src/eda/data_dictionary.py       # docs/data_dictionary.md (from docs/column_inventory.csv, written by 05_features.py)

# look up one store or chain; everything after 2021-12-31 is censored (lifting that needs a reason and is logged in docs/test_reservation_log.md)
uv run python src/eda/lookup.py --name "earth fare"
uv run python src/eda/lookup.py --record 740603

# 5. D3 model evaluation: fit on train 2012-2018, score validation 2019-2021 (the test file is never read)
uv run python src/model/01_evaluate.py         # docs/model_results.md/.csv, figures/model_pr_curves.png
uv run python src/model/02_error_analysis.py   # docs/model_error_analysis.md/.csv (needs 01 first)
```

The reserved test cohorts (2022-2024) are written to `data/processed/store_year_test.parquet`. That file stays local: it is
never loaded to Supabase and no outcome statistic, plot or summary is computed from it.

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

## Prediction API (D4)

- **API:** https://hgmccall--snap-grocery-exits-api.us-east.modal.run
- **Interactive docs:** https://hgmccall--snap-grocery-exits-api.us-east.modal.run/docs
- **Endpoints:** `GET /health`, `GET /model-info`, `POST /predict`.

The API serves the frozen D4 model: gradient-boosted trees for `exit_12m` (learning rate 0.1, `max_leaf_nodes` 2,
`min_samples_leaf` 100, l2 0, 300 iterations), fit on train cohorts 2012-2018. Its validation PR-AUC is 0.149, the
same as in `docs/model_results.md`. It is saved as one scikit-learn Pipeline:
`StoreYearPreprocessor` ([`src/model/transformers.py`](src/model/transformers.py)) followed by
`HistGradientBoostingClassifier`.

The transformer does all the preprocessing:
- It keeps only the inventory feature columns and refuses `year`, `qa_*`, `impact_*`, `exit_*` and `bias_*` columns.
- It treats `store_type` as a categorical limited to the five grocery types.
- It median-imputes `unemployment_rate`, with the median fitted on the training rows.
- It converts `median_hh_income` to the store's percentile within its cohort year, as D3/D4 did. To do that for a single
  request it stores each cohort's income values (2012-2021; feature values only, no outcomes). Each request therefore
  carries a `cohort_year`, which is used only to look up that reference and is never a model feature. Cohorts after 2021
  are rejected.

`POST /predict` takes `{"records": [...]}` with 1-1000 store-year records containing the raw Jan-1 features, plus an
optional `record_id`. Shares such as `pct_poverty` are proportions from 0 to 1. Missing values are sent as `null`.
Unknown fields are rejected. The API reads no database and has no secrets.

**Model file.** `models/exit_model.joblib` is committed (134 KB), so the API runs and deploys without rebuilding the
data. `models/exit_model.json` records the scikit-learn version (1.9.1), features, training rows (14,982 / 632 exits),
validation PR-AUC and the file's SHA-256. To rebuild it (needs `data/processed/store_year_trainval.parquet` from the
Reproduce steps above):

```bash
uv run python src/model/04_fit_final.py   # refits and asserts the result equals 01_evaluate's model and docs/model_results.csv
```

The rebuild is deterministic: the same data and package versions give a byte-identical file.

```bash
# run the API locally (then open http://127.0.0.1:8000/docs); `uv run python -m fastapi dev app/api.py` also works
uv run fastapi dev app/api.py

# deploy on Modal (a separate app from the dashboard; no secret needed). The image pins scikit-learn,
# pandas, numpy and joblib to the versions in models/exit_model.json
uv run python -m modal setup              # once per machine
uv run python -m modal deploy app/modal_api.py

# check that the deployed API matches the local Pipeline (writes docs/api_verification.md)
uv run python src/model/05_verify_api.py                                  # deployed URL
uv run python src/model/05_verify_api.py --url http://127.0.0.1:8000      # or a local server
```

[`docs/api_verification.md`](docs/api_verification.md) shows the latest check: the deployed API returned the same
probability as the local Pipeline for all 20 validation store-years, bit for bit.
