"""01: load the national USDA SNAP retailer CSV and keep North Carolina.

Reads : data/raw/Historical SNAP Retailer Locator Data 2005-2025.csv
        data/raw/ruca2010revised.xlsx, data/raw/RUCA-codes-2020-tract.xlsx   (tract-level only: stores are
        matched to tracts by point-in-polygon, so the ZIP-level RUCA files are neither downloaded nor read)
Writes: data/interim/snap_retailers_nc_raw.parquet  (NC rows, every column still a raw string)
        data/interim/ruca_2010_tract_nc.parquet, ruca_2020_tract_nc.parquet  (NC tracts, typed)

No cleaning happens here; 02_clean.py owns every cleaning rule.
(Atlas xlsx -> parquet conversion is deferred; 05 needs it only if time allows.)
"""

import pandas as pd

from common import INTERIM, RAW, SNAP_CSV, ensure_dirs, log_step, start_log

SCRIPT = "01_load"

EXPECTED_COLUMNS = [
    "Record ID", "Store Name", "Store Type", "Street Number", "Street Name",
    "Additional Address", "City", "State", "Zip Code", "Zip4", "County",
    "Latitude", "Longitude", "Authorization Date", "End Date",
]


def main() -> None:
    ensure_dirs()
    start_log(SCRIPT)

    # utf-8-sig: the file starts with a BOM that otherwise corrupts the first header.
    # dtype=str + keep_default_na=False: a blank End Date means "still active", so no
    # value may be silently coerced to NaN or a number (e.g. ZIPs losing leading zeros).
    df = pd.read_csv(SNAP_CSV, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    if list(df.columns) != EXPECTED_COLUMNS:
        raise ValueError(f"Unexpected columns: {list(df.columns)}")
    n_all = len(df)

    # The study area is NC; other states are irrelevant to the question. Stores just across
    # the border still count as neighbours, but that is handled with NC coordinates only.
    nc = df[df["State"].str.strip().str.upper() == "NC"].reset_index(drop=True)
    log_step(
        SCRIPT, "keep_nc", "State == 'NC' (case/whitespace-insensitive)",
        "Research question is NC SNAP grocery stores", n_all, len(nc),
    )

    out = INTERIM / "snap_retailers_nc_raw.parquet"
    nc.to_parquet(out, index=False)
    print(f"Wrote {out} ({len(nc):,} rows)")

    load_ruca_tracts()


def load_ruca_tracts() -> None:
    """RUCA tract tables (USDA ERS) -> NC-only parquet, one per census-tract vintage.

    ids stay strings (leading zeros); codes become numbers. No cleaning beyond the NC filter.
    """
    # 2010 file: row 0 is an errata note, row 1 the header; 'Select State' holds the USPS abbreviation.
    r10 = pd.read_excel(RAW / "ruca2010revised.xlsx", sheet_name="Data", header=1, dtype=str, engine="calamine")
    assert r10.shape[1] == 9 and "Primary RUCA" in r10.columns[4], list(r10.columns)
    r10.columns = ["county_fips", "state", "county_name", "tract_geoid", "ruca_primary", "ruca_secondary",
                   "tract_pop", "land_area_sqmi", "pop_density"]
    nc10 = r10[r10["state"].str.strip().str.upper() == "NC"].copy()
    for c in ("ruca_primary", "tract_pop"):
        nc10[c] = pd.to_numeric(nc10[c], errors="raise").astype("int64")
    for c in ("ruca_secondary", "land_area_sqmi", "pop_density"):
        nc10[c] = pd.to_numeric(nc10[c], errors="coerce")
    nc10 = nc10.drop(columns="state").reset_index(drop=True)
    assert nc10["tract_geoid"].is_unique and nc10["tract_geoid"].str.startswith("37").all()
    nc10.to_parquet(INTERIM / "ruca_2010_tract_nc.parquet", index=False)
    log_step(SCRIPT, "ruca_2010_nc", "ruca2010revised.xlsx 'Data' sheet: keep state == NC (rows_before = all US tracts)",
             "RUCA 2010 codes are keyed by 2010 tract GEOID", len(r10), len(nc10))

    # 2020 file: row 0 is a title, row 1 the header; carries both 2020 and 2023 tract ids, we key on 2020.
    r20 = pd.read_excel(RAW / "RUCA-codes-2020-tract.xlsx", sheet_name="RUCA2020 Tract Data", header=1, dtype=str, engine="calamine")
    nc20 = r20[r20["StateFIPS20"] == "37"][
        ["TractFIPS20", "CountyName20", "PrimaryRUCA", "SecondaryRUCA", "UrbanCore", "UrbanCoreType",
         "Population", "LandArea", "PopDensity"]].copy()
    nc20.columns = ["tract_geoid", "county_name", "ruca_primary", "ruca_secondary", "urban_core",
                    "urban_core_type", "tract_pop", "land_area_sqmi", "pop_density"]
    nc20["ruca_primary"] = pd.to_numeric(nc20["ruca_primary"], errors="raise").astype("int64")
    for c in ("ruca_secondary", "tract_pop", "land_area_sqmi", "pop_density"):
        nc20[c] = pd.to_numeric(nc20[c], errors="coerce")
    nc20 = nc20.reset_index(drop=True)
    assert nc20["tract_geoid"].is_unique and nc20["tract_geoid"].str.startswith("37").all()
    nc20.to_parquet(INTERIM / "ruca_2020_tract_nc.parquet", index=False)
    log_step(SCRIPT, "ruca_2020_nc", "RUCA-codes-2020-tract.xlsx tract sheet: keep StateFIPS20 == '37' (rows_before = all US tracts)",
             "RUCA 2020 codes are keyed by 2020 tract GEOID (TractFIPS20)", len(r20), len(nc20))


if __name__ == "__main__":
    main()
