"""Shared paths, constants, and the cleaning-log helper for the prep scripts.

Not numbered because the numbered scripts (01_load.py, ...) cannot be imported by name.
Scripts run as `uv run python src/prep/NN_*.py`, so this folder is on sys.path and
`from common import ...` works.
"""

from datetime import date
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
INTERIM = ROOT / "data" / "interim"
PROCESSED = ROOT / "data" / "processed"
DOCS = ROOT / "docs"
FIGURES = ROOT / "figures"

SNAP_CSV = RAW / "Historical SNAP Retailer Locator Data 2005-2025.csv"

# Fixed chronological split (CLAUDE.md). Test rows are never used for outcome statistics.
TRAIN_END_YEAR = 2018
VAL_END_YEAR = 2021
TEST_YEARS = (2022, 2023, 2024)
COHORT_YEARS = tuple(range(2008, 2025))
# Anything derived from outcomes (thresholds, rates) may only look at dates up to here.
DATA_THROUGH = date(2021, 12, 31)

GROCERY_TYPES = (
    "Supermarket",
    "Super Store",
    "Large Grocery Store",
    "Medium Grocery Store",
    "Small Grocery Store",
)
CONVENIENCE_TYPE = "Convenience Store"

RELEASE_DATES_CSV = ROOT / "src" / "prep" / "reference" / "release_dates.csv"

# 4-way urban-rural grouping of USDA primary RUCA codes (analyst choice, documented in the data dictionary):
#   1 metropolitan core -> urban; 2-3 metropolitan high/low commuting -> metro fringe (not "suburban":
#   these tracts are defined by commuting flows to a metro area, and many are rural in character);
#   4-9 micropolitan and small-town tracts -> small town; 10 -> rural; 99 (zero-population water tract) -> unclassified.
RUCA_GROUP_ORDER = ["urban", "metro fringe", "small town", "rural", "unclassified"]


def ruca_group(code) -> str | None:
    if pd.isna(code):
        return None
    code = int(code)
    if code == 1:
        return "urban"
    if code in (2, 3):
        return "metro fringe"
    if 4 <= code <= 9:
        return "small town"
    if code == 10:
        return "rural"
    return "unclassified"


def load_release_dates() -> pd.DataFrame:
    """Curated, cited release dates (src/prep/reference/release_dates.csv) used by the timing rule."""
    return pd.read_csv(RELEASE_DATES_CSV, parse_dates=["release_date"])


CLEANING_LOG_CSV = INTERIM / "cleaning_log.csv"
CLEANING_LOG_MD = DOCS / "cleaning_log.md"
_LOG_COLS = ["script", "seq", "step", "step_type", "rule", "why", "rows_before", "rows_after", "rows_affected"]
_COUNT_COLS = ["seq", "rows_before", "rows_after", "rows_affected"]
# The scripts in run order. Re-running one invalidates the log rows of every later one (they describe its old output), so start_log drops
# them too; running 01 therefore rewrites the whole log from scratch, and 06 refuses to load a log with a script missing.
PIPELINE_ORDER = ["01_load", "02_clean", "03_spells", "04_panel", "05_features", "05b_location_gaps", "06_load_supabase"]
# What each step does, so the exported log can be filtered:
#   filter    drops rows                       transform  rewrites or derives values (rows kept)
#   flag      adds a marker / classification   audit      counts or checks only, nothing is changed
#   build     creates or writes a table
# rows_before / rows_after are left blank for audit and build steps (the step has no input-to-output row count); rows_affected stays.
STEP_TYPES = {
    ("01_load", "keep_nc"): "filter", ("01_load", "ruca_2010_nc"): "filter", ("01_load", "ruca_2020_nc"): "filter",
    ("02_clean", "trim_whitespace"): "transform", ("02_clean", "collapse_internal_spaces"): "transform", ("02_clean", "parse_dates"): "transform",
    ("02_clean", "auth_date_placeholder"): "transform", ("02_clean", "flag_odd_periods"): "flag", ("02_clean", "coords"): "transform",
    ("02_clean", "zip"): "transform", ("02_clean", "city_format"): "transform", ("02_clean", "city_zip_variants"): "transform",
    ("02_clean", "county"): "transform", ("02_clean", "store_type_flags"): "flag", ("02_clean", "address_std"): "transform",
    ("02_clean", "store_name"): "flag", ("02_clean", "qa_batch_end"): "flag", ("02_clean", "drop_exact_duplicates"): "filter",
    ("02_clean", "write_clean"): "build",
    ("03_spells", "periods_to_spells"): "build", ("03_spells", "same_id_gap_buckets"): "audit", ("03_spells", "ownership_change"): "flag",
    ("03_spells", "successor_type_change"): "flag", ("03_spells", "true_exit_and_batch"): "flag", ("03_spells", "write_spells"): "build",
    ("04_panel", "build_store_years"): "build", ("04_panel", "qa_coord_invalid"): "flag", ("04_panel", "tract_2010"): "transform",
    ("04_panel", "tract_2020"): "transform", ("04_panel", "ruca"): "transform", ("04_panel", "impact_dist"): "transform", ("04_panel", "split"): "build",
    ("05_features", "features_trainval"): "build", ("05_features", "features_test"): "build", ("05_features", "acs_sentinels"): "transform",
    ("05b_location_gaps", "location_gaps"): "build",
    ("06_load_supabase", "retailers_cutoff_start"): "filter", ("06_load_supabase", "retailers_cutoff_end"): "transform",
}
STEP_TYPE_NAMES = ("filter", "transform", "flag", "audit", "build")


def step_type_of(script: str, step: str) -> str:
    if step.startswith("override_"):          # one row per reviewed pair in data/reference/successor_overrides.csv (03_spells)
        return "audit"
    try:
        return STEP_TYPES[(script, step)]
    except KeyError:
        raise KeyError(f"cleaning-log step {script}/{step} has no step type: add it to common.STEP_TYPES") from None


def load_env() -> None:
    """Load .env (gitignored) into os.environ; real environment variables win."""
    load_dotenv(ROOT / ".env")


def ensure_dirs() -> None:
    for d in (INTERIM, PROCESSED, DOCS, FIGURES):
        d.mkdir(parents=True, exist_ok=True)


def start_log(script: str) -> None:
    """Drop this script's earlier log rows AND those of every later script in PIPELINE_ORDER, so no row describes a stale run
    (running 01 empties the log; each script then rebuilds its own rows)."""
    ensure_dirs()
    if script not in PIPELINE_ORDER:
        raise ValueError(f"{script} is not in common.PIPELINE_ORDER")
    stale = PIPELINE_ORDER[PIPELINE_ORDER.index(script):]
    if CLEANING_LOG_CSV.exists():
        log = pd.read_csv(CLEANING_LOG_CSV)
        log[~log["script"].isin(stale)].to_csv(CLEANING_LOG_CSV, index=False)


def log_step(
    script: str,
    step: str,
    rule: str,
    why: str,
    rows_before: int,
    rows_after: int,
    rows_affected: int | None = None,
    step_type: str | None = None,
) -> None:
    """Append one cleaning rule with row counts, then re-render docs/cleaning_log.md.

    rows_affected is how many rows the rule changed, flagged, merged or dropped; for a pure drop it defaults to rows_before - rows_after.
    step_type comes from STEP_TYPES unless given; rows_before / rows_after are blanked for audit and build steps.
    """
    ensure_dirs()
    kind = step_type or step_type_of(script, step)
    if kind not in STEP_TYPE_NAMES:
        raise ValueError(f"step_type must be one of {STEP_TYPE_NAMES}, got {kind!r}")
    if rows_affected is None:
        rows_affected = rows_before - rows_after
    shown = (None, None) if kind in ("audit", "build") else (rows_before, rows_after)
    log = pd.read_csv(CLEANING_LOG_CSV) if CLEANING_LOG_CSV.exists() else pd.DataFrame(columns=_LOG_COLS)
    seq = int((log["script"] == script).sum()) + 1
    row = dict(script=script, seq=seq, step=step, step_type=kind, rule=rule, why=why,
               rows_before=shown[0], rows_after=shown[1], rows_affected=rows_affected)
    log = pd.concat([log, pd.DataFrame([row])], ignore_index=True)
    for c in _COUNT_COLS:
        log[c] = pd.to_numeric(log[c]).astype("Int64")        # blanks stay blank (no "22845.0")
    log = log[_LOG_COLS]
    log.to_csv(CLEANING_LOG_CSV, index=False)
    _render_markdown(log)
    print(f"[{script} #{seq}] {step} ({kind}): " + (f"{rows_before:,} -> {rows_after:,}, " if shown[0] is not None else "") + f"affected {rows_affected:,}")


def _render_markdown(log: pd.DataFrame) -> None:
    log = log.sort_values(["script", "seq"])
    count = lambda v: "" if pd.isna(v) else f"{int(v):,}"  # noqa: E731
    lines = [
        "# Cleaning log",
        "",
        "Generated by `src/prep/common.log_step`; do not edit by hand. Row counts are store",
        "authorization periods unless a step says otherwise. Counts are descriptive only; no",
        "outcome statistics are computed on test-year (2022-2024) rows.",
        "",
        "Step types: **filter** drops rows; **transform** rewrites or derives values; **flag** adds a marker or classification; **audit** counts or",
        "checks only; **build** creates or writes a table. Rows before / after are blank for audit and build steps; rows affected is the number of rows",
        "dropped, changed, flagged or merged.",
        "",
        "| Script | # | Step | Type | Rule | Why | Rows before | Rows after | Rows affected |",
        "|---|---|---|---|---|---|---:|---:|---:|",
    ]
    for r in log.itertuples(index=False):
        cells = [str(c).replace("|", "\\|") for c in (r.script, r.seq, r.step, r.step_type, r.rule, r.why)]
        lines.append(f"| {cells[0]} | {cells[1]} | {cells[2]} | {cells[3]} | {cells[4]} | {cells[5]} | {count(r.rows_before)} | {count(r.rows_after)} | {count(r.rows_affected)} |")
    CLEANING_LOG_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
