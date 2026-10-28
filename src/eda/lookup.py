"""Look up one store's (or a chain's) history with everything after 2021-12-31 CENSORED by default.

  uv run python src/eda/lookup.py --name "earth fare"
  uv run python src/eda/lookup.py --record 740603

Why: the 2022-2024 cohorts are the reserved test set, and authorization events after the data cut-off can reveal their
outcomes (a store that is still authorized in 2025 has exit_12m = 0 in every test year). By default this helper
  * drops authorization periods that began after 2021-12-31,
  * shows an end date after 2021-12-31 as missing ("still authorized at the cut-off"; end_censored = True),
  * clears the flags derived from such an end date (qa_batch_end, re-entry, successor facts that start after the cut-off),
  * returns store-years of the train and validation cohorts only (the reserved test file is not opened).

`include_test_period=True` lifts the censoring. It needs a written `reason` and appends a line to
docs/test_reservation_log.md, so every glimpse of the test period is on record.
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "prep"))
from common import DATA_THROUGH, DOCS, INTERIM, VAL_END_YEAR  # noqa: E402

CUTOFF = pd.Timestamp(DATA_THROUGH)
LOG = DOCS / "test_reservation_log.md"


def _log_glimpse(selection: str, reason: str) -> None:
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"\n### {datetime.now():%Y-%m-%d %H:%M} (lookup.py, include_test_period=True)\n"
                f"- **Selection:** {selection}\n- **Why the test period was lifted:** {reason}\n"
                "- **Nothing from it may feed a label, rule, threshold, feature, figure or reported statistic.**\n")


def history(name: str | None = None, record_id: int | list[int] | None = None,
            include_test_period: bool = False, reason: str | None = None) -> dict[str, pd.DataFrame]:
    """Periods, spells and store-years of the selected stores. Censored after 2021-12-31 unless include_test_period=True."""
    if name is None and record_id is None:
        raise ValueError("give a name pattern or a record_id")
    if include_test_period and not (reason and reason.strip()):
        raise ValueError("include_test_period=True needs a reason; it is written to docs/test_reservation_log.md")
    per = pd.read_parquet(INTERIM / "retailers_nc_clean.parquet")
    sp = pd.read_parquet(INTERIM / "spells.parquet")
    panel = pd.read_parquet(INTERIM / "panel_trainval.parquet")
    if include_test_period:
        panel = pd.concat([panel, pd.read_parquet(INTERIM / "panel_test.parquet")], ignore_index=True)
        _log_glimpse(f"name={name!r}, record_id={record_id!r}", reason.strip())

    ids = set()
    if record_id is not None:
        ids |= set([record_id] if isinstance(record_id, int) else record_id)
    if name is not None:
        ids |= set(per.loc[per["store_name"].str.contains(name, case=False, na=False), "record_id"])
    per, sp, panel = per[per.record_id.isin(ids)].copy(), sp[sp.record_id.isin(ids)].copy(), panel[panel.record_id.isin(ids)].copy()
    out = {"omitted_after_cutoff": pd.DataFrame()}
    if not include_test_period:
        n_late = int((per["auth_date"] > CUTOFF).sum())
        per = per[per["auth_date"].isna() | (per["auth_date"] <= CUTOFF)]
        late_end = per["end_date"] > CUTOFF
        per["end_censored"] = late_end
        per.loc[late_end, "end_date"] = pd.NaT
        per.loc[late_end, ["qa_batch_end", "qa_zero_length_period", "qa_end_before_auth"]] = False
        sp = sp[sp["spell_start"].isna() | (sp["spell_start"] <= CUTOFF)]
        sp_late = sp["spell_end"] > CUTOFF
        sp["end_censored"] = sp_late
        reentry_late = (sp["spell_end"] + pd.to_timedelta(sp["qa_reentry_gap_days"].astype("float"), unit="D")) > CUTOFF  # before spell_end is blanked
        for c in ("spell_end", "ownership_change", "true_exit", "qa_batch_end", "exit_is_batch", "successor_spell_id", "successor_record_id",
                  "successor_gap_days", "successor_basis", "successor_name_sim", "successor_distance_mi"):
            sp[c] = sp[c].astype("object").where(~sp_late, None)      # .where upcasts, so boolean columns can hold the blank
        sp["qa_reentry_gap_days"] = sp["qa_reentry_gap_days"].astype("object").where(~reentry_late, None)
        sp["qa_reentered_later"] = sp["qa_reentered_later"].astype("object").where(~reentry_late, False)
        panel = panel[panel["year"] <= VAL_END_YEAR].copy()
        pl = panel["qa_spell_end"] > CUTOFF
        rs = (panel["qa_spell_end"] + pd.to_timedelta(panel["qa_reentry_gap_days"].astype("float"), unit="D")) > CUTOFF
        panel["qa_spell_end"] = panel["qa_spell_end"].where(~pl, pd.NaT)
        for c in ("qa_reentered_later", "qa_reentry_gap_days"):
            panel[c] = panel[c].astype("object").where(~rs, None)
        out["omitted_after_cutoff"] = pd.DataFrame({"periods that began after the cut-off (not shown)": [n_late]})
    out["periods"] = per.sort_values(["record_id", "period_seq"])
    out["spells"] = sp.sort_values(["record_id", "spell_seq"])
    out["store_years"] = panel.sort_values(["record_id", "year"])
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--name", help="case-insensitive store-name pattern")
    ap.add_argument("--record", type=int, nargs="*", help="one or more Record IDs")
    ap.add_argument("--include-test-period", action="store_true", help="lift the censoring (needs --reason; logged)")
    ap.add_argument("--reason", help="why the test period is needed")
    a = ap.parse_args()
    r = history(name=a.name, record_id=a.record, include_test_period=a.include_test_period, reason=a.reason)
    pd.set_option("display.width", 250); pd.set_option("display.max_columns", 40); pd.set_option("display.max_colwidth", 30)
    print("PERIODS"); print(r["periods"][["record_id", "period_seq", "store_name", "store_type", "address_std", "unit_std", "auth_date", "end_date"] + (["end_censored"] if "end_censored" in r["periods"] else [])].to_string(index=False))
    print("\nSPELLS"); print(r["spells"][["spell_id", "spell_start", "spell_end", "ownership_change", "successor_record_id", "successor_gap_days", "successor_basis", "true_exit"]].to_string(index=False))
    print("\nSTORE-YEARS (last 3 per store)"); print(r["store_years"].groupby("record_id").tail(3)[["record_id", "year", "split", "exit_12m", "exit_12m_strict", "qa_ownership_change_in_year"]].to_string(index=False))
    if not r["omitted_after_cutoff"].empty:
        print(f"\n(data after {DATA_THROUGH} is censored; {int(r['omitted_after_cutoff'].iloc[0, 0])} period(s) that began later are not shown)")


if __name__ == "__main__":
    main()
