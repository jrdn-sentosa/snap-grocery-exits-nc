"""04: build the store-year panel, attach tracts and the exit-impact distance, then SPLIT.

Reads : data/interim/spells.parquet, data/interim/periods_spells.parquet   (from 03)
        data/raw/tl_2010_37_tract10.shp, data/raw/tl_2020_37_tract.shp
Writes: data/interim/panel_trainval.parquet   years 2008-2021, split = train | validation
        data/interim/panel_test.parquet       years 2022-2024, split = test (RESERVED)
        docs/store_year_counts_by_year_type.csv   descriptive store counts only, all years

One row = a grocery-type Record ID whose spell is active on Jan 1 of year t (definition and labels
in store_years.py). The split happens here, before any feature or plot code, and the trainval file
is asserted to hold no year >= 2022.

Column prefixes: qa_* (data quality / outcome bookkeeping) and impact_* (measured at the exit,
after Jan 1) are never model features; neither are exit_* labels.

Test-set discipline: logs below count store-years and missing tracts for every year (descriptive
counts of stores), but any count involving exits is limited to years <= 2021.
"""

import numpy as np
import pandas as pd
import geopandas as gpd

from common import (
    COHORT_YEARS, DOCS, INTERIM, RAW, TEST_YEARS, TRAIN_END_YEAR, VAL_END_YEAR,
    ensure_dirs, load_release_dates, log_step, ruca_group, start_log,
)
from store_years import build_store_years

SCRIPT = "04_panel"
# Tract shapefiles are NAD83 (EPSG:4269). SNAP coordinates are treated as NAD83 too; the ~1 m
# NAD83/WGS84 difference is irrelevant for tract assignment.
CRS_GEO = "EPSG:4269"
CRS_PROJ = "EPSG:32119"  # NC State Plane (NAD83), metres: distances in a locally accurate plane
M_PER_MI = 1609.344
RUCA_2020_FROM_YEAR = 2023  # first cohort year on 2020 tracts; matches ACS, whose newest vintage usable on Jan 1 2023 (2017-2021) is on 2020 tracts
OPEN_END = pd.Timestamp("2200-01-01").as_unit("us")
EARLIEST = pd.Timestamp("1900-01-01").as_unit("us")


def tract_ids(locs: pd.DataFrame, shp: str, geoid: str) -> pd.Series:
    """Tract GEOID for each unique (latitude, longitude) row of locs; NaN if outside every tract."""
    pts = gpd.GeoDataFrame(locs, geometry=gpd.points_from_xy(locs["longitude"], locs["latitude"]), crs=CRS_GEO)
    tracts = gpd.read_file(RAW / shp)[[geoid, "geometry"]]
    # 'intersects' (not 'within') so a point exactly on a tract boundary still gets a tract;
    # if it touches two, keep the first so the join stays one row per point.
    j = gpd.sjoin(pts, tracts, how="left", predicate="intersects")
    j = j[~j.index.duplicated(keep="first")]
    return j[geoid].reindex(locs.index)


def nearest_other_grocery_mi(exits: pd.DataFrame, periods: pd.DataFrame) -> pd.Series:
    """Miles from each exiting store to the nearest OTHER grocery-type store still authorized after
    its exit date (start <= exit date < end, or no end). Others ending the same day do not count,
    so a batch of stores closing together is not credited as remaining access."""
    oth = periods[periods["is_grocery"] & periods["latitude"].notna()]
    xy = gpd.GeoSeries(gpd.points_from_xy(oth["longitude"], oth["latitude"]), crs=CRS_GEO).to_crs(CRS_PROJ)
    ox, oy = xy.x.to_numpy(), xy.y.to_numpy()
    o_rec = oth["record_id"].to_numpy()
    o_start = oth["auth_date"].fillna(EARLIEST).astype("datetime64[us]").to_numpy()  # placeholder = authorized long ago
    o_end = oth["end_date"].fillna(OPEN_END).astype("datetime64[us]").to_numpy()
    exy = gpd.GeoSeries(gpd.points_from_xy(exits["longitude"], exits["latitude"]), crs=CRS_GEO).to_crs(CRS_PROJ)
    out = np.full(len(exits), np.nan)
    for k, (x, y, rid, d) in enumerate(zip(exy.x, exy.y, exits["record_id"], exits["qa_spell_end"].to_numpy())):
        ok = (o_rec != rid) & (o_start <= d) & (o_end > d)
        if ok.any():
            out[k] = np.hypot(ox[ok] - x, oy[ok] - y).min() / M_PER_MI
    return pd.Series(out, index=exits.index)


def main() -> None:
    ensure_dirs()
    start_log(SCRIPT)
    spells = pd.read_parquet(INTERIM / "spells.parquet")
    periods = pd.read_parquet(INTERIM / "periods_spells.parquet")

    # 1. Store-years for every cohort year, then the split flag.
    sy = build_store_years(spells, periods, COHORT_YEARS)
    sy["split"] = np.select(
        [sy["year"] <= TRAIN_END_YEAR, sy["year"] <= VAL_END_YEAR], ["train", "validation"], default="test")
    log_step(SCRIPT, "build_store_years",
             "grocery Record IDs with an active spell on Jan 1 of t, t = 2008-2024 (rows_before = spells, rows_after = store-years)",
             "Observation unit of the research question", len(spells), len(sy), 0)

    # 2. Coordinates: 02 blanked invalid ones, so these store-years get no tract and no distance.
    n_bad = int(sy["qa_coord_invalid"].sum())
    bad_g = periods[periods["is_grocery"] & periods["latitude"].isna()]
    log_step(SCRIPT, "qa_coord_invalid",
             "grocery store-years whose period in force on Jan 1 has missing/invalid coordinates (kept; no tract, no impact distance); "
             f"for reference {len(bad_g)} grocery PERIODS have blanked coordinates, the latest ending {bad_g['end_date'].max().date()}, "
             "before the first cohort, so none reach a Jan 1 in 2008-2024",
             "Dropping them would bias the sample; they would stay in with missing geography",
             len(sy), len(sy), n_bad)

    # 3. Tract assignment, both vintages (05 picks the one matching each source's boundaries).
    locs = sy.loc[~sy["qa_coord_invalid"], ["latitude", "longitude"]].drop_duplicates().reset_index(drop=True)
    locs["tract_geoid_2010"] = tract_ids(locs, "tl_2010_37_tract10.shp", "GEOID10")
    locs["tract_geoid_2020"] = tract_ids(locs, "tl_2020_37_tract.shp", "GEOID")
    sy = sy.merge(locs, on=["latitude", "longitude"], how="left")
    valid = ~sy["qa_coord_invalid"]
    for vint in ("2010", "2020"):
        miss = int((valid & sy[f"tract_geoid_{vint}"].isna()).sum())
        log_step(SCRIPT, f"tract_{vint}",
                 f"point-in-polygon against tl_{'2010_37_tract10' if vint == '2010' else '2020_37_tract'} (intersects); "
                 f"store-years with valid coordinates but no tract match",
                 "Tracts key the ACS / Atlas features in 05; unmatched points (coast, border) stay missing, not guessed",
                 int(valid.sum()), int(valid.sum()) - miss, miss)
    sy["qa_tract_unmatched"] = valid & (sy["tract_geoid_2010"].isna() | sy["tract_geoid_2020"].isna())

    # 3b. RUCA by tract vintage: RUCA 2010 (keyed by 2010 tracts) up to 2022, RUCA 2020 (2020 tracts)
    #     from 2023, the first cohort year whose ACS vintage is on 2020 tracts, so every source uses
    #     the same tract boundaries in a given year. The release date of the version we hold rides
    #     along so 05 can enforce the Jan-1 timing rule (rule 2) instead of this script silently
    #     dropping early years.
    ruca = {v: pd.read_parquet(INTERIM / f"ruca_{v}_tract_nc.parquet").set_index("tract_geoid")["ruca_primary"] for v in (2010, 2020)}
    rel = load_release_dates()
    rel = rel[rel["dataset"] == "ruca"].set_index("end_year")["release_date"]
    use20 = sy["year"] >= RUCA_2020_FROM_YEAR
    code = sy["tract_geoid_2020"].map(ruca[2020]).where(use20, sy["tract_geoid_2010"].map(ruca[2010]))
    sy["ruca_primary"] = code.astype("Int8")
    sy["ruca_group"] = sy["ruca_primary"].map(ruca_group)
    sy["ruca_vintage"] = np.where(use20, 2020, 2010).astype("int16")
    sy["ruca_release_date"] = rel[2010]
    sy.loc[use20, "ruca_release_date"] = rel[2020]
    n_miss_ruca = int((valid & sy["ruca_primary"].isna()).sum())
    log_step(SCRIPT, "ruca",
             f"ruca_primary / ruca_group joined by tract: RUCA 2010 on 2010 tracts for t <= {RUCA_2020_FROM_YEAR - 1}, RUCA 2020 on 2020 tracts from {RUCA_2020_FROM_YEAR}; "
             "groups: 1 urban, 2-3 suburban, 4-9 small town, 10 rural, 99 unclassified; "
             "ruca_release_date = last-updated date of the file we hold (original release not stated by ERS), enforced in 05",
             "Urban/rural context for the exit analysis; valid-coordinate store-years with no RUCA code are counted as affected",
             int(valid.sum()), int(valid.sum()) - n_miss_ruca, n_miss_ruca)

    # 4. Impact distance for true exits (not ownership changes). Measured at the exit date, i.e.
    #    after Jan 1, so it is an outcome-side column (impact_*), never a predictor.
    sy["impact_dist_nearest_other_grocery_mi"] = np.nan
    ex = sy[(sy["exit_12m"] == 1) & valid]
    sy.loc[ex.index, "impact_dist_nearest_other_grocery_mi"] = nearest_other_grocery_mi(ex, periods)
    ex_scope = sy["exit_12m"].eq(1) & (sy["year"] <= VAL_END_YEAR)  # counts limited to train + validation
    log_step(SCRIPT, "impact_dist",
             "impact_dist_nearest_other_grocery_mi = miles (EPSG:32119) to the nearest other grocery-type store authorized after the exit date; "
             f"counts below are exits in years <= {VAL_END_YEAR}: no coordinates={int((ex_scope & ~valid).sum())}, "
             f"no other grocery found={int((ex_scope & valid & sy['impact_dist_nearest_other_grocery_mi'].isna()).sum())}",
             "Not every exit reduces access; this measures how much",
             int(ex_scope.sum()), int((ex_scope & sy['impact_dist_nearest_other_grocery_mi'].notna()).sum()))

    # 5. Split and write. The assertions are the guard for hard rule 1.
    cols = [
        "record_id", "spell_id", "year", "split", "store_type", "store_name", "name_std", "address_key",
        "zip5", "county", "latitude", "longitude", "tract_geoid_2010", "tract_geoid_2020",
        "ruca_primary", "ruca_group", "ruca_vintage", "ruca_release_date",
        "exit_12m", "exit_12m_strict", "exit_is_batch",
        "impact_dist_nearest_other_grocery_mi",
        "qa_coord_invalid", "qa_tract_unmatched", "qa_ownership_change_in_year", "qa_spell_end",
    ]
    sy = sy[cols]
    trainval = sy[sy["year"] <= VAL_END_YEAR].reset_index(drop=True)
    test = sy[sy["year"].isin(TEST_YEARS)].reset_index(drop=True)
    assert trainval["year"].max() <= VAL_END_YEAR, "test-year row found in trainval"
    assert set(test["year"]) <= set(TEST_YEARS) and test["split"].eq("test").all()
    assert len(trainval) + len(test) == len(sy) and not trainval["split"].eq("test").any()
    assert not sy.duplicated(["record_id", "year"]).any()
    trainval.to_parquet(INTERIM / "panel_trainval.parquet", index=False)
    test.to_parquet(INTERIM / "panel_test.parquet", index=False)
    log_step(SCRIPT, "split",
             f"train 2008-{TRAIN_END_YEAR}, validation {TRAIN_END_YEAR + 1}-{VAL_END_YEAR} -> panel_trainval.parquet; "
             f"test {TEST_YEARS[0]}-{TEST_YEARS[-1]} -> panel_test.parquet (reserved); asserted no year >= {TEST_YEARS[0]} in trainval; "
             f"store-years train={int((trainval['split'] == 'train').sum()):,}, validation={int((trainval['split'] == 'validation').sum()):,}, test={len(test):,}",
             "Fixed chronological split; the test file is not read by EDA or the app",
             len(sy), len(trainval) + len(test), 0)

    # 6. Descriptive store counts (not outcomes) are allowed for all years.
    (sy.groupby(["year", "store_type"]).size().rename("store_years").reset_index()
       .to_csv(DOCS / "store_year_counts_by_year_type.csv", index=False))
    print(f"Wrote panel_trainval ({len(trainval):,}), panel_test ({len(test):,}), store_year_counts_by_year_type.csv")


if __name__ == "__main__":
    main()
