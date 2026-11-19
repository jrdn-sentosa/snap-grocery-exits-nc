"""Export the static JSON the Grocery Watch website reads (frontend/public/data/).

Run: uv run python src/site/01_export_site_data.py     then:  uv run python src/site/02_check_export.py

Outputs
  stores.json    Mecklenburg grocery stores authorized on Jan 1, 2024: identity, address, coordinates, Record ID, the 22 API
                 input keys (year + 20 model inputs + dist_other_grocery_jan1_mi), display context, 2 nearest alternatives.
  tracts.geojson Mecklenburg 2020 census tracts with ACS 2018-2022 display values and past-exit shading (2008-2021 only).
  meta.json      store-type exit rates (2012-2021), grocery-only pie of how authorizations ended (through 2021), counts.

Test-period rule (CLAUDE.md hard rules 1 and 2). The 2024 cohort is in the reserved test file, so:
  * store_year_test.parquet is opened ONLY with the explicit column whitelist TEST_COLUMNS (Jan-1 features and identity) and
    filtered to year == 2024 on read. No exit_*, qa_*, impact_*, bias_* or date column is ever loaded from it.
  * No end date is read at all for 2024: the "active on Jan 1, 2024" set is the 2024 store-year rows themselves (nearest
    alternatives), and addresses come from spells.parquet with a whitelist that excludes spell_end and every outcome flag.
  * Everything outcome-based (tract shading, store-type rates, the pie, past exits that left a gap) uses
    store_year_trainval.parquet (years 2008-2021) and spells that ended on or before 2021-12-31. Asserted below.
Logged in docs/test_reservation_log.md.
"""

import importlib
import json
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import shapely
from scipy.spatial import cKDTree

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "prep"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "model"))
from store_prep import FIELD_RULES  # noqa: E402  (the API's own validation rules)
from common import DATA_THROUGH, GROCERY_TYPES, INTERIM, PROCESSED, RAW, ROOT, VAL_END_YEAR  # noqa: E402

OUT = ROOT / "frontend" / "public" / "data"
SCORE_YEAR = 2024                    # the Jan 1, 2024 cohort shown on the site
COUNTY = "MECKLENBURG"
COUNTY_FIPS = "119"
SHADE_YEARS = (2008, VAL_END_YEAR)   # past-exit shading uses train + validation cohorts only
RATE_YEARS = (2012, VAL_END_YEAR)    # the final model's training years (rates shown on the site)
# A tract needs at least this many grocery store-years in 2008-2021 (about one store present for the whole period) before its exit
# share is drawn; with fewer, one closure swings the share too much. A display rule chosen from the store-year counts, not from outcomes.
MIN_STORE_YEARS = 15
ALT_COUNT = 2
M_PER_MILE = 1609.344

# The 22 keys POST /predict requires (src/model/store_prep.FIELD_RULES), in the API's own names.
API_INPUTS = ["year", "store_type", "store_age_years", "auth_date_placeholder", "n_prior_spells_same_id", "n_prior_ownership_changes",
              "chain_size", "n_grocery_05mi", "n_grocery_1mi", "n_convenience_1mi", "convenience_to_grocery_ratio_1mi",
              "n_grocery_ends_1mi_prior12m", "acs_population", "pop_density_sqmi", "pct_poverty", "median_hh_income",
              "pct_no_vehicle", "pct_snap_hh", "pct_renter", "pct_age_65_plus", "unemployment_rate", "dist_other_grocery_jan1_mi"]
# Everything the 2024 test-file read may touch. Feature and identity columns only; labels and dates are not on this list.
TEST_COLUMNS = ["record_id", "spell_id", "county", "store_name", "latitude", "longitude", "tract_geoid_2020", "acs_vintage",
                "acs_tract_vintage", *[c for c in API_INPUTS if c != "year"], "year"]
FORBIDDEN_PREFIXES = ("exit_", "qa_", "impact_", "bias_")


def clean(v):
    """JSON-safe scalar: NaN/NA -> None, numpy -> python."""
    if v is None or (not isinstance(v, str) and pd.isna(v)):
        return None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return float(v)
    return v


def acs_vintage_for(year: int) -> tuple[int, dict]:
    """Latest ACS 5-year vintage released before Jan 1 of `year` (same rule as 05_features.Acs.vintage_for_year)."""
    man = json.loads((RAW / "acs" / "manifest.json").read_text(encoding="utf-8"))
    rows = [(int(d["end_year"]), pd.Timestamp(d["release_date"]), d) for d in man["vintages"].values()]
    eligible = [r for r in rows if r[1] < pd.Timestamp(year, 1, 1)]
    end_year, release, d = max(eligible, key=lambda r: r[0])
    return end_year, {"end_year": end_year, "release_date": str(release.date()), "tract_geography": d["tract_geography"], "label": next(k for k, v in man["vintages"].items() if int(v["end_year"]) == end_year)}


def read_test_2024() -> pd.DataFrame:
    """The ONLY read of the reserved test file: whitelisted columns, year == 2024 filter pushed into the read."""
    assert not any(c.startswith(FORBIDDEN_PREFIXES) for c in TEST_COLUMNS)
    t = pq.read_table(PROCESSED / "store_year_test.parquet", columns=TEST_COLUMNS, filters=[("year", "=", SCORE_YEAR)]).to_pandas()
    assert (t["year"] == SCORE_YEAR).all() and len(t) > 0
    return t


# ----------------------------------------------------------------------------------------------------------------- tracts / ACS
def tract_acs(end_year: int) -> pd.DataFrame:
    """Display values per tract from the raw ACS CSV: counts (the processed files keep only shares)."""
    raw = pd.read_csv(RAW / "acs" / f"acs5_{end_year}_nc_tract.csv", dtype={"geoid": str})
    num = raw.drop(columns=["NAME", "geoid"], errors="ignore").apply(pd.to_numeric, errors="coerce")
    num = num.mask(num < 0)           # Census negative sentinels = not available (same rule as 05_features)
    out = pd.DataFrame({
        "geoid": raw["geoid"],
        "population": num["B01003_001E"],
        "households": num["B22001_001E"],
        "snap_households": num["B22001_002E"],
        "vehicle_households": num["B25044_001E"],
        "no_car_households": num["B25044_003E"] + num["B25044_010E"],
        "median_hh_income": num["B19013_001E"],
    })
    out["snap_share"] = (out["snap_households"] / out["households"]).where(out["households"] > 0)
    out["no_car_share"] = (out["no_car_households"] / out["vehicle_households"]).where(out["vehicle_households"] > 0)
    return out.set_index("geoid")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    acs_end, acs_info = acs_vintage_for(SCORE_YEAR)
    assert acs_info["tract_geography"] == "2020", acs_info
    acs = tract_acs(acs_end)

    # ------------------------------------------------------------------------------------------------ 2024 stores (statewide read)
    t = read_test_2024()
    assert set(t["acs_vintage"].dropna().unique()) == {acs_info["label"]}, "test file ACS vintage differs from the release-date rule"
    n_state = len(t)
    meck = t[t["county"] == COUNTY].copy()
    print(f"2024 store-years: {n_state} statewide, {len(meck)} in {COUNTY}")

    # addresses: spell-level street fields; whitelist excludes spell_end and every outcome flag
    sp = pq.read_table(INTERIM / "spells.parquet", columns=["spell_id", "street_number", "street_name", "city", "zip5", "spell_start", "start_placeholder"]).to_pandas()
    meck = meck.merge(sp, on="spell_id", how="left", validate="one_to_one")
    meck["address"] = (meck["street_number"].fillna("").str.strip() + " " + meck["street_name"].fillna("").str.strip()).str.strip().str.title()
    meck["city"] = meck["city"].str.title()
    meck["since_year"] = meck["spell_start"].dt.year.where(~meck["start_placeholder"].astype(bool))

    # ----------------------------------------------------------------------------------- nearest alternatives (active on Jan 1, 2024)
    # Same candidate rule as 05d (which produced dist_other_grocery_jan1_mi): grocery periods authorized ON Jan 1, 2024. The 2024
    # store-year rows are not enough, because a spell that merges a <=90-day re-authorization gap is a store-year even though it was not
    # authorized that day. The end/auth dates are used here only to answer "authorized on Jan 1, 2024?", exactly as 05d does, and are
    # dropped before anything is written; no end date, and nothing after Jan 1, 2024, is exported.
    ctx05d = importlib.import_module("05d_context_columns")
    periods = pq.read_table(INTERIM / "periods_spells.parquet", columns=["record_id", "auth_date", "end_date", "is_grocery", "latitude", "longitude", "store_name", "store_type", "county"]).to_pandas()
    pts = ctx05d._active_groceries(periods, pd.Timestamp(SCORE_YEAR, 1, 1))[["record_id", "store_name", "store_type", "latitude", "longitude", "county"]].reset_index(drop=True)
    del periods
    assert pts["record_id"].is_unique, "a record has two periods authorized on Jan 1, 2024"
    xy = gpd.GeoSeries(gpd.points_from_xy(pts["longitude"], pts["latitude"]), crs=4326).to_crs(32119)   # NC State Plane (same as 05)
    own_xy = gpd.GeoSeries(gpd.points_from_xy(meck["longitude"], meck["latitude"]), crs=4326).to_crs(32119)
    coords = np.column_stack([xy.x, xy.y])
    tree = cKDTree(coords)
    alts = {}
    for rid, ox, oy, has in zip(meck["record_id"], own_xy.x, own_xy.y, meck["latitude"].notna()):
        if not has:
            continue
        d, idx = tree.query([ox, oy], k=12)
        found = []
        for dist, j in zip(d, idx):
            if j >= len(pts) or pts.at[j, "record_id"] == rid:      # excludes the store's own Record ID, like 05d
                continue
            found.append({"record_id": str(pts.at[j, "record_id"]), "name": pts.at[j, "store_name"], "store_type": pts.at[j, "store_type"],
                          "distance_mi": round(float(dist) / M_PER_MILE, 2), "county": pts.at[j, "county"]})
            if len(found) == ALT_COUNT:
                break
        alts[rid] = found
    # cross-check against the model's own context column (05d): must agree
    chk = meck.assign(alt=meck["record_id"].map(lambda r: alts[r][0]["distance_mi"] if alts.get(r) else np.nan))
    chk = chk.dropna(subset=["alt", "dist_other_grocery_jan1_mi"])
    max_diff = float((chk["alt"] - chk["dist_other_grocery_jan1_mi"]).abs().max())
    print(f"nearest-alternative vs dist_other_grocery_jan1_mi: max |diff| = {max_diff:.3f} mi over {len(chk)} stores")
    assert max_diff < 0.02, "alternatives disagree with the feature pipeline"

    # ------------------------------------------------------------------------------------------------------------- stores.json
    stores = []
    for _, r in meck.sort_values("record_id").iterrows():
        geoid = clean(r["tract_geoid_2020"])
        a = acs.loc[geoid] if geoid in acs.index else None
        inputs = {k: clean(r[k]) for k in API_INPUTS}
        for k in API_INPUTS:                      # ints and the 0/1 flag go out as JSON integers (the API's types), never true/false
            if inputs[k] is not None and FIELD_RULES[k]["kind"] in ("int", "binary"):
                inputs[k] = int(inputs[k])
        missing_required = [k for k in API_INPUTS if inputs[k] is None and not FIELD_RULES[k]["nullable"]]
        stores.append({
            "record_id": str(r["record_id"]), "name": r["store_name"], "store_type": r["store_type"],
            "address": clean(r["address"]), "city": clean(r["city"]), "zip": clean(r["zip5"]),
            "lat": round(float(r["latitude"]), 6) if pd.notna(r["latitude"]) else None,
            "lon": round(float(r["longitude"]), 6) if pd.notna(r["longitude"]) else None,
            "tract": geoid, "since_year": clean(r["since_year"]),
            "chain_size": clean(r["chain_size"]), "independent": (bool(r["chain_size"] == 1) if pd.notna(r["chain_size"]) else None),
            # The API refuses a null in a non-nullable field and rejects the WHOLE batch for one bad record, so the site must leave such
            # stores out of /predict. chain_size is missing when the store name is blank after cleaning (name_std empty).
            "scorable": not missing_required, "unscorable_reason": (f"missing {', '.join(missing_required)}" if missing_required else None),
            "inputs": inputs,
            "context": {
                "dist_next_grocery_mi": clean(r["dist_other_grocery_jan1_mi"]),
                "tract_snap_households": clean(a["snap_households"]) if a is not None else None,
                "tract_snap_share": clean(a["snap_share"]) if a is not None else None,
                "tract_no_car_households": clean(a["no_car_households"]) if a is not None else None,
                "tract_no_car_share": clean(a["no_car_share"]) if a is not None else None,
                "tract_households": clean(a["households"]) if a is not None else None,
            },
            "alternatives": alts.get(r["record_id"], []),
        })
    (OUT / "stores.json").write_text(json.dumps({"score_year": SCORE_YEAR, "scored_on": f"{SCORE_YEAR}-01-01", "stores": stores}, separators=(",", ":")), encoding="utf-8")
    print(f"stores.json: {len(stores)} stores, {sum(not x['scorable'] for x in stores)} not scorable: {[(x['record_id'], x['unscorable_reason']) for x in stores if not x['scorable']]}")

    # --------------------------------------------------------------------- past-exit shading + rates (train + validation ONLY)
    tv = pq.read_table(PROCESSED / "store_year_trainval.parquet",
                       columns=["record_id", "year", "county", "store_type", "tract_geoid_2020", "exit_12m", "impact_dist_nearest_other_grocery_mi"]).to_pandas()
    assert tv["year"].max() <= VAL_END_YEAR, "trainval file contains cohorts after 2021"
    shade = tv[(tv["year"] >= SHADE_YEARS[0]) & (tv["county"] == COUNTY)]
    g = shade.dropna(subset=["tract_geoid_2020"]).groupby("tract_geoid_2020")["exit_12m"].agg(store_years="size", exits="sum")
    print(f"shading: {len(shade)} Mecklenburg store-years 2008-2021, {int(shade['tract_geoid_2020'].isna().sum())} without a tract")

    tr = gpd.read_file(RAW / "tl_2020_37_tract.shp")
    tr = tr[tr["COUNTYFP"] == COUNTY_FIPS][["GEOID", "NAMELSAD", "geometry"]].to_crs(4326)
    tr["geometry"] = shapely.set_precision(tr.geometry.simplify(0.0002, preserve_topology=True), 1e-5)
    props = []
    for gid in tr["GEOID"]:
        a = acs.loc[gid] if gid in acs.index else None
        sy = int(g["store_years"].get(gid, 0))
        ex = int(g["exits"].get(gid, 0))
        status = "none" if sy == 0 else ("low_data" if sy < MIN_STORE_YEARS else "ok")   # none: never had a SNAP grocery; low_data: drawn as "not enough data"
        props.append({
            "geoid": gid, "name": None, "store_years_0821": sy,
            "exit_share_0821": round(ex / sy, 4) if status == "ok" else None, "shade_status": status,
            **{k: clean(a[k]) if a is not None else None for k in ["population", "households", "snap_households", "snap_share", "no_car_households", "no_car_share", "median_hh_income"]},
        })
    tr = tr.reset_index(drop=True)
    for i, p in enumerate(props):
        p["name"] = tr.at[i, "NAMELSAD"]
    geo = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": p, "geometry": json.loads(shapely.to_geojson(tr.at[i, "geometry"]))} for i, p in enumerate(props)]}
    (OUT / "tracts.geojson").write_text(json.dumps(geo, separators=(",", ":")), encoding="utf-8")
    shown = sum(p["shade_status"] == "ok" for p in props)
    print(f"tracts.geojson: {len(props)} tracts, {shown} shaded, {sum(p['shade_status']=='low_data' for p in props)} not enough data, "
          f"{sum(p['shade_status']=='none' for p in props)} no SNAP grocery")

    # store-type exit rates, statewide, the final model's training years (2012-2021)
    rt = tv[(tv["year"] >= RATE_YEARS[0])]
    by_type = rt.groupby("store_type")["exit_12m"].agg(store_years="size", exits="sum")
    rates = {t_: {"store_years": int(by_type.at[t_, "store_years"]), "exits": int(by_type.at[t_, "exits"]),
                  "rate": round(float(by_type.at[t_, "exits"] / by_type.at[t_, "store_years"]), 4)} for t_ in GROCERY_TYPES}
    overall = {"store_years": int(len(rt)), "exits": int(rt["exit_12m"].sum()), "rate": round(float(rt["exit_12m"].mean()), 4)}

    # past Mecklenburg exits that left a gap: nearest other grocery > 1 mile away at the exit (train + validation exits only)
    mex = tv[(tv["county"] == COUNTY) & (tv["exit_12m"] == 1) & (tv["year"] >= SHADE_YEARS[0])]
    known = mex["impact_dist_nearest_other_grocery_mi"].notna()
    gap = {"exits": int(len(mex)), "with_distance": int(known.sum()), "gap_exits": int((mex.loc[known, "impact_dist_nearest_other_grocery_mi"].round(2) > 1).sum())}   # same rule as the site: distance as shown (2 decimals) > 1
    gap["share"] = round(gap["gap_exits"] / gap["with_distance"], 4)

    # ------------------------------------------------------------------ pie: how grocery authorizations ended, through 2021
    spells = pq.read_table(INTERIM / "spells.parquet", columns=["spell_id", "spell_end", "store_type_last", "county", "true_exit", "ownership_change", "qa_batch_end"]).to_pandas()
    ended = spells[spells["store_type_last"].isin(GROCERY_TYPES) & spells["spell_end"].notna() & (spells["spell_end"] <= pd.Timestamp(DATA_THROUGH))].copy()
    assert (ended["true_exit"] ^ ended["ownership_change"]).all(), "every ended spell must be exactly one of exit / ownership change"
    ended["how"] = np.where(ended["ownership_change"], "ownership_change", np.where(ended["qa_batch_end"], "batch", "other_exit"))

    def pie(d: pd.DataFrame) -> dict:
        c = d["how"].value_counts()
        return {"ended": int(len(d)), **{k: {"n": int(c.get(k, 0)), "share": round(float(c.get(k, 0) / len(d)), 4)} for k in ["other_exit", "batch", "ownership_change"]}}

    meta = {
        "score_year": SCORE_YEAR, "scored_on": f"{SCORE_YEAR}-01-01", "generated_by": "src/site/01_export_site_data.py",
        "acs": {"vintage": acs_info["label"], "release_date": acs_info["release_date"], "tract_geography": acs_info["tract_geography"]},
        "counts": {"stores_2024_statewide": n_state, "stores_2024_mecklenburg": len(stores), "stores_scorable": sum(x["scorable"] for x in stores), "tracts": len(props)},
        "type_rates": {"years": list(RATE_YEARS), "scope": "all NC grocery store-years", "by_type": rates, "overall": overall},
        "pie": {"through": str(DATA_THROUGH), "statewide": pie(ended), "mecklenburg": pie(ended[ended["county"] == COUNTY])},
        "past_exit_gap": {"years": list(SHADE_YEARS), "gap_distance_mi": 1, **gap},
        "shading": {"years": list(SHADE_YEARS), "min_store_years": MIN_STORE_YEARS, "label": "exit_12m (primary, batch ends included)"},
    }
    (OUT / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    print(json.dumps({k: meta[k] for k in ["type_rates", "pie", "past_exit_gap"]}, indent=1))


if __name__ == "__main__":
    main()
