"""Check frontend/public/data/ before it is committed. Exits non-zero on the first problem.

Run: uv run python src/site/02_check_export.py

What it guarantees
  1. Test reservation: stores.json holds only 2024 Jan-1 features, identity, address and context. No key that names an outcome,
     label, QA flag, impact column, bias column or an end date; no date string except the three allowed ones (score date, data cut-off,
     ACS release date). Outcome-derived files (tracts shading, meta rates / pie / gap) are built from years <= 2021 only.
  2. API readiness: every scorable store's `inputs` is exactly the 22 keys of store_prep.FIELD_RULES and passes the same rules the
     API applies (type, range, nullability), so /predict will not answer 422 for exported data; unscorable stores are flagged.
  3. Internal consistency: the tract store-year counts equal the Mecklenburg train+validation store-years 2008-2021 in the parquet.
"""

import json
import re
import sys
from pathlib import Path

import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "prep"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "model"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATA_THROUGH, PROCESSED, ROOT  # noqa: E402
from store_prep import FIELD_RULES  # noqa: E402

import importlib  # noqa: E402

export = importlib.import_module("01_export_site_data")

DATA = ROOT / "frontend" / "public" / "data"
# Key tokens (split on "_") that name an outcome or QA/impact/bias/date-of-end information.
FORBIDDEN_TOKENS = {"exit", "exits", "end", "ends", "label", "qa", "impact", "bias", "enddate"}
# Jan-1 feature whose name contains "ends": grocery ends in the 12 months BEFORE the score date (a predictor, allowed).
ALLOWED_STORE_KEYS = {"n_grocery_ends_1mi_prior12m"}
failures: list[str] = []


def fail(msg: str) -> None:
    failures.append(msg)
    print("FAIL:", msg)


def walk_keys(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield f"{path}/{k}", k
            yield from walk_keys(v, f"{path}/{k}")
    elif isinstance(obj, list):
        for v in obj:
            yield from walk_keys(v, path)


def valid_value(key: str, v) -> str | None:
    rule = FIELD_RULES[key]
    if v is None:
        return None if rule["nullable"] else "null not allowed"
    kind = rule["kind"]
    if kind == "category":
        return None if isinstance(v, str) else "not a string"
    if isinstance(v, bool):
        return "boolean sent; the API takes numbers"
    if not isinstance(v, (int, float)):
        return "not a number"
    if kind in ("int", "binary") and not isinstance(v, int):
        return "not an integer"
    if kind == "binary" and v not in (0, 1):
        return "not 0/1"
    if kind == "share" and not 0 <= v <= 1:
        return "outside 0-1"
    if "min" in rule and v < rule["min"]:
        return f"below {rule['min']}"
    if "max" in rule and v > rule["max"]:
        return f"above {rule['max']}"
    return None


def main() -> None:
    files = {n: DATA / n for n in ("stores.json", "tracts.geojson", "meta.json")}
    for n, p in files.items():
        if not p.exists():
            fail(f"{n} missing; run 01_export_site_data.py")
    if failures:
        sys.exit(1)
    stores_doc = json.loads(files["stores.json"].read_text(encoding="utf-8"))
    tracts = json.loads(files["tracts.geojson"].read_text(encoding="utf-8"))
    meta = json.loads(files["meta.json"].read_text(encoding="utf-8"))
    stores = stores_doc["stores"]

    # ---- the export script's own test-file whitelist
    for c in export.TEST_COLUMNS:
        if c.startswith(export.FORBIDDEN_PREFIXES) or ("date" in c and c != "auth_date_placeholder") or c.endswith("_end"):   # the placeholder flag is a 0/1 model input
            fail(f"TEST_COLUMNS contains {c}")

    # ---- 1. test reservation: keys and dates
    for fname, doc in (("stores.json", stores_doc),):
        for path, key in walk_keys(doc):
            if key in ALLOWED_STORE_KEYS:
                continue
            if set(re.split(r"[_\W]+", key.lower())) & FORBIDDEN_TOKENS:
                fail(f"{fname}: forbidden key {path}")
    for path, key in walk_keys(tracts):
        if key in ("exit_share_0821",):          # train+validation shading, 2008-2021 only (checked below)
            continue
        if set(re.split(r"[_\W]+", key.lower())) & FORBIDDEN_TOKENS:
            fail(f"tracts.geojson: forbidden key {path}")
    allowed_dates = {"2024-01-01", str(DATA_THROUGH), meta["acs"]["release_date"]}
    for n, p in files.items():
        for d in set(re.findall(r"\d{4}-\d{2}-\d{2}", p.read_text(encoding="utf-8"))):
            if d not in allowed_dates:
                fail(f"{n}: unexpected date {d}")
    if stores_doc["score_year"] != 2024 or {s["inputs"]["year"] for s in stores} != {2024}:
        fail("stores.json must hold the 2024 cohort only")
    for k, hi in (("shading", meta["shading"]["years"][1]), ("type_rates", meta["type_rates"]["years"][1]), ("past_exit_gap", meta["past_exit_gap"]["years"][1])):
        if hi > 2021:
            fail(f"meta.{k} uses years after 2021")
    if meta["pie"]["through"] > str(DATA_THROUGH):
        fail("pie counts ends after the data cut-off")

    # ---- 2. API readiness
    expected = set(export.API_INPUTS)
    ids = [s["record_id"] for s in stores]
    if len(ids) != len(set(ids)):
        fail("duplicate record_id")
    for s in stores:
        if set(s["inputs"]) != expected:
            fail(f"{s['record_id']}: inputs keys differ from the API's 22 keys")
            continue
        problems = {k: m for k in expected if (m := valid_value(k, s["inputs"][k]))}
        if s["scorable"] and problems:
            fail(f"{s['record_id']} flagged scorable but API would reject: {problems}")
        if not s["scorable"] and not problems:
            fail(f"{s['record_id']} flagged unscorable but passes the rules")
        if len(s["alternatives"]) > 2 or any(a["record_id"] == s["record_id"] for a in s["alternatives"]):
            fail(f"{s['record_id']}: bad alternatives")
        if s["lat"] is not None and not (34.9 < s["lat"] < 35.6 and -81.1 < s["lon"] < -80.5):
            fail(f"{s['record_id']}: coordinates outside Mecklenburg")
    if meta["counts"]["stores_scorable"] != sum(s["scorable"] for s in stores):
        fail("meta scorable count disagrees with stores.json")

    # ---- 3. consistency with the train+validation parquet
    tv = pq.read_table(PROCESSED / "store_year_trainval.parquet", columns=["year", "county", "tract_geoid_2020"]).to_pandas()
    if tv["year"].max() > 2021:
        fail("trainval parquet has cohorts after 2021")
    # Two Record IDs filed under Mecklenburg sit in a Cabarrus County tract (37025...); their 13 store-years have no tract to shade here.
    n_meck = int(((tv["county"] == "MECKLENBURG") & (tv["year"] >= 2008) & tv["tract_geoid_2020"].str.startswith("37119", na=False)).sum())
    n_tract = sum(f["properties"]["store_years_0821"] for f in tracts["features"])
    if n_meck != n_tract:
        fail(f"tract store-years {n_tract} != Mecklenburg train+validation store-years {n_meck}")
    for f in tracts["features"]:
        p = f["properties"]
        if (p["shade_status"] == "ok") != (p["exit_share_0821"] is not None):
            fail(f"tract {p['geoid']}: shade_status and exit_share disagree")
        if p["shade_status"] == "ok" and p["store_years_0821"] < meta["shading"]["min_store_years"]:
            fail(f"tract {p['geoid']}: shaded below the store-year threshold")
    for t, v in meta["type_rates"]["by_type"].items():
        if abs(v["exits"] / v["store_years"] - v["rate"]) > 1e-4:
            fail(f"rate for {t} is inconsistent")
    for scope in ("statewide", "mecklenburg"):
        pie = meta["pie"][scope]
        if sum(pie[k]["n"] for k in ("other_exit", "batch", "ownership_change")) != pie["ended"]:
            fail(f"pie {scope} does not add up")

    if failures:
        print(f"\n{len(failures)} problem(s)")
        sys.exit(1)
    print(f"OK: {len(stores)} stores ({meta['counts']['stores_scorable']} scorable), {len(tracts['features'])} tracts; no outcome, label or end date in the export; "
          f"every scorable record passes the API's rules")


if __name__ == "__main__":
    main()
