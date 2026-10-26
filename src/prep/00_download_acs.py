"""00: download ACS 5-year tract tables for North Carolina, one file per vintage.

Reads : .env (CENSUS_API_KEY)
        src/prep/reference/release_dates.csv   (curated, cited ACS release dates)
        data/raw/tl_2010_37_tract10.shp, data/raw/tl_2020_37_tract.shp   (for the GEOID check)
Writes: data/raw/acs/acs5_{endyear}_nc_tract.csv   exactly as the API returned them, plus geoid
        data/raw/acs/manifest.json   per vintage: URL (key removed), variables, retrieval time,
                                     release date + source, and GEOID match rates

Vintages 2006-2010 .. 2018-2022: 2018-2022 (released Dec 2023) is the newest usable by the 2024 cohort.
Values are NOT cleaned here: the API's negative sentinel codes (e.g. -666666666 = not available)
stay as returned; 05 converts them to missing.

Which tract boundaries a vintage uses is not assumed. The GEOID check below measures it: the share of
the vintage's tracts that exist in each shapefile and the share of each shapefile's tracts the
vintage covers. `acs_on_2010_tracts` / `acs_on_2020_tracts` are set from that measurement.

B03002 (race / Hispanic origin) is for group error analysis (D3) and the bias discussion (D6) ONLY;
it is flagged `bias_analysis_only` and must never be a model feature.
"""

import json
import os
import time
from datetime import datetime, timezone

import geopandas as gpd
import pandas as pd
import requests

from common import RAW, ensure_dirs, load_env, load_release_dates

STATE_FIPS = "37"
END_YEARS = range(2010, 2023)  # 2006-2010 .. 2018-2022
API = "https://api.census.gov/data/{year}/acs/acs5"
OUT_DIR = RAW / "acs"
MATCH_THRESHOLD = 0.99  # a vintage "is on" a tract vintage if >= 99% of its tracts exist in that shapefile ...
COVER_THRESHOLD = 0.95  # ... and it covers >= 95% of that shapefile's tracts

# Feature candidates: group -> variables. 65+ = male B01001_020-025 and female B01001_044-049.
FEATURE_VARS = {
    "population": ["B01003_001E"],
    "poverty": ["B17001_001E", "B17001_002E"],
    "median_household_income": ["B19013_001E"],
    "vehicles": ["B25044_001E", "B25044_003E", "B25044_010E"],
    # B22001 (households receiving SNAP) exists in every vintage; B22010 (SNAP by disability) only from 2008-2012 on.
    "snap_households": ["B22001_001E", "B22001_002E"],
    "tenure": ["B25003_001E", "B25003_003E"],
    "age_65_plus": ["B01001_001E"] + [f"B01001_{i:03d}E" for i in (20, 21, 22, 23, 24, 25, 44, 45, 46, 47, 48, 49)],
    # B23025 is not published in the 2006-2010 vintage; that vintage simply has no labor-force columns
    # (recorded in the manifest as unavailable) instead of a hand-built substitute from B23001.
    "labor_force": ["B23025_003E", "B23025_005E"],
}
BIAS_ONLY_VARS = {
    "race_ethnicity_B03002": [f"B03002_{i:03d}E" for i in (1, 3, 4, 5, 6, 7, 8, 9, 12)],
}


def scrub(text: str, key: str) -> str:
    return text.replace(key, "***")


def fetch(year: int, variables: list[str], key: str) -> pd.DataFrame:
    params = {"get": "NAME," + ",".join(variables), "for": "tract:*", "in": [f"state:{STATE_FIPS}", "county:*"], "key": key}
    try:
        r = requests.get(API.format(year=year), params=params, timeout=120)
        r.raise_for_status()
    except requests.RequestException as e:  # the URL in the message contains the key
        raise RuntimeError(f"ACS {year} request failed: {scrub(str(e), key)}") from None
    if "json" not in r.headers.get("content-type", ""):
        # The API answers 200 + an HTML page for a bad/unactivated key instead of an error status.
        why = ("rejected CENSUS_API_KEY (\"Invalid Key\": keys are 40 hex characters and must be activated "
               "from the emailed link)") if "Invalid Key" in r.text else "returned a non-JSON response"
        raise SystemExit(f"ACS {year}: the Census API {why}. Request a key at https://api.census.gov/data/key_signup.html and put it in .env.")
    rows = r.json()
    df = pd.DataFrame(rows[1:], columns=rows[0])
    df["geoid"] = df["state"] + df["county"] + df["tract"]
    return df


def available_variables(year: int, wanted: list[str]) -> list[str]:
    """Subset of `wanted` that this vintage actually publishes (the API 400s on an unknown variable)."""
    r = requests.get(API.format(year=year) + "/variables.json", timeout=120)
    r.raise_for_status()
    published = r.json()["variables"]
    return [v for v in wanted if v in published]


def geoid_match(ids: set[str], shp_ids: set[str]) -> tuple[float, float]:
    both = len(ids & shp_ids)
    return both / len(ids), both / len(shp_ids)


def main() -> None:
    ensure_dirs()
    load_env()
    key = os.environ.get("CENSUS_API_KEY", "").strip()
    if not key:
        raise SystemExit("CENSUS_API_KEY is not set (put it in .env)")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    shp = {
        "2010": set(gpd.read_file(RAW / "tl_2010_37_tract10.shp")["GEOID10"]),
        "2020": set(gpd.read_file(RAW / "tl_2020_37_tract.shp")["GEOID"]),
    }
    rel = load_release_dates()
    rel = rel[rel["dataset"] == "acs5"].set_index("end_year")
    variables = [v for vs in FEATURE_VARS.values() for v in vs] + [v for vs in BIAS_ONLY_VARS.values() for v in vs]

    manifest = {
        "variables": {**{g: {"vars": v, "bias_analysis_only": False} for g, v in FEATURE_VARS.items()},
                      **{g: {"vars": v, "bias_analysis_only": True} for g, v in BIAS_ONLY_VARS.items()}},
        "api_missing_value_note": "negative sentinel values (e.g. -666666666) are kept as returned; 05 converts them to missing",
        "vintages": {},
    }
    summary = []
    for end in END_YEARS:
        if end not in rel.index:
            raise SystemExit(f"No cited release date for ACS vintage ending {end}; add it to release_dates.csv with a source")
        have = available_variables(end, variables)
        missing = [v for v in variables if v not in have]
        df = fetch(end, have, key)
        df.to_csv(OUT_DIR / f"acs5_{end}_nc_tract.csv", index=False)
        ids = set(df["geoid"])
        m = {v: geoid_match(ids, s) for v, s in shp.items()}
        on = {v: (m[v][0] >= MATCH_THRESHOLD and m[v][1] >= COVER_THRESHOLD) for v in m}
        geography = "2010" if on["2010"] else "2020" if on["2020"] else "neither (not 2010 or 2020 tracts)"
        r = rel.loc[end]
        manifest["vintages"][f"{end - 4}-{end}"] = {
            "end_year": end,
            "url": API.format(year=end) + "?get=NAME,<variables>&for=tract:*&in=state:37&in=county:*",
            "retrieved_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "rows": len(df),
            "variables_unavailable": missing,
            "release_date": r["release_date"].date().isoformat(),
            "release_date_kind": r["date_kind"],
            "release_source_url": r["source_url"],
            "release_corroboration_url": None if pd.isna(r["corroboration_url"]) else r["corroboration_url"],
            "release_note": None if pd.isna(r["note"]) else r["note"],
            "geoid_match": {v: {"acs_tracts_in_shapefile": round(m[v][0], 4), "shapefile_tracts_covered": round(m[v][1], 4)} for v in m},
            "acs_on_2010_tracts": on["2010"],
            "acs_on_2020_tracts": on["2020"],
            "tract_geography": geography,
        }
        summary.append((f"{end - 4}-{end}", len(df), m["2010"], m["2020"], geography, r["release_date"].date().isoformat(), missing))
        time.sleep(0.3)  # be polite to the API

    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"{'vintage':<10}{'rows':>6}  {'in 2010 shp':>11} {'covers':>7}  {'in 2020 shp':>11} {'covers':>7}  {'geography':<12}release")
    for v, n, a, b, g, d, miss in summary:
        print(f"{v:<10}{n:>6}  {a[0]:>11.1%} {a[1]:>7.1%}  {b[0]:>11.1%} {b[1]:>7.1%}  {g[:11]:<12}{d}" + (f"  (no {', '.join(miss)})" if miss else ""))
    print(f"Wrote {OUT_DIR / 'manifest.json'}")


if __name__ == "__main__":
    main()
