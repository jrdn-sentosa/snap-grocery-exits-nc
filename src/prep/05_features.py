"""05: Jan-1 features for every store-year (ACS, population density, store density, store history).

Reads : data/interim/panel_trainval.parquet, data/interim/panel_test.parquet   (from 04)
        data/interim/spells.parquet, data/interim/periods_spells.parquet       (from 03)
        data/raw/acs/acs5_{endyear}_nc_tract.csv + manifest.json                (from 00)
        data/raw/tl_2010_37_tract10.shp, tl_2020_37_tract.shp                   (land area)
Writes: data/processed/store_year_trainval.parquet, store_year_test.parquet
        docs/feature_missingness.md, docs/column_inventory.csv

The two panel files go through the SAME feature code separately. No feature uses a label, and nothing
here prints exit counts or rates. Deferred (not built here): Food Access Atlas, RUCA-as-feature (RUCA is carried through as a
grouping column only).

Timing (hard rule 2), enforced by assertions at the end:
  * ACS: the latest 5-year vintage whose cited release date is before Jan 1 of t, joined on the tract
    boundaries that vintage actually uses (2010 or 2020, measured in 00), so t >= 2012 has ACS and
    2008-2011 has none. 2016-2020 (released 2022-03-17) is never used.
  * Store-density and history features use only stores/periods active, or ended, before Jan 1 of t.

Column roles (see docs/column_inventory.csv): feature | id | descriptor | label | outcome_side | bias.
Never features: qa_*, impact_*, exit_*, bias_*, calendar year, and acs_* metadata (acs_available is a
function of year, so it would be a calendar-year proxy).
"""

import json
import re

import geopandas as gpd
import numpy as np
import pandas as pd

from common import DOCS, INTERIM, PROCESSED, RAW, TEST_YEARS, VAL_END_YEAR, ensure_dirs, log_step, start_log

SCRIPT = "05_features"
CRS_GEO, CRS_PROJ = "EPSG:4269", "EPSG:32119"
M_PER_MI = 1609.344
SQM_PER_SQMI = 2_589_988.110336

FEATURES = [
    # store
    "store_type", "store_age_years", "auth_date_placeholder", "n_prior_spells_same_id", "n_prior_ownership_changes", "chain_size",
    # neighbourhood store density (stores active on Jan 1 of t)
    "n_grocery_05mi", "n_grocery_1mi", "n_convenience_1mi", "convenience_to_grocery_ratio_1mi", "n_grocery_ends_1mi_prior12m",
    # tract (ACS, vintage released before Jan 1 of t)
    "acs_population", "pop_density_sqmi", "pct_poverty", "median_hh_income", "pct_no_vehicle", "pct_snap_hh",
    "pct_renter", "pct_age_65_plus", "unemployment_rate",
]
BIAS = ["bias_pct_hispanic", "bias_pct_white_nh", "bias_pct_black_nh", "bias_pct_asian_nh", "bias_pct_aian_nh", "bias_pct_other_multi_nh"]
ACS_META = ["acs_available", "acs_vintage", "acs_release_date", "acs_tract_vintage"]
IDS = ["record_id", "spell_id", "year", "split"]
DESCRIPTORS = ["store_name", "county", "latitude", "longitude", "tract_geoid_2010", "tract_geoid_2020"] + ACS_META
LABELS = ["exit_12m", "exit_12m_strict", "exit_is_batch"]
OUTCOME_SIDE = ["impact_dist_nearest_other_grocery_mi", "qa_coord_invalid", "qa_tract_unmatched", "qa_ownership_change_in_year", "qa_spell_end"]
# RUCA urban-rural grouping (from 04). A GROUPING column for slicing results and the dashboard, never a feature: the files we
# hold were last updated 2019-07-03 (RUCA 2010) and 2025-07-31 (RUCA 2020), after most cohort years (see ruca_release_date).
RUCA = ["ruca_primary", "ruca_group", "ruca_vintage", "ruca_release_date"]
ALL_COLUMNS = IDS + FEATURES + BIAS + ACS_META + DESCRIPTORS[:6] + RUCA + LABELS + OUTCOME_SIDE


def role_of(col: str) -> str:
    """id | label | feature | qa_ | impact_ | bias_ | grouping. Only `feature` may enter a model."""
    if col in IDS:
        return "id"
    if col in FEATURES:
        return "feature"
    if col in LABELS:
        return "label"
    if col in BIAS:
        return "bias_"
    if col.startswith("impact_"):
        return "impact_"
    if col.startswith("qa_"):
        return "qa_"
    return "grouping"  # descriptors used to slice results (county, tracts, coordinates, ACS vintage metadata)


# ---------------------------------------------------------------- ACS ----------------------------------------------------
def ratio(num: pd.DataFrame, a: str, b: str) -> pd.Series:
    """a / b, missing when either is missing or the denominator is not positive."""
    if a not in num or b not in num:
        return pd.Series(np.nan, index=num.index)
    return (num[a] / num[b]).where(num[b] > 0)


def acs_vintage_features(end_year: int, area_sqmi: pd.Series) -> tuple[pd.DataFrame, int]:
    """Tract features for one vintage. Returns (features indexed by geoid, sentinel cells set to missing)."""
    raw = pd.read_csv(RAW / "acs" / f"acs5_{end_year}_nc_tract.csv", dtype=str)
    cols = [c for c in raw.columns if re.fullmatch(r"B\d{5}_\d{3}E", c)]
    num = raw[cols].apply(pd.to_numeric, errors="coerce")
    # Census encodes "not available / suppressed" as large negative sentinels (-666666666, -222222222, ...);
    # no real count or dollar value is negative, so every negative becomes missing.
    sentinels = int((num < 0).sum().sum())
    num = num.mask(num < 0)
    num.index = raw["geoid"]

    age65 = [f"B01001_{i:03d}E" for i in (20, 21, 22, 23, 24, 25, 44, 45, 46, 47, 48, 49)]
    pop = num["B01003_001E"]
    out = pd.DataFrame({
        "acs_population": pop,
        "pop_density_sqmi": (pop / area_sqmi.reindex(num.index)).where(area_sqmi.reindex(num.index) > 0),
        "pct_poverty": ratio(num, "B17001_002E", "B17001_001E"),
        "median_hh_income": num["B19013_001E"],
        "pct_no_vehicle": ((num["B25044_003E"] + num["B25044_010E"]) / num["B25044_001E"]).where(num["B25044_001E"] > 0),
        "pct_snap_hh": ratio(num, "B22001_002E", "B22001_001E"),
        "pct_renter": ratio(num, "B25003_003E", "B25003_001E"),
        "pct_age_65_plus": (num[age65].sum(axis=1, skipna=False) / num["B01001_001E"]).where(num["B01001_001E"] > 0),
        "unemployment_rate": ratio(num, "B23025_005E", "B23025_003E"),  # B23025 is not published for 2006-2010 -> missing
        "bias_pct_hispanic": ratio(num, "B03002_012E", "B03002_001E"),
        "bias_pct_white_nh": ratio(num, "B03002_003E", "B03002_001E"),
        "bias_pct_black_nh": ratio(num, "B03002_004E", "B03002_001E"),
        "bias_pct_asian_nh": ratio(num, "B03002_006E", "B03002_001E"),
        "bias_pct_aian_nh": ratio(num, "B03002_005E", "B03002_001E"),
        "bias_pct_other_multi_nh": ((num["B03002_007E"] + num["B03002_008E"] + num["B03002_009E"]) / num["B03002_001E"]).where(num["B03002_001E"] > 0),
    })
    return out, sentinels


class Acs:
    def __init__(self) -> None:
        man = json.loads((RAW / "acs" / "manifest.json").read_text(encoding="utf-8"))
        v = pd.DataFrame([{"label": k, **d} for k, d in man["vintages"].items()])
        v["release_date"] = pd.to_datetime(v["release_date"])
        self.vintages = v.set_index("end_year")
        # land area (square miles) per tract GEOID, from the TIGER shapefile of the same boundary vintage
        a10 = gpd.read_file(RAW / "tl_2010_37_tract10.shp")[["GEOID10", "ALAND10"]].set_index("GEOID10")["ALAND10"]
        a20 = gpd.read_file(RAW / "tl_2020_37_tract.shp")[["GEOID", "ALAND"]].set_index("GEOID")["ALAND"]
        self.area = {"2010": a10 / SQM_PER_SQMI, "2020": a20 / SQM_PER_SQMI}
        self.cache: dict[int, pd.DataFrame] = {}
        self.sentinels = 0

    def vintage_for_year(self, year: int) -> int | None:
        eligible = self.vintages[self.vintages["release_date"] < pd.Timestamp(year, 1, 1)]
        return int(eligible.index.max()) if len(eligible) else None

    def features(self, end_year: int) -> pd.DataFrame:
        if end_year not in self.cache:
            geo = self.vintages.loc[end_year, "tract_geography"]
            self.cache[end_year], n = acs_vintage_features(end_year, self.area[geo])
            self.sentinels += n
        return self.cache[end_year]


def add_acs(frame: pd.DataFrame, acs: Acs) -> pd.DataFrame:
    frame = frame.copy()
    value_cols = [c for c in acs.features(2022).columns]
    for c in value_cols:
        frame[c] = np.nan
    frame["acs_end_year"] = frame["year"].map(acs.vintage_for_year).astype("Int64")
    frame["acs_vintage"] = pd.Series(pd.NA, index=frame.index, dtype="object")
    frame["acs_release_date"] = pd.NaT
    frame["acs_tract_vintage"] = pd.Series(pd.NA, index=frame.index, dtype="object")
    for ey in sorted(frame["acs_end_year"].dropna().unique()):
        ey = int(ey)
        rows = frame["acs_end_year"] == ey
        geo = acs.vintages.loc[ey, "tract_geography"]
        keys = frame.loc[rows, f"tract_geoid_{geo}"]
        frame.loc[rows, value_cols] = acs.features(ey).reindex(keys.to_numpy()).to_numpy()
        frame.loc[rows, "acs_vintage"] = acs.vintages.loc[ey, "label"]
        frame.loc[rows, "acs_release_date"] = acs.vintages.loc[ey, "release_date"]
        frame.loc[rows, "acs_tract_vintage"] = geo
    frame["acs_available"] = frame["acs_end_year"].notna()
    return frame


# ------------------------------------------------------- store features ---------------------------------------------------
def project(lat: pd.Series, lon: pd.Series) -> tuple[np.ndarray, np.ndarray]:
    ok = lat.notna() & lon.notna()
    x = np.full(len(lat), np.nan)
    y = np.full(len(lat), np.nan)
    if ok.any():
        g = gpd.GeoSeries(gpd.points_from_xy(lon[ok], lat[ok]), crs=CRS_GEO).to_crs(CRS_PROJ)
        x[ok.to_numpy()], y[ok.to_numpy()] = g.x.to_numpy(), g.y.to_numpy()
    return x, y


def count_within(rx, ry, rrec, ox, oy, orec, miles: float, exclude_self: bool) -> np.ndarray:
    """For each focal store, how many of the other points lie within `miles` (projected metres)."""
    if len(ox) == 0:
        return np.zeros(len(rx), dtype=int)
    counts = np.empty(len(rx), dtype=int)
    for s in range(0, len(rx), 400):  # chunk the focal stores to keep the distance matrix small
        sl = slice(s, s + 400)
        d = np.hypot(rx[sl, None] - ox[None, :], ry[sl, None] - oy[None, :]) / M_PER_MI
        if exclude_self:
            d[rrec[sl, None] == orec[None, :]] = np.inf
        counts[sl] = (d <= miles).sum(axis=1)
    return counts


def add_store_features(frame: pd.DataFrame, periods: pd.DataFrame, spells: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    periods = periods.copy()
    periods["px"], periods["py"] = project(periods["latitude"], periods["longitude"])
    frame["px"], frame["py"] = project(frame["latitude"], frame["longitude"])
    for c in ("n_grocery_05mi", "n_grocery_1mi", "n_convenience_1mi", "n_grocery_ends_1mi_prior12m"):
        frame[c] = pd.array([pd.NA] * len(frame), dtype="Int64")
    frame["chain_size"] = pd.array([pd.NA] * len(frame), dtype="Int64")

    for y, idx in frame.groupby("year").groups.items():
        j1 = pd.Timestamp(int(y), 1, 1)
        active = (periods["auth_date"].isna() | (periods["auth_date"] <= j1)) & (periods["end_date"].isna() | (periods["end_date"] >= j1))
        located = periods["px"].notna()
        G = periods[active & located & periods["is_grocery"]]
        C = periods[active & located & periods["is_convenience"]]
        # Ends in the previous calendar year: whether such an end was an ownership transfer is not yet
        # knowable on Jan 1 (the successor window runs 90 days past the end), so all grocery ends count.
        E = periods[located & periods["is_grocery"] & (periods["end_date"] >= pd.Timestamp(int(y) - 1, 1, 1)) & (periods["end_date"] < j1)]
        r = frame.loc[idx]
        ok = r["px"].notna().to_numpy()
        rx, ry, rrec = r["px"].to_numpy(), r["py"].to_numpy(), r["record_id"].to_numpy()
        out = {k: np.full(len(r), np.nan) for k in ("g05", "g1", "c1", "e1")}
        out["g05"][ok] = count_within(rx[ok], ry[ok], rrec[ok], G["px"].to_numpy(), G["py"].to_numpy(), G["record_id"].to_numpy(), 0.5, True)
        out["g1"][ok] = count_within(rx[ok], ry[ok], rrec[ok], G["px"].to_numpy(), G["py"].to_numpy(), G["record_id"].to_numpy(), 1.0, True)
        out["c1"][ok] = count_within(rx[ok], ry[ok], rrec[ok], C["px"].to_numpy(), C["py"].to_numpy(), C["record_id"].to_numpy(), 1.0, False)
        out["e1"][ok] = count_within(rx[ok], ry[ok], rrec[ok], E["px"].to_numpy(), E["py"].to_numpy(), E["record_id"].to_numpy(), 1.0, True)
        for col, key in (("n_grocery_05mi", "g05"), ("n_grocery_1mi", "g1"), ("n_convenience_1mi", "c1"), ("n_grocery_ends_1mi_prior12m", "e1")):
            frame.loc[idx, col] = pd.Series(out[key], index=idx).astype("Int64")
        # chain size: active periods of any type sharing the standardized name, statewide
        names = periods.loc[active, "name_std"].value_counts()
        frame.loc[idx, "chain_size"] = r["name_std"].map(names).where(r["name_std"].notna() & (r["name_std"] != "")).astype("Int64")

    # grocery nearby includes the store itself in the ratio's denominator (+1), so it is defined even with no neighbours
    frame["convenience_to_grocery_ratio_1mi"] = frame["n_convenience_1mi"].astype("float64") / (frame["n_grocery_1mi"].astype("float64") + 1)

    # store history from the spell
    sp = spells.set_index("spell_id")
    j1s = pd.to_datetime(frame["year"].astype(str) + "-01-01")
    start = frame["spell_id"].map(sp["spell_start"])
    placeholder = frame["spell_id"].map(sp["start_placeholder"]).astype(bool)
    frame["auth_date_placeholder"] = placeholder
    frame["store_age_years"] = ((j1s - start).dt.days / 365.25).where(~placeholder)  # missing when the true start is unknown
    frame["n_prior_spells_same_id"] = (frame["spell_id"].map(sp["spell_seq"]) - 1).astype("Int64")

    # prior ownership transfers in this store's lineage: follow predecessor links whose predecessor ended before Jan 1 of t
    link = spells.loc[spells["successor_spell_id"].notna(), ["spell_id", "successor_spell_id", "successor_gap_days"]].copy()
    link["absgap"] = link["successor_gap_days"].abs()
    pred_of = (link.sort_values(["successor_spell_id", "absgap", "spell_id"]).drop_duplicates("successor_spell_id")
                   .set_index("successor_spell_id")["spell_id"].to_dict())
    end_of = sp["spell_end"].to_dict()

    def depth(spell_id: str, j1: pd.Timestamp) -> int:
        d, cur = 0, spell_id
        while cur in pred_of and d < 25:
            p = pred_of[cur]
            if not end_of[p] < j1:
                break
            d, cur = d + 1, p
        return d

    frame["n_prior_ownership_changes"] = pd.Series([depth(s, j) for s, j in zip(frame["spell_id"], j1s)], index=frame.index).astype("Int64")
    return frame.drop(columns=["px", "py"])


# ---------------------------------------------------------- checks -------------------------------------------------------
def haversine_mi(lat1, lon1, lat2, lon2):
    p1, p2 = np.radians(lat1), np.radians(lat2)
    a = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(np.radians(lon2 - lon1) / 2) ** 2
    return 2 * 3958.7613 * np.arcsin(np.sqrt(a))


def check_density(out: pd.DataFrame, periods: pd.DataFrame, n: int = 150, seed: int = 7) -> tuple[int, int, float]:
    """Recompute n_grocery_1mi / n_convenience_1mi for a random sample with haversine distance and plain pandas
    masks (independent of the projected/vectorised path). Returns (checked, exact matches, max abs diff)."""
    s = out.sample(min(n, len(out)), random_state=seed)
    exact, worst = 0, 0
    for r in s.itertuples():
        j1 = pd.Timestamp(r.year, 1, 1)
        act = periods[(periods["auth_date"].isna() | (periods["auth_date"] <= j1)) & (periods["end_date"].isna() | (periods["end_date"] >= j1)) & periods["latitude"].notna()]
        d = haversine_mi(r.latitude, r.longitude, act["latitude"].to_numpy(), act["longitude"].to_numpy())
        g = int(((d <= 1) & act["is_grocery"].to_numpy() & (act["record_id"].to_numpy() != r.record_id)).sum())
        c = int(((d <= 1) & act["is_convenience"].to_numpy()).sum())
        diff = max(abs(g - r.n_grocery_1mi), abs(c - r.n_convenience_1mi))
        exact += diff == 0
        worst = max(worst, diff)
    return len(s), exact, worst


def timing_assertions(out: pd.DataFrame, acs: Acs) -> str:
    has = out[out["acs_available"]]
    j1 = pd.to_datetime(has["year"].astype(str) + "-01-01")
    lag = (j1 - has["acs_release_date"]).dt.days
    assert (lag > 0).all(), "an ACS vintage was released on/after Jan 1 of the cohort year"
    # latest eligible vintage, and the tract boundary column that was joined matches the vintage's boundaries
    for y, g in has.groupby("year"):
        assert (g["acs_end_year"] == acs.vintage_for_year(int(y))).all()
    assert has["acs_tract_vintage"].isin(["2010", "2020"]).all()
    assert not (has["acs_end_year"] == 2020).any(), "2016-2020 (released 2022-03-17) must never be used"
    assert out.loc[out["year"] <= 2011, "acs_available"].eq(False).all() and out.loc[out["year"] >= 2012, "acs_available"].all()
    return (f"{len(has):,} ACS-bearing rows, every ACS release date precedes Jan 1 of its cohort year (min lead {int(lag.min())} days); "
            f"vintages used: {', '.join(sorted(has['acs_vintage'].unique()))}")


def main() -> None:
    ensure_dirs()
    start_log(SCRIPT)
    spells = pd.read_parquet(INTERIM / "spells.parquet")
    periods = pd.read_parquet(INTERIM / "periods_spells.parquet")
    acs = Acs()
    keep_from_panel = ["record_id", "spell_id", "year", "split", "store_type", "store_name", "name_std", "county", "latitude", "longitude",
                       "tract_geoid_2010", "tract_geoid_2020", *RUCA, *LABELS, *OUTCOME_SIDE]
    results = {}
    for name in ("trainval", "test"):
        panel = pd.read_parquet(INTERIM / f"panel_{name}.parquet")
        base = panel[keep_from_panel]
        out = add_store_features(add_acs(base, acs), periods, spells)
        results[name] = out
        log_step(SCRIPT, f"features_{name}", "ACS (vintage released before Jan 1 t, matching tract boundary), population density, store density, store history",
                 "Predictors available on Jan 1 of t (hard rule 2)", len(panel), len(out), 0)
    log_step(SCRIPT, "acs_sentinels", "negative ACS sentinel codes (-666666666 etc.) set to missing; cells counted over the vintage files actually used",
             "A sentinel read as a number would corrupt rates and incomes", acs.sentinels, acs.sentinels, acs.sentinels)

    # ---- guards ----
    tv, te = results["trainval"], results["test"]
    assert tv["year"].max() <= VAL_END_YEAR and not tv["split"].eq("test").any(), "test-year row in trainval"
    assert set(te["year"]) <= set(TEST_YEARS) and te["split"].eq("test").all()
    allrows = pd.concat([tv, te], ignore_index=True)
    timing_msg = timing_assertions(allrows, acs)
    checked, exact, worst = check_density(allrows, periods)
    assert worst <= 1, f"density cross-check differs by {worst} (projected vs haversine)"

    final_cols = [c for c in ALL_COLUMNS if c in tv.columns]
    tv[final_cols].to_parquet(PROCESSED / "store_year_trainval.parquet", index=False)
    te[final_cols].to_parquet(PROCESSED / "store_year_test.parquet", index=False)

    # ---- missingness (features only; no labels touched) ----
    def miss(df: pd.DataFrame) -> pd.Series:
        return (100 * df[FEATURES].isna().mean()).round(1)

    by_split = pd.DataFrame({s: miss(allrows[allrows["split"] == s]) for s in ("train", "validation", "test")})
    by_split_2012 = pd.DataFrame({s: miss(allrows[(allrows["split"] == s) & (allrows["year"] >= 2012)]) for s in ("train", "validation", "test")})
    n_rows = {s: int((allrows["split"] == s).sum()) for s in ("train", "validation", "test")}
    n_rows12 = {s: int(((allrows["split"] == s) & (allrows["year"] >= 2012)).sum()) for s in ("train", "validation", "test")}

    def md(df: pd.DataFrame, counts: dict) -> str:
        head = "| feature | " + " | ".join(f"{c} (n={counts[c]:,})" for c in df.columns) + " |"
        lines = [head, "|---|" + "---|" * len(df.columns)]
        lines += [f"| {i} | " + " | ".join(f"{v:.1f}%" for v in row) + " |" for i, row in df.iterrows()]
        return "\n".join(lines)

    doc = [
        "# Feature missingness (percent of store-years missing)", "",
        "Generated by `src/prep/05_features.py`; do not edit by hand. Features only; no labels are used.", "",
        "## All rows, by split", "", md(by_split, n_rows), "",
        "ACS columns are missing for the whole 2008-2011 cohorts (the first usable vintage, 2006-2010, was released 2011-12-08).", "",
        "## Rows with year >= 2012 (ACS available), by split", "", md(by_split_2012, n_rows12), "",
        "## Timing and consistency checks", "",
        f"- ACS timing: PASSED. {timing_msg}.",
        "- 2016-2020 (released 2022-03-17) is never used; the 2022 cohort uses 2015-2019.",
        f"- Store-density cross-check (haversine + plain pandas masks vs the projected path), {checked} random store-years: "
        f"{exact} exact matches, max absolute difference {worst}.",
        "- Neighbour counts use periods active on Jan 1 of t; prior-year ends use period end dates before Jan 1 of t; "
        "ownership-lineage links count only predecessors that ended before Jan 1 of t.", "",
    ]
    (DOCS / "feature_missingness.md").write_text("\n".join(doc), encoding="utf-8")

    inv = pd.DataFrame({
        "column": final_cols,
        "dtype": [str(tv[c].dtype) for c in final_cols],
        "role": [role_of(c) for c in final_cols],
        **{f"missing_pct_{s}": [round(100 * allrows.loc[allrows["split"] == s, c].isna().mean(), 1) for c in final_cols] for s in ("train", "validation", "test")},
    })
    inv.to_csv(DOCS / "column_inventory.csv", index=False)

    print(f"Wrote store_year_trainval ({len(tv):,}) and store_year_test ({len(te):,})")
    print(f"TIMING ASSERTION PASSED: {timing_msg}")
    print(f"Density cross-check: {exact}/{checked} exact, max abs diff {worst}")
    print(f"ACS sentinel cells set to missing (vintage files used): {acs.sentinels:,}")
    print("\nFeature missingness (%), all rows:")
    print(by_split.to_string())
    print("\nFeature missingness (%), year >= 2012:")
    print(by_split_2012.to_string())
    print("\nrows:", n_rows, "| rows year>=2012:", n_rows12)


if __name__ == "__main__":
    main()
