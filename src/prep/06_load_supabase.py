"""06: load the dashboard tables into Supabase (data through 2021-12-31 only).

Reads : data/processed/store_year_trainval.parquet   (the reserved test file is never opened)
        data/processed/location_gap.parquet (05b), data/interim/retailers_nc_clean.parquet, data/interim/cleaning_log.csv
        supabase/schema.sql                           (column lists, checked against the frames)
        .env: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY (the key that may write; never used by the dashboard)
Writes: Supabase tables store_year, snap_retailers_nc, cleaning_log, data_meta, location_gap
        (create them first by running supabase/schema.sql in the Supabase SQL editor).

  uv run python src/prep/06_load_supabase.py             # insert what is missing (a second run inserts 0)
  uv run python src/prep/06_load_supabase.py --dry-run   # build and check every table, no network
  uv run python src/prep/06_load_supabase.py --replace   # delete the rows of the selected tables, then reload
  uv run python src/prep/06_load_supabase.py --tables location_gap   # only some tables (also works with --replace)

Rows go in as batched upserts of 500 on each table's primary key with duplicates ignored, so re-runs are safe
(gacha pattern). Because existing rows are left alone, changed data needs --replace.

Test-set discipline (hard rule 1): only train and validation store-years (2008-2021) are loaded. In
snap_retailers_nc, authorizations that began after 2021-12-31 are not loaded and end dates after 2021-12-31
are blanked ("still authorized at the cut-off"), with the qa_ flags derived from an end date cleared for those
rows, so the dashboard cannot show test-period exits. The schema's CHECK constraints enforce the same rules.
"""

import argparse
import json
import os
import re
import sys

import pandas as pd

from common import DATA_THROUGH, INTERIM, PIPELINE_ORDER, PROCESSED, ROOT, VAL_END_YEAR, ensure_dirs, load_env, log_step, start_log
from matching import MERGE_GAP_DAYS, ownership_rule_text

SCRIPT = "06_load_supabase"
SCHEMA = ROOT / "supabase" / "schema.sql"
BATCH = 500
CUTOFF = pd.Timestamp(DATA_THROUGH)
PKS = {
    "store_year": ["record_id", "year"],
    "snap_retailers_nc": ["record_id", "period_seq"],
    "cleaning_log": ["script", "seq"],
    "data_meta": ["key"],
    "location_gap": ["spell_id"],
}
# a value that matches no real row, for the delete-everything filter of --replace
DELETE_FILTER = {"store_year": ("record_id", -1), "snap_retailers_nc": ("record_id", -1), "cleaning_log": ("seq", -1), "data_meta": ("key", ""), "location_gap": ("end_year", -1)}


def schema_columns() -> dict[str, list[str]]:
    """Column names per table, parsed from supabase/schema.sql (so loader and schema cannot drift apart)."""
    sql = SCHEMA.read_text(encoding="utf-8")
    out = {}
    for m in re.finditer(r"create table if not exists (\w+) \((.*?)\n\);", sql, flags=re.S):
        cols = []
        for line in m.group(2).splitlines():
            line = line.split("--")[0].strip()
            if line and not line.lower().startswith("primary key"):
                cols.append(line.split()[0])
        out[m.group(1)] = cols
    return out


def to_records(df: pd.DataFrame) -> list[dict]:
    """JSON-ready rows: NaN / NA / NaT become null, dates become YYYY-MM-DD strings."""
    out = df.copy()
    for c in out.columns:
        if str(out[c].dtype).startswith("datetime64"):
            out[c] = out[c].dt.strftime("%Y-%m-%d").astype("object").where(out[c].notna(), None)
    return json.loads(out.to_json(orient="records", double_precision=15))


def build_frames(log: bool) -> dict[str, pd.DataFrame]:
    cols = schema_columns()

    # --- store_year: train + validation only ---
    sy = pd.read_parquet(PROCESSED / "store_year_trainval.parquet")
    assert sy["year"].max() <= VAL_END_YEAR and sy["split"].isin(["train", "validation"]).all(), "test-year row in the load"
    sy = sy[cols["store_year"]]

    # --- snap_retailers_nc: nothing after the data cut-off ---
    ret = pd.read_parquet(INTERIM / "retailers_nc_clean.parquet")
    n0 = len(ret)
    ret = ret[ret["auth_date"].isna() | (ret["auth_date"] <= CUTOFF)].copy()  # authorizations that began after the cut-off do not exist yet
    n1 = len(ret)
    late_end = ret["end_date"] > CUTOFF
    n_blanked = int(late_end.sum())
    ret.loc[late_end, "end_date"] = pd.NaT  # still authorized as of the cut-off
    # flags derived from an end date would reveal it: clear them for the blanked rows
    for flag in ("qa_batch_end", "qa_zero_length_period", "qa_end_before_auth"):
        ret.loc[late_end, flag] = False
    assert ret["end_date"].dropna().max() <= CUTOFF and ret["auth_date"].dropna().max() <= CUTOFF
    ret = ret[cols["snap_retailers_nc"]]
    if log:
        log_step(SCRIPT, "retailers_cutoff_start", f"snap_retailers_nc: drop authorizations that began after {DATA_THROUGH}",
                 "The dashboard shows data through the cut-off; later authorizations are outside it", n0, n1)
        log_step(SCRIPT, "retailers_cutoff_end", f"snap_retailers_nc: end dates after {DATA_THROUGH} set to missing (shown as still authorized) and the qa_ flags derived from them cleared",
                 "Hard rule 1: the public dashboard must not show test-period (2022-2024) exits", n1, n1, n_blanked)

    # --- cleaning_log (read after the two rows above were appended) and data_meta ---
    cl = pd.read_csv(INTERIM / "cleaning_log.csv")
    # the log must describe the current run of every script: start_log drops a script's rows and all later ones when it starts
    missing = [x for x in PIPELINE_ORDER[:-1] if x not in set(cl["script"])]
    if missing or cl["step_type"].isna().any():
        raise SystemExit(f"data/interim/cleaning_log.csv is incomplete (no rows for {missing or 'none'}, step_type missing: {int(cl['step_type'].isna().sum())}); "
                         "rerun the prep scripts 01-05b in order, then load")
    cl = cl[cols["cleaning_log"]]
    meta = pd.DataFrame([
        ("data_through", str(DATA_THROUGH)),
        ("cohort_years_loaded", "2008-2021 (train 2008-2018, validation 2019-2021)"),
        ("test_set", "The 2022-2024 cohorts are reserved and not loaded; end dates after 2021-12-31 are blank in snap_retailers_nc."),
        ("sources", "USDA FNS SNAP Retailer Locator 2005-2025; ACS 5-year tract tables; USDA ERS RUCA; Census TIGER/Line tracts."),
        # the rule in words and its one structural constant, so the dashboard states them without hard-coding numbers
        ("ownership_rule", ownership_rule_text()),
        ("merge_gap_days", str(MERGE_GAP_DAYS)),
    ], columns=cols["data_meta"])

    # --- location_gap: ended grocery records, ends through the cut-off only (built by 05b_location_gaps.py) ---
    lg = pd.read_parquet(PROCESSED / "location_gap.parquet")
    assert lg["end_date"].max() <= CUTOFF and lg["end_year"].max() <= VAL_END_YEAR, "a date after the cut-off in location_gap"
    lg = lg[cols["location_gap"]]
    return {"store_year": sy, "snap_retailers_nc": ret, "cleaning_log": cl, "data_meta": meta, "location_gap": lg}


def check_frames(frames: dict[str, pd.DataFrame]) -> None:
    for t, df in frames.items():
        assert not df.duplicated(PKS[t]).any(), f"{t}: duplicate primary keys"
        assert df[PKS[t]].notna().all().all(), f"{t}: null in a primary key"
        json.dumps(to_records(df), allow_nan=False)  # strict: a stray NaN would make the REST payload invalid
    print("Checks passed: columns match supabase/schema.sql, primary keys unique, rows serialize to strict JSON, no row after 2021-12-31.")
    for t, df in frames.items():
        print(f"  {t:<18} {len(df):>7,} rows, {df.shape[1]} columns")


def db_count(client, table: str) -> int:
    return client.table(table).select("*", count="exact").limit(1).execute().count or 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="build and check the tables, do not touch Supabase")
    ap.add_argument("--replace", action="store_true", help="delete all rows of the selected tables first, then load")
    ap.add_argument("--tables", help="comma-separated subset of tables to load (default: all)")
    args = ap.parse_args()
    ensure_dirs()
    if not args.dry_run:
        start_log(SCRIPT)
    frames = build_frames(log=not args.dry_run)
    if args.tables:
        wanted = [t.strip() for t in args.tables.split(",")]
        unknown = [t for t in wanted if t not in frames]
        if unknown:
            raise SystemExit(f"Unknown table(s) {unknown}; known: {list(frames)}")
        frames = {t: frames[t] for t in wanted}
    check_frames(frames)
    if args.dry_run:
        return 0

    load_env()
    url, key = os.environ.get("SUPABASE_URL", "").strip(), os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not url or not key:
        raise SystemExit("Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in .env (the service-role key is used only by this loader).")
    from supabase import create_client

    client = create_client(url, key)
    for t in frames:  # preflight: the schema must have been run
        try:
            db_count(client, t)
        except Exception as exc:
            raise SystemExit(f"Cannot read table '{t}': {type(exc).__name__}: {str(exc)[:200]}\n"
                             "Run supabase/schema.sql in the Supabase SQL editor first.") from None

    if args.replace:
        for t, (col, sentinel) in ((t, DELETE_FILTER[t]) for t in frames):
            client.table(t).delete().neq(col, sentinel).execute()
            print(f"  deleted existing rows of {t}")

    failed_total, mismatches = 0, []
    print(f"\n{'table':<18}{'read':>9}{'inserted':>10}{'already there':>15}{'failed':>8}{'in DB now':>11}")
    for t, df in frames.items():
        records = to_records(df)
        inserted = failed = 0
        for i in range(0, len(records), BATCH):
            batch = records[i:i + BATCH]
            try:
                res = client.table(t).upsert(batch, on_conflict=",".join(PKS[t]), ignore_duplicates=True).execute()
                inserted += len(res.data or [])  # with ignore_duplicates only newly inserted rows come back
            except Exception as exc:
                failed += len(batch)
                print(f"  batch {i // BATCH} of {t} failed ({len(batch)} rows): {type(exc).__name__}: {str(exc)[:200]}", file=sys.stderr)
        now = db_count(client, t)
        print(f"{t:<18}{len(records):>9,}{inserted:>10,}{len(records) - inserted - failed:>15,}{failed:>8,}{now:>11,}")
        failed_total += failed
        if now != len(records):
            mismatches.append((t, now, len(records)))
    if failed_total or mismatches:
        for t, now, expected in mismatches:
            hint = " (extra rows from an earlier load: rerun with --replace)" if now > expected else ""
            print(f"MISMATCH {t}: {now:,} rows in the database, {expected:,} expected{hint}", file=sys.stderr)
        return 1
    print("\nAll tables loaded and row counts match.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
