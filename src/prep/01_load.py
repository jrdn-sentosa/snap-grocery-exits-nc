"""01: load the national USDA SNAP retailer CSV and keep North Carolina.

Reads : data/raw/Historical SNAP Retailer Locator Data 2005-2025.csv
Writes: data/interim/snap_retailers_nc_raw.parquet  (NC rows, every column still a raw string)

No cleaning happens here; 02_clean.py owns every cleaning rule.
(Atlas / RUCA xlsx -> parquet conversion is deferred; 05 needs it only if time allows.)
"""

import pandas as pd

from common import INTERIM, SNAP_CSV, ensure_dirs, log_step, start_log

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


if __name__ == "__main__":
    main()
