# Predicting SNAP Grocery Store Exits in North Carolina

Using only information available on January 1 of each year, can we predict which SNAP-authorized grocery
stores in North Carolina will lose SNAP authorization within the next 12 months more accurately than the
historical exit rate for their store type? Charlotte-Mecklenburg is the focus area. Cohorts are 2008-2024
with a fixed chronological split (train 2008-2018, validation 2019-2021, test 2022-2024, reserved).

Project rules, labels and feature-timing rules are in [`CLAUDE.md`](CLAUDE.md); the cleaning log is in
[`docs/cleaning_log.md`](docs/cleaning_log.md).

## Data

Raw data is not stored in git (`data/raw/` is gitignored). [`data/sources.yaml`](data/sources.yaml) is the manifest:
for every file it records the official download URL, the local filename, size, SHA-256, retrieval date and a
citation. [`src/prep/download_raw.py`](src/prep/download_raw.py) downloads missing files from the official URL,
falls back to the GitHub Release asset `raw-data-v1.zip` (tag `data-v1`) if that fails or serves different bytes,
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

Only files the pipeline reads are kept: the ZIP-level RUCA files, the 2025 SNAP-authorized Retailer Access Map and the
tract relationship-file explanation were removed from `data/raw/` and the manifest.

ACS 5-year tract tables (2006-2010 through 2018-2022) are not in the manifest: `00_download_acs.py` pulls them from the
Census API into `data/raw/acs/` and records each vintage's release date and source in `data/raw/acs/manifest.json`
(it needs a free [Census API key](https://api.census.gov/data/key_signup.html) in `.env` as `CENSUS_API_KEY`).

### Fallback release (maintainers)

The QOL export has no stable URL and any official file can be re-issued upstream, so a `data-v1` release holds a flat
zip of every file in the manifest. The repository must be pushed first (`git push -u origin main`); then, from PowerShell
at the repository root:

```powershell
# the zip goes to the temp folder, not the repo, so it cannot be committed by accident
Get-ChildItem data\raw -File | Where-Object { $_.Name -ne '.gitkeep' } | Compress-Archive -DestinationPath "$env:TEMP\raw-data-v1.zip" -Force
gh release create data-v1 "$env:TEMP\raw-data-v1.zip" --repo jrdn-sentosa/snap-grocery-exits-nc --title "Raw data v1" --notes "Raw inputs for the SNAP grocery exits project: a flat zip of the 21 files listed in data/sources.yaml. Verify with: uv run python src/prep/download_raw.py --check"
```

The release must be public for graders to download it without credentials. Offline, download the asset by hand and
run `uv run python src/prep/download_raw.py --fallback-zip path\to\raw-data-v1.zip`.

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
# look up one store (censored after 2021-12-31; lifting that is logged in docs/test_reservation_log.md):
#   from src.eda.lookup import history
```

## Dashboard (Supabase, Streamlit, Modal)

The dashboard shows data through 2021-12-31 only (train and validation cohorts; the 2022-2024 test cohorts are reserved and
never loaded). It reads from Supabase with the publishable key and refuses to run with a secret / service-role key.

```bash
# 1. once: run supabase/schema.sql in the Supabase SQL editor (creates store_year, snap_retailers_nc, cleaning_log, data_meta, location_gap; safe to re-run)
# 2. .env needs SUPABASE_URL, SUPABASE_KEY (publishable) and SUPABASE_SERVICE_ROLE_KEY (loader only); see .env.example
uv run python src/prep/06_load_supabase.py --dry-run   # check the tables without touching Supabase
uv run python src/prep/06_load_supabase.py             # load; run it again and it inserts 0 rows
uv run streamlit run app/streamlit_app.py              # http://localhost:8501
```

Deploy on Modal (the secret holds only the URL and the publishable key, never the service-role key):

```bash
uv run modal setup
uv run modal secret create snap-supabase SUPABASE_URL=https://<project>.supabase.co SUPABASE_KEY=<publishable key>
uv run modal deploy app/modal_app.py
```
