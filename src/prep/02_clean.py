"""02: clean the NC SNAP retailer authorization periods.

Reads : data/interim/snap_retailers_nc_raw.parquet
Writes: data/interim/retailers_nc_clean.parquet
        (ALL NC retailers, all store types, one row per authorization period; the
         convenience stores are needed later for the convenience-to-grocery ratio)

Every rule is logged with row counts via common.log_step (-> docs/cleaning_log.md).
Columns prefixed qa_ are data-quality flags; they are excluded from model features in 05.

Test-set discipline: nothing here summarizes outcomes for 2022-2024. The qa_batch_end
threshold is learned only from end dates through DATA_THROUGH (2021-12-31) and then applied
as a fixed number to every row; counts logged for it also stop at DATA_THROUGH.
"""

import math
import re
import unicodedata
from difflib import SequenceMatcher

import pandas as pd

from common import (
    CONVENIENCE_TYPE, DATA_THROUGH, GROCERY_TYPES, INTERIM, ensure_dirs, log_step, start_log,
)

SCRIPT = "02_clean"

KNOWN_STORE_TYPES = {
    "Convenience Store", "Combination Grocery/Other", "Supermarket", "Small Grocery Store",
    "Super Store", "Medium Grocery Store", "Seafood Specialty", "Meat/Poultry Specialty",
    "Farmers' Market", "Large Grocery Store", "Fruits/Veg Specialty", "Bakery Specialty",
    "Delivery Route", "Unknown", "Food Buying Co-op", "Military Commissary",
}
PLACEHOLDER_AUTH_DATE = pd.Timestamp("1930-01-01")
# Loose bounding box around NC (a few tenths of a degree of slack); catches (0, 0) and strays.
NC_LAT = (33.7, 36.7)
NC_LON = (-84.5, -75.3)
# Quantile of the statewide daily end-date counts above which a day is an administrative batch.
BATCH_END_QUANTILE = 0.99

# USPS-style abbreviations so "MAIN STREET" and "MAIN ST" give the same address key.
ADDRESS_TOKENS = {
    "STREET": "ST", "ROAD": "RD", "AVENUE": "AVE", "BOULEVARD": "BLVD", "DRIVE": "DR",
    "HIGHWAY": "HWY", "PARKWAY": "PKWY", "LANE": "LN", "COURT": "CT", "CIRCLE": "CIR",
    "PLACE": "PL", "SQUARE": "SQ", "TRAIL": "TRL", "TERRACE": "TER", "PLAZA": "PLZ",
    "EXTENSION": "EXT", "NORTH": "N", "SOUTH": "S", "EAST": "E", "WEST": "W",
    "NORTHEAST": "NE", "NORTHWEST": "NW", "SOUTHEAST": "SE", "SOUTHWEST": "SW",
}
CITY_TOKENS = {"MT": "MOUNT", "MTN": "MOUNTAIN", "FT": "FORT"}
NAME_SUFFIX_WORDS = r"\b(INC|LLC|LTD|CORP|CORPORATION|CO)\b"


def strip_accents(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def normalize_city(raw: str) -> str:
    c = re.sub(r"[^A-Z ]", " ", raw.upper())
    return " ".join(CITY_TOKENS.get(t, t) for t in c.split())


def std_address(number: str | None, street: str) -> str | None:
    """'123' + 'Main Street' -> '123 MAIN ST'. None without a street number: a street name
    alone cannot identify a storefront, so it must not drive ownership-change matching."""
    if number is None or pd.isna(number):
        return None
    tokens = re.sub(r"[^A-Z0-9 ]", " ", street.upper()).split()
    tokens = [ADDRESS_TOKENS.get(t, t) for t in tokens]
    num = re.sub(r"[^A-Z0-9-]", "", number.upper())
    return f"{num} {' '.join(tokens)}" if num and tokens else None


def std_name(name: str) -> str:
    n = strip_accents(name).upper()
    n = re.sub(r"#\s*\d+", " ", n)            # store numbers: "WALMART #1234"
    n = re.sub(r"[^A-Z0-9 ]", " ", n)
    n = re.sub(NAME_SUFFIX_WORDS, " ", n)
    n = re.sub(r"\b\d+\b$", " ", n.strip())   # trailing bare store number
    return " ".join(n.split())


def merge_city_variants(city: pd.Series, zip5: pd.Series) -> pd.Series:
    """Within each ZIP, map minority spellings to the ZIP's most common spelling when they are
    near-identical (typos, missing space, or a truncation). Scoped to a ZIP so two genuinely
    different towns sharing a ZIP (e.g. ADVANCE / BERMUDA RUN) are never merged."""
    counts = pd.DataFrame({"zip5": zip5, "city": city}).value_counts().reset_index(name="n")
    mapping: dict[tuple[str, str], str] = {}
    for z, grp in counts.groupby("zip5"):
        grp = grp.sort_values(["n", "city"], ascending=[False, True])
        modal = grp.iloc[0]["city"]
        for other in grp.iloc[1:]["city"]:
            a, b = other.replace(" ", ""), modal.replace(" ", "")
            if SequenceMatcher(None, a, b).ratio() >= 0.8 or (len(a) >= 5 and b.startswith(a)):
                mapping[(z, other)] = modal
    return pd.Series(
        [mapping.get((z, c), c) for z, c in zip(zip5, city)], index=city.index
    )


def main() -> None:
    ensure_dirs()
    start_log(SCRIPT)
    raw = pd.read_parquet(INTERIM / "snap_retailers_nc_raw.parquet")
    n = len(raw)

    # 1. Whitespace: the export pads fields with trailing spaces and uses " " for "blank".
    #    Left as-is, a blank End Date would not read as missing and "CHARLOTTE " != "CHARLOTTE".
    stripped = raw.apply(lambda c: c.str.strip())
    changed_rows = int((stripped != raw).any(axis=1).sum())
    df = stripped.replace("", pd.NA)
    df.columns = [
        "record_id", "store_name", "store_type", "street_number", "street_name",
        "additional_address", "city", "state", "zip_code", "zip4", "county",
        "latitude", "longitude", "auth_date", "end_date",
    ]
    log_step(SCRIPT, "trim_whitespace", "strip every field; whitespace-only -> missing",
             "Export pads fields; blank End Date must read as missing (= still active)",
             n, len(df), changed_rows)

    # 2. Internal repeated spaces in names/streets break exact matching of addresses and chains.
    multi_space = (df["store_name"].str.contains(r"\s{2,}") | df["street_name"].str.contains(r"\s{2,}")).sum()
    for col in ("store_name", "street_name"):
        df[col] = df[col].str.replace(r"\s+", " ", regex=True)
    log_step(SCRIPT, "collapse_internal_spaces", "collapse runs of spaces in store_name, street_name",
             "Repeated spaces would make identical addresses/names compare unequal",
             len(df), len(df), int(multi_space))

    # 3. Record ID must be a clean integer key.
    if not df["record_id"].str.fullmatch(r"\d+").all():
        raise ValueError("Non-numeric Record ID found")
    df["record_id"] = df["record_id"].astype("int64")

    # 4. Dates. Unparseable values would silently become NaT, so count them explicitly.
    auth = pd.to_datetime(df["auth_date"], format="%m/%d/%Y", errors="coerce")
    end = pd.to_datetime(df["end_date"], format="%m/%d/%Y", errors="coerce")
    bad = int((auth.isna() & df["auth_date"].notna()).sum() + (end.isna() & df["end_date"].notna()).sum())
    df["auth_date"], df["end_date"] = auth, end
    log_step(SCRIPT, "parse_dates", "parse M/D/YYYY; unparseable -> missing",
             "Dates arrive as text; failures counted so none vanish silently",
             len(df), len(df), bad)

    # 5. 1/1/1930 is a USDA placeholder, not a real authorization date.
    ph = df["auth_date"] == PLACEHOLDER_AUTH_DATE
    df["auth_date_placeholder"] = ph
    df.loc[ph, "auth_date"] = pd.NaT
    log_step(SCRIPT, "auth_date_placeholder", "auth_date 1/1/1930 -> missing; flag auth_date_placeholder",
             "Placeholder would make store age ~95 years; true start date is unknown",
             len(df), len(df), int(ph.sum()))

    # 6. Zero-length periods (end == start) and end-before-start are quality flags, not drops;
    #    03_spells decides how to treat them.
    df["qa_zero_length_period"] = (df["end_date"] == df["auth_date"])
    df["qa_end_before_auth"] = (df["end_date"] < df["auth_date"])
    log_step(SCRIPT, "flag_odd_periods", "qa_zero_length_period (end == start), qa_end_before_auth (end < start)",
             "Flag, do not drop: 03_spells handles them after ownership-change linking",
             len(df), len(df), int((df["qa_zero_length_period"] | df["qa_end_before_auth"]).sum()))

    # 7. Coordinates: (0, 0) and out-of-state points cannot be used for distances or tracts.
    lat = pd.to_numeric(df["latitude"], errors="coerce")
    lon = pd.to_numeric(df["longitude"], errors="coerce")
    bad_xy = ~(lat.between(*NC_LAT) & lon.between(*NC_LON))
    df["qa_coord_invalid"] = bad_xy
    df["latitude"] = lat.mask(bad_xy)
    df["longitude"] = lon.mask(bad_xy)
    log_step(SCRIPT, "coords", f"lat/lon outside NC box lat {NC_LAT}, lon {NC_LON} (incl. 0,0) -> missing; flag qa_coord_invalid",
             "Bad coordinates would corrupt nearest-store distances and tract assignment",
             len(df), len(df), int(bad_xy.sum()))

    # 8. ZIP: keep 5 digits; Zip4 only if exactly 4 digits.
    df["zip5"] = df["zip_code"].str.extract(r"^(\d{5})")[0]
    zip4_bad = int((df["zip4"].notna() & ~df["zip4"].str.fullmatch(r"\d{4}", na=False)).sum())
    df["zip4"] = df["zip4"].where(df["zip4"].str.fullmatch(r"\d{4}", na=False))
    log_step(SCRIPT, "zip", "zip5 = first 5 digits of Zip Code; Zip4 must be 4 digits else missing",
             "Keys for city repair and address matching need consistent ZIPs",
             len(df), len(df), int(df["zip5"].isna().sum()) + zip4_bad)

    # 9. City: uppercase/punctuation first, then merge near-duplicate spellings within a ZIP.
    df["city_raw"] = df["city"]
    norm = df["city"].map(normalize_city)
    fmt_changed = int((norm != df["city"]).sum())
    n_spell_before = norm.nunique()
    log_step(SCRIPT, "city_format", "uppercase, strip punctuation, MT/MTN/FT -> MOUNT/MOUNTAIN/FORT",
             "'Charlotte' vs 'CHARLOTTE' must be one city", len(df), len(df), fmt_changed)
    merged = merge_city_variants(norm, df["zip5"])
    df["city"] = merged
    log_step(SCRIPT, "city_zip_variants",
             f"within a ZIP, merge near-identical spellings into the modal one (ratio>=0.8 or prefix); distinct city strings {n_spell_before} -> {merged.nunique()}",
             "Repairs typos like 'WINSTONSALEM', 'PILOTT MTN' without merging different towns",
             len(df), len(df), int((merged != norm).sum()))

    # 10. County: uppercase; NC has exactly 100.
    df["county"] = df["county"].str.upper()
    if df["county"].nunique() != 100:
        raise ValueError(f"Expected 100 NC counties, found {df['county'].nunique()}")
    log_step(SCRIPT, "county", "uppercase; assert exactly 100 distinct NC counties",
             "Consistent join key; sanity check on the NC filter", len(df), len(df), 0)

    # 11. Store type: must be a known USDA type; add grocery/convenience flags.
    unknown = set(df["store_type"].dropna().unique()) - KNOWN_STORE_TYPES
    if unknown or df["store_type"].isna().any():
        raise ValueError(f"Unexpected store types: {unknown}")
    df["is_grocery"] = df["store_type"].isin(GROCERY_TYPES)
    df["is_convenience"] = df["store_type"] == CONVENIENCE_TYPE
    log_step(SCRIPT, "store_type_flags", "is_grocery = the 5 grocery types; is_convenience = Convenience Store",
             "Observations are grocery stores; convenience stores feed the food-swamp ratio",
             len(df), len(df), int(df["is_grocery"].sum()))

    # 12. Standardized address for ownership-change matching (Additional Address / suites ignored
    #     because they are inconsistently filled for the same storefront).
    df["address_std"] = [std_address(a, b) for a, b in zip(df["street_number"], df["street_name"])]
    df["address_key"] = (df["address_std"] + "|" + df["zip5"]).where(df["address_std"].notna() & df["zip5"].notna())
    log_step(SCRIPT, "address_std", "address_std = number + USPS-abbreviated street; address_key = address_std|zip5; missing without street number",
             "Ownership-change rule needs a storefront identity; street name alone is ambiguous",
             len(df), len(df), int(df["address_key"].isna().sum()))

    # 13. Names: normalized form for chain detection; flag unusable names.
    df["name_std"] = df["store_name"].map(std_name)
    malformed = (
        df["store_name"].str.contains(r"[\x00-\x1f�]")
        | ~df["store_name"].str.contains(r"[A-Za-z]")
        | (df["store_name"].str.len() <= 1)
    )
    df["qa_name_malformed"] = malformed
    log_step(SCRIPT, "store_name", "name_std = uppercase, no accents/punctuation/store numbers/INC-LLC; qa_name_malformed = control chars, no letters, or 1 char",
             "Chain size in 05 needs comparable names; malformed names are flagged for the data note",
             len(df), len(df), int(malformed.sum()))

    # 14. qa_batch_end. The threshold comes from the statewide distribution of daily end counts
    #     using ONLY end dates through DATA_THROUGH (train + validation), then is applied as a
    #     fixed number to all rows so no test-period outcome informs a data-derived rule.
    daily = df.groupby("end_date").size()
    train_val_daily = daily[daily.index <= pd.Timestamp(DATA_THROUGH)]
    threshold = math.ceil(train_val_daily.quantile(BATCH_END_QUANTILE))
    df["qa_batch_end"] = df["end_date"].map(daily).ge(threshold).fillna(False).astype(bool)
    n_flag_trainval = int(df.loc[df["end_date"] <= pd.Timestamp(DATA_THROUGH), "qa_batch_end"].sum())
    log_step(SCRIPT, "qa_batch_end",
             f"end date shared by >= {threshold} NC retailers (all types) on one day = administrative batch; {threshold} = ceil of the {BATCH_END_QUANTILE:.0%} quantile of daily end counts over {len(train_val_daily):,} end-date days through {DATA_THROUGH}",
             "Mass end dates look like USDA batch actions, not store decisions; rows affected counts end dates through 2021 only",
             len(df), len(df), n_flag_trainval)

    # 15. Exact duplicates after cleaning (normalization can collapse near-identical rows).
    before = len(df)
    df = df.drop_duplicates(subset=[c for c in df.columns if c != "city_raw"]).reset_index(drop=True)
    log_step(SCRIPT, "drop_exact_duplicates", "drop rows identical in every cleaned column",
             "A repeated period would double-count a store-year", before, len(df))

    # 16. Order periods within a Record ID so 03_spells can chain them.
    df = df.sort_values(["record_id", "auth_date", "end_date"], na_position="first").reset_index(drop=True)
    df["period_seq"] = df.groupby("record_id").cumcount() + 1
    n_multi = int((df.groupby("record_id").size() > 1).sum())

    out = df[[
        "record_id", "period_seq", "store_name", "name_std", "store_type", "is_grocery", "is_convenience",
        "street_number", "street_name", "additional_address", "address_std", "address_key",
        "city", "city_raw", "zip5", "zip4", "county", "latitude", "longitude",
        "auth_date", "auth_date_placeholder", "end_date",
        "qa_batch_end", "qa_coord_invalid", "qa_name_malformed",
        "qa_zero_length_period", "qa_end_before_auth",
    ]]
    out.to_parquet(INTERIM / "retailers_nc_clean.parquet", index=False)
    log_step(SCRIPT, "write_clean", f"write retailers_nc_clean.parquet (all NC retailers); {n_multi:,} Record IDs have more than one period",
             "Handoff to 03_spells", len(df), len(out), 0)


if __name__ == "__main__":
    main()
