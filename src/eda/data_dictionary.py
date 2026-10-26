"""Generate docs/data_dictionary.md.

Reads : docs/column_inventory.csv      (written by 05_features.py: column, dtype, role, % missing by split)
        data/interim/retailers_nc_clean.parquet   (for the second table's columns and missingness)
Writes: docs/data_dictionary.md

The type, source, definition and units text below is hand-written; the column list, dtype, role and
missingness come from the data. The script stops if a column in either table has no definition, so the
dictionary cannot silently fall behind the data. Missingness is shown for train and validation only
(for the retailers table: all periods, descriptive store attributes; end_date is not summarized because a
blank end date means "still authorized" and an all-years share would describe the reserved test years).
"""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "prep"))
from common import DOCS, INTERIM, ensure_dirs  # noqa: E402

FNS = "USDA FNS SNAP Retailer Locator (01-03)"
ACS = "ACS 5-year, Census API (00, 05)"
TIGER = "Census TIGER/Line tract shapefiles (04, 05)"

# column -> (source, definition, units / allowed values)
STORE_YEAR = {
    "record_id": (FNS, "USDA's store identifier ('Record ID'). One Record ID can have several authorization periods; with `year` it is unique.", "positive integer"),
    "spell_id": ("derived, 03_spells", "Continuous authorization spell of the Record ID: `record_id-spell number`. Periods of the same Record ID separated by 90 days or less are one spell; a longer gap starts a new spell.", "text, e.g. `123456-1`"),
    "year": ("derived, 04_panel", "Cohort year t: the store's spell is active on Jan 1 of t. It is only the cohort index and the split key; it is never a model feature, nor any transform of it.", "integer 2008-2021 in this file"),
    "split": ("derived, 04_panel", "Fixed chronological split of the cohort year.", "`train` (2008-2018), `validation` (2019-2021); `test` (2022-2024) lives in a separate, reserved file"),
    "store_type": (FNS, "Store type of the authorization period in force on Jan 1 of t (a store can change type between periods).", "Supermarket, Super Store, Large Grocery Store, Medium Grocery Store, Small Grocery Store"),
    "store_age_years": ("derived, 05_features", "Years from the spell's authorization date to Jan 1 of t. Missing when the true start is unknown (USDA placeholder date 1/1/1930, see `auth_date_placeholder`).", "years, >= 0"),
    "auth_date_placeholder": (FNS, "True if the spell's first period carried the USDA placeholder authorization date 1/1/1930. Such stores are treated as authorized before the data window.", "true / false"),
    "n_prior_spells_same_id": ("derived, 03/05", "Number of earlier spells of the same Record ID (re-authorizations after a gap of more than 90 days).", "integer >= 0 (max 2)"),
    "n_prior_ownership_changes": ("derived, 03/05", "Ownership transfers in this store's lineage whose predecessor ended before Jan 1 of t. A transfer = a different Record ID at the same standardized address authorized from 30 days before to 90 days after the predecessor's end.", "integer >= 0 (max 6)"),
    "chain_size": ("derived, 05_features", "Number of authorization periods of any store type, active on Jan 1 of t anywhere in NC, whose standardized store name (`name_std`: upper case, no accents or punctuation, store numbers and INC/LLC removed) equals this store's. **Caveat: it is name-based, not ownership-based.** Generic names ('Mi Tienda', 'Food Mart') merge unrelated stores, and name variants split one chain, so treat it as a rough proxy (maximum 512); consider a log transform in D3.", "integer >= 1; missing when the name is empty"),
    "n_grocery_05mi": ("derived, 05_features", "Other grocery-type stores authorized on Jan 1 of t within 0.5 mile (distance in EPSG:32119 State Plane metres); excludes the store itself.", "integer >= 0"),
    "n_grocery_1mi": ("derived, 05_features", "Same as `n_grocery_05mi`, within 1 mile.", "integer >= 0"),
    "n_convenience_1mi": ("derived, 05_features", "Convenience stores authorized on Jan 1 of t within 1 mile. ('Combination Grocery/Other' stores count as neither grocery nor convenience.)", "integer >= 0"),
    "convenience_to_grocery_ratio_1mi": ("derived, 05_features", "`n_convenience_1mi / (n_grocery_1mi + 1)`; the +1 is the store itself, so the ratio is defined with no neighbours. A partial food-swamp indicator.", "ratio >= 0 (max 23)"),
    "n_grocery_ends_1mi_prior12m": ("derived, 05_features", "Grocery-type authorization periods of OTHER stores within 1 mile that ended in the previous calendar year (Jan 1 to Dec 31 of t-1). Counts every end, including ownership transfers, because whether a late-December end was a transfer is not knowable on Jan 1.", "integer >= 0"),
    "acs_population": (ACS + ", B01003", "Total population of the store's census tract, from the latest ACS 5-year vintage released before Jan 1 of t (tract boundaries matched to the vintage). Missing for t <= 2011 (no vintage was out yet).", "persons"),
    "pop_density_sqmi": (ACS + " + " + TIGER, "`acs_population` divided by the tract's land area (TIGER ALAND, same tract vintage). Missing for zero-land-area tracts.", "persons per square mile"),
    "pct_poverty": (ACS + ", B17001", "Share of people with poverty status determined who are below the poverty level.", "share 0-1"),
    "median_hh_income": (ACS + ", B19013", "Tract median household income. **Top-coded:** the Census Bureau reports 250,001 for tracts at or above the cap, so a value of 250001 means 'at least $250,000'. Dollars are inflation-adjusted to the vintage's last year (2010 dollars for 2006-2010 ... 2022 dollars for 2018-2022), so levels are not comparable across vintages; compare within a cohort year (e.g. quintiles).", "US dollars; 250001 = top code"),
    "pct_no_vehicle": (ACS + ", B25044", "Share of occupied housing units with no vehicle available (owner + renter).", "share 0-1"),
    "pct_snap_hh": (ACS + ", B22001", "Share of households that received SNAP in the past 12 months.", "share 0-1"),
    "pct_renter": (ACS + ", B25003", "Share of occupied housing units that are renter-occupied.", "share 0-1"),
    "pct_age_65_plus": (ACS + ", B01001", "Share of the tract population aged 65 and over (male and female cells 65-66 through 85+).", "share 0-1"),
    "unemployment_rate": (ACS + ", B23025", "Unemployed civilians as a share of the civilian labor force. **Gap: missing for the entire 2012 cohort**, because the 2006-2010 vintage (the only one usable in 2012) does not publish table B23025; present from the 2013 cohort on.", "share 0-1"),
    "bias_pct_hispanic": (ACS + ", B03002", "Share of tract population that is Hispanic or Latino. For group error analysis (D3) and the bias discussion (D6) only.", "share 0-1"),
    "bias_pct_white_nh": (ACS + ", B03002", "Share non-Hispanic White alone. Bias analysis only.", "share 0-1"),
    "bias_pct_black_nh": (ACS + ", B03002", "Share non-Hispanic Black or African American alone. Bias analysis only.", "share 0-1"),
    "bias_pct_asian_nh": (ACS + ", B03002", "Share non-Hispanic Asian alone. Bias analysis only.", "share 0-1"),
    "bias_pct_aian_nh": (ACS + ", B03002", "Share non-Hispanic American Indian and Alaska Native alone. Bias analysis only.", "share 0-1"),
    "bias_pct_other_multi_nh": (ACS + ", B03002", "Share non-Hispanic Native Hawaiian/Pacific Islander, some other race, or two or more races. Bias analysis only.", "share 0-1"),
    "acs_available": ("derived, 05_features", "True when an ACS vintage released before Jan 1 of t exists. Identical to `year >= 2012`, i.e. a calendar-year proxy: never a feature.", "true / false"),
    "acs_vintage": (ACS, "Label of the ACS 5-year vintage used for this row (the latest released before Jan 1 of t).", "text, e.g. `2015-2019`; missing for t <= 2011"),
    "acs_release_date": ("data/raw/acs/manifest.json (cited in src/prep/reference/release_dates.csv)", "Census Bureau release date of that vintage's detailed tables, checked to precede Jan 1 of t.", "date"),
    "acs_tract_vintage": (ACS, "Which tract boundaries the ACS vintage uses, measured by GEOID match in 00_download_acs.py.", "`2010` (cohorts 2012-2022) or `2020` (2023-2024)"),
    "store_name": (FNS, "Store name of the period in force on Jan 1 of t (whitespace-cleaned, original capitalization).", "text"),
    "county": (FNS, "USDA county of the store (upper case). Used to separate Mecklenburg from the rest of NC.", "one of NC's 100 counties"),
    "latitude": (FNS, "Store latitude as supplied by USDA; 02_clean blanks values outside a box around NC and (0,0).", "decimal degrees"),
    "longitude": (FNS, "Store longitude, same handling as latitude.", "decimal degrees"),
    "tract_geoid_2010": (TIGER, "2010 census tract containing the store (point-in-polygon, `tl_2010_37_tract10`).", "11-digit GEOID text"),
    "tract_geoid_2020": (TIGER, "2020 census tract containing the store (`tl_2020_37_tract`).", "11-digit GEOID text"),
    "exit_12m": ("derived, 03/04", "**Primary label.** 1 if the store's spell ends in [Jan 1 t, Dec 31 t] and the end is a true exit (not an ownership change); batch ends are included. Otherwise 0.", "0 / 1"),
    "exit_12m_strict": ("derived, 03/04", "**Strict label.** Same as `exit_12m`, except that a batch-end exit makes the label MISSING (the row is excluded from strict analyses; it is not coded 0, because those stores did lose authorization). Compare models on identical rows.", "0 / 1 / missing"),
    "exit_is_batch": ("derived, 03/04", "For exits only: whether the end was a `qa_batch_end` (an administrative batch day). Missing for non-exits. Never a feature.", "true / false / missing"),
    "impact_dist_nearest_other_grocery_mi": ("derived, 04_panel", "For exits (`exit_12m` = 1) only: miles from the exiting store to the nearest OTHER grocery-type store still authorized after the exit date (stores ending the same day excluded). Measured at the exit, after Jan 1, so never a predictor.", "miles >= 0; missing for non-exits"),
    "qa_coord_invalid": ("derived, 02/04", "The store's coordinates were invalid and blanked (no tract, no distance).", "true / false"),
    "qa_tract_unmatched": ("derived, 04_panel", "Valid coordinates but no tract matched.", "true / false"),
    "qa_ownership_change_in_year": ("derived, 03/04", "The spell ended in year t as an ownership change (label 0 in both labels).", "true / false"),
    "qa_spell_end": ("derived, 03/04", "End date of the spell, kept to audit the labels. An outcome date, never a feature.", "date"),
}

# columns of retailers_nc_clean.parquet (all NC SNAP retailers, one row per authorization period)
RETAILERS = {
    "record_id": ("USDA Record ID.", "integer"),
    "period_seq": ("1-based order of the period within its Record ID (by authorization date).", "integer >= 1"),
    "store_name": ("Store name, whitespace-cleaned.", "text"),
    "name_std": ("Standardized name for chain matching: upper case, accents/punctuation/store numbers/INC-LLC removed.", "text"),
    "store_type": ("USDA store type of the period.", "16 USDA types, e.g. Supermarket, Convenience Store, Combination Grocery/Other"),
    "is_grocery": ("True for the five grocery types (Supermarket, Super Store, Large/Medium/Small Grocery Store).", "true / false"),
    "is_convenience": ("True for Convenience Store.", "true / false"),
    "street_number": ("Street number as supplied; blank for 99 periods (their `address_key` is missing).", "text"),
    "street_name": ("Street name as supplied.", "text"),
    "additional_address": ("Suite / unit text; mostly blank and not used for address matching.", "text"),
    "address_std": ("Street number + street name with USPS abbreviations and no punctuation.", "text, e.g. `123 MAIN ST`"),
    "address_key": ("`address_std|zip5`: the storefront identity used to link ownership changes. Missing when the street number is blank.", "text"),
    "city": ("City, upper case, near-duplicate spellings merged within a ZIP (e.g. WINSTONSALEM -> WINSTON SALEM).", "text"),
    "city_raw": ("City exactly as supplied (whitespace-trimmed).", "text"),
    "zip5": ("First five digits of the ZIP code.", "5-digit text"),
    "zip4": ("ZIP+4 extension when it is exactly four digits.", "4-digit text"),
    "county": ("County, upper case.", "one of NC's 100 counties"),
    "latitude": ("Latitude; blanked when outside the NC box or (0,0).", "decimal degrees"),
    "longitude": ("Longitude; same handling.", "decimal degrees"),
    "auth_date": ("Authorization date of the period; blank for the 1/1/1930 placeholder.", "date"),
    "auth_date_placeholder": ("True when the supplied authorization date was the placeholder 1/1/1930.", "true / false"),
    "end_date": ("Date the authorization ended; **blank = still authorized at the data cut-off (Dec 2025)**. In the Supabase table, end dates after 2021-12-31 are blanked so the dashboard cannot show test-period exits (data through 2021-12-31).", "date"),
    "qa_batch_end": ("End date shared by at least 40 NC retailers (all types) on one day: an administrative batch action. Threshold = 99th percentile of daily end counts, computed from end dates through 2021-12-31 only.", "true / false"),
    "qa_coord_invalid": ("Coordinates were invalid and blanked.", "true / false"),
    "qa_name_malformed": ("Store name has control characters, no letters, or one character.", "true / false"),
    "qa_zero_length_period": ("End date equals authorization date.", "true / false"),
    "qa_end_before_auth": ("End date earlier than authorization date (none occur).", "true / false"),
}

TYPE_NAMES = {
    "int64": "integer", "Int64": "integer (nullable)", "int8": "0/1 integer", "Int8": "0/1 integer (nullable)",
    "float64": "decimal", "bool": "boolean", "boolean": "boolean (nullable)", "str": "text", "object": "text",
}
ROLE_ORDER = ["id", "label", "feature", "grouping", "bias_", "qa_", "impact_"]
ROLE_TEXT = {
    "id": "identifies a row; `year` and `split` are indexes, never features",
    "label": "the outcome",
    "feature": "the only columns a model may use (known on Jan 1 of t)",
    "grouping": "slices results (county, tract, coordinates, ACS vintage metadata); never a feature",
    "bias_": "race/ethnicity for group error analysis (D3) and the bias discussion (D6); never a feature",
    "qa_": "data-quality or outcome bookkeeping; never a feature",
    "impact_": "measured at the exit, after Jan 1; never a feature",
}


def dtype_name(dtype: str) -> str:
    if dtype.startswith("datetime64"):
        return "date"
    return TYPE_NAMES.get(dtype, dtype)


def esc(s: str) -> str:
    return str(s).replace("|", "\\|")


def main() -> None:
    ensure_dirs()
    inv = pd.read_csv(DOCS / "column_inventory.csv")
    missing_defs = sorted(set(inv["column"]) - set(STORE_YEAR))
    stale = sorted(set(STORE_YEAR) - set(inv["column"]))
    if missing_defs or stale:
        raise SystemExit(f"data dictionary out of sync with column_inventory.csv: undefined={missing_defs}, no longer in data={stale}")
    ret = pd.read_parquet(INTERIM / "retailers_nc_clean.parquet")
    r_missing = sorted(set(ret.columns) - set(RETAILERS))
    r_stale = sorted(set(RETAILERS) - set(ret.columns))
    if r_missing or r_stale:
        raise SystemExit(f"retailers table out of sync: undefined={r_missing}, no longer in data={r_stale}")

    out = [
        "# Data dictionary", "",
        "Generated by `src/eda/data_dictionary.py` from `docs/column_inventory.csv` (written by `05_features.py`); do not edit by hand.", "",
        "- **Table 1, `store_year`** (`data/processed/store_year_trainval.parquet`, and `store_year_test.parquet` with the same columns for the reserved 2022-2024 cohorts): one row per grocery-type Record ID authorized on Jan 1 of year t.",
        "- **Table 2, `snap_retailers_nc`** (`data/interim/retailers_nc_clean.parquet`): every NC SNAP retailer of every store type, one row per authorization period. Convenience stores live here (they feed the convenience-to-grocery ratio) even though they are never observations.", "",
        "## Read this first", "",
        "**Labels (about the 12 months of year t).**",
        "- `exit_12m` (primary): 1 if a true exit (an end that is not an ownership change) falls in [Jan 1 t, Dec 31 t], batch ends included.",
        "- `exit_12m_strict`: same, but a batch-end exit makes the label missing, so those rows drop out of strict analyses. The historical-rate baseline and every model must be evaluated on the same rows.",
        "- `exit_is_batch`: for exits only, whether the end was an administrative batch day.",
        "- An **ownership change** (not an exit) is a different Record ID at the same standardized address, authorized from 30 days before to 90 days after the end date. Same-Record-ID periods 90 days apart or less form one spell.", "",
        "**Known gaps and caveats.**",
        "- **ACS starts with the 2012 cohort.** The first usable vintage (2006-2010) was released 2011-12-08, so every 2008-2011 row has missing ACS features (33.6% of train rows). Compare baseline and models on 2012 onward (14,982 train store-years).",
        "- **Unemployment gap.** `unemployment_rate` is missing for the entire 2012 cohort (the 2006-2010 vintage has no table B23025): 13.8% of the train rows from 2012 on.",
        "- **Income top-code.** `median_hh_income` is capped at 250,001 by the Census Bureau, and dollars differ by vintage; use within-year ranks.",
        "- **Chain-size caveat.** `chain_size` counts same-name stores, so generic names inflate it and spelling variants split chains.",
        "- ACS 'not available' sentinel codes (negative numbers such as -666666666) are converted to missing; 423 such cells exist in the vintage files used.",
        "- Not in this table: RUCA codes (a descriptive urban/rural grouping kept in `data/interim/panel_*.parquet` until their release dates allow use as a feature) and Food Access Atlas features (deferred).",
        "- `year` is the cohort index only. It is not a feature, and neither is anything that is a function of it (such as `acs_available`).", "",
        "**Roles** (the `role` column of `docs/column_inventory.csv`):", "",
        "| role | meaning |", "|---|---|",
        *[f"| `{r}` | {ROLE_TEXT[r]} |" for r in ROLE_ORDER], "",
        "## Table 1: `store_year`", "",
        "Missingness is the percent of rows with a missing value in the train split (2008-2018) and the validation split (2019-2021).", "",
    ]
    inv["order"] = inv["role"].map({r: i for i, r in enumerate(ROLE_ORDER)})
    for role, grp in inv.sort_values("order", kind="stable").groupby("order", sort=True):
        role_name = ROLE_ORDER[int(role)]
        out += [f"### Role: `{role_name}`", "", "| column | type | source | definition | units / allowed values | % missing (train / validation) |", "|---|---|---|---|---|---|"]
        for r in grp.itertuples():
            src, definition, units = STORE_YEAR[r.column]
            out.append(f"| `{r.column}` | {dtype_name(r.dtype)} | {esc(src)} | {esc(definition)} | {esc(units)} | {r.missing_pct_train:.1f} / {r.missing_pct_validation:.1f} |")
        out.append("")

    out += ["## Table 2: `snap_retailers_nc`", "",
            "Not modelled: its columns are descriptive attributes (role `attribute`) or `qa_` flags. Source for every column: USDA FNS SNAP Retailer Locator, cleaned in `02_clean.py` "
            "(every rule is in `docs/cleaning_log.md`). Missingness is over all periods.", "",
            "| column | type | definition | units / allowed values | % missing |", "|---|---|---|---|---|"]
    for col in ret.columns:
        definition, units = RETAILERS[col]
        pct = "n/a (blank = still authorized)" if col == "end_date" else f"{100 * ret[col].isna().mean():.1f}"
        out.append(f"| `{col}` | {dtype_name(str(ret[col].dtype))} | {esc(definition)} | {esc(units)} | {pct} |")
    out.append("")
    (DOCS / "data_dictionary.md").write_text("\n".join(out), encoding="utf-8")
    print(f"Wrote {DOCS / 'data_dictionary.md'}: {len(inv)} store_year columns, {len(ret.columns)} retailer columns")


if __name__ == "__main__":
    main()
