"""05b: how long did each store LOCATION go without any SNAP authorization after a grocery record ended there? (data through 2021-12-31 only)

Reads : data/interim/periods_spells.parquet, spells.parquet, retailers_nc_clean.parquet
Writes: data/processed/location_gap.parquet   one row per ended grocery-type spell with an end date in 2008-01-01 .. 2021-12-31

Definitions
  * Location: the standardized street address (address_core + ZIP). A period with no street number falls back to its coordinates
    rounded to 4 decimals (about 10 m); periods with neither are left out.
  * For an ended grocery-type spell S at location L, look at every OTHER authorization period at L (any Record ID, any store type,
    including later spells of S's own Record ID):
      - if one is still authorized after S's end date (it started on or before the end date and ends later or is open) the location
        was never uncovered: gap = 0 ("overlaps count as 0", also a successor that starts on the end date);
      - otherwise the gap is the number of days until the next such period STARTS, if it starts on or before 2021-12-31;
      - otherwise the location had no SNAP authorization through the cut-off: 'not re-authorized by 2021-12-31'.
  * Same-Record-ID periods <= 90 days apart are already one spell (03), so a record never leaves a gap <= 90 days with itself.

Test-set discipline (hard rule 1): only ends through 2021-12-31 are examined, authorization periods that start after 2021-12-31 are
dropped before anything is computed, and the output holds no date after the cut-off. Whether a covering period ENDS after the cut-off is
only used as a yes/no (it is still authorized when S ended), never stored.
"""

import numpy as np
import pandas as pd

from common import DATA_THROUGH, GROCERY_TYPES, INTERIM, PROCESSED, TRAIN_END_YEAR, ensure_dirs, log_step, start_log

SCRIPT = "05b_location_gaps"
CUTOFF = pd.Timestamp(DATA_THROUGH)
FIRST_END = pd.Timestamp("2008-01-01")      # the first cohort year
CLASSES = ["0 days", "1-90 days", "91-365 days", "more than 365 days", "not re-authorized by 2021-12-31"]
NEG_INF, POS_INF = np.datetime64("1900-01-01"), np.datetime64("2200-01-01")


def gap_class(days: float | None) -> str:
    if days is None or pd.isna(days):
        return CLASSES[4]
    d = int(days)
    return CLASSES[0] if d == 0 else CLASSES[1] if d <= 90 else CLASSES[2] if d <= 365 else CLASSES[3]


def main() -> None:
    ensure_dirs()
    start_log(SCRIPT)
    per = pd.read_parquet(INTERIM / "periods_spells.parquet")
    addr = pd.read_parquet(INTERIM / "retailers_nc_clean.parquet")[["record_id", "period_seq", "address_core"]]
    per = per.merge(addr, on=["record_id", "period_seq"], how="left")
    sp = pd.read_parquet(INTERIM / "spells.parquet").set_index("spell_id")

    # nothing that starts after the cut-off is looked at; an end date after it only means "still authorized"
    per = per[per["auth_date"].isna() | (per["auth_date"] <= CUTOFF)].copy()
    loc_addr = per["address_core"] + "|" + per["zip5"]
    loc_xy = "xy:" + per["latitude"].round(4).astype(str) + "," + per["longitude"].round(4).astype(str)
    per["loc"] = loc_addr.fillna(loc_xy.where(per["latitude"].notna()))
    n_no_loc = int(per["loc"].isna().sum())
    per = per[per["loc"].notna()]
    per["s"] = per["auth_date"].fillna(pd.Timestamp(NEG_INF)).to_numpy()
    per["e"] = per["end_date"].where(per["end_date"].isna() | (per["end_date"] <= CUTOFF), pd.NaT).fillna(pd.Timestamp(POS_INF)).to_numpy()
    by_loc = {k: (g["s"].to_numpy(), g["e"].to_numpy(), g["record_id"].to_numpy(), g["spell_id"].to_numpy()) for k, g in per.groupby("loc")}
    last_loc = per.sort_values("period_seq").groupby("spell_id")["loc"].last()

    ended = sp[sp["spell_end"].between(FIRST_END, CUTOFF) & sp["store_type_last"].isin(GROCERY_TYPES)]
    rows, no_loc = [], 0
    for sid, r in ended.iterrows():
        loc = last_loc.get(sid)
        if loc is None or loc not in by_loc:
            no_loc += 1
            continue
        s, e, rec, spl = by_loc[loc]
        end = np.datetime64(r["spell_end"])
        other = spl != sid
        covered = other & (s <= end) & (e > end)
        nxt = other & (s > end) & (s <= np.datetime64(CUTOFF))
        if covered.any():
            gap, nrec = 0, None
        elif nxt.any():
            j = np.where(nxt)[0][np.argmin(s[nxt])]
            gap, nrec = int((s[j] - end) / np.timedelta64(1, "D")), int(rec[j])
        else:
            gap, nrec = None, None
        rows.append({
            "spell_id": sid, "record_id": int(r["record_id"]), "store_name": r["store_name"], "store_type": r["store_type_last"], "county": r["county"],
            "end_date": r["spell_end"], "end_year": int(r["spell_end"].year), "split": "train" if r["spell_end"].year <= TRAIN_END_YEAR else "validation",
            "is_batch": bool(r["qa_batch_end"]), "end_kind": "ownership change" if r["ownership_change"] else "exit",
            "gap_days": gap, "gap_class": gap_class(gap),
            # the first authorization to start after the end is the same Record ID coming back (a later spell, so more than 90 days away)
            "reauth_same_id": bool(nrec is not None and nrec == int(r["record_id"])),
        })
    out = pd.DataFrame(rows)
    out["gap_days"] = out["gap_days"].astype("Int64")
    assert out["end_date"].max() <= CUTOFF and out["end_year"].max() <= 2021
    out.to_parquet(PROCESSED / "location_gap.parquet", index=False)
    dist = out["gap_class"].value_counts()
    log_step(SCRIPT, "location_gaps",
             f"one row per ended grocery-type spell (end 2008-01-01 to {DATA_THROUGH}) with the days the LOCATION (address_core + ZIP; coordinates if no street number) went without any SNAP authorization "
             f"under any Record ID: {', '.join(f'{c}={int(dist.get(c, 0))}' for c in CLASSES)}; {n_no_loc} periods without any location and {no_loc} spells not locatable were left out",
             "Shows whether an end left the location uncovered, and for how long; nothing after the cut-off is used",
             len(ended), len(out), 0)
    print(out["gap_class"].value_counts().reindex(CLASSES).to_string())
    print(f"rows {len(out):,} of {len(ended):,} ended grocery spells | not locatable: {no_loc}")


if __name__ == "__main__":
    main()
