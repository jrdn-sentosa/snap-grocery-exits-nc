"""03: turn authorization periods into spells and classify how each spell ended.

Reads : data/interim/retailers_nc_clean.parquet  (all NC retailers, one row per period)
Writes: data/interim/spells.parquet           one row per continuous spell per Record ID
        data/interim/periods_spells.parquet   every period with its spell_id (04 uses it to get
                                              the store type that was active on a given Jan 1)

Rules (all logged via common.log_step):
  * Same-Record-ID periods separated by <= 90 days (or overlapping) are ONE spell; a longer gap
    ends the spell and the later period starts a new one (exit, then re-entry).
  * Ownership change: a DIFFERENT Record ID at the same address_key whose spell starts from
    30 days before to 90 days after this spell's end. The end is then NOT an exit.
  * true_exit = spell has an end date and is not an ownership change.
  * exit_is_batch = qa_batch_end for true exits (missing otherwise). Never a model feature.

Test-set discipline: structural counts (periods -> spells) cover all years, but any count that
depends on how spells ENDED (gap buckets, ownership changes, exits, batch exits) is reported
only for end dates through DATA_THROUGH (2021-12-31). Per-row classifications are stored for all
years because 04 needs them to build labels; nobody summarizes them for 2022+.
"""

import pandas as pd

from common import DATA_THROUGH, GROCERY_TYPES, INTERIM, ensure_dirs, log_step, start_log

SCRIPT = "03_spells"
MERGE_GAP_DAYS = 90
OWNERSHIP_WINDOW = (-30, 90)  # successor start minus predecessor end, in days
CUTOFF = pd.Timestamp(DATA_THROUGH)


def assign_spells(p: pd.DataFrame) -> tuple[pd.DataFrame, list[tuple[str, pd.Timestamp]], dict[str, int]]:
    """Add spell_no and the running spell end to periods sorted by (record_id, period_seq).

    Returns the periods, one (gap_bucket, earlier_end) per consecutive same-ID pair (so callers can
    count only pairs whose earlier period ended through DATA_THROUGH), and anomaly counters.
    """
    p = p.copy()
    p["spell_no"] = 1
    p["_run_end"] = p["end_date"]
    pairs: list[tuple[str, pd.Timestamp]] = []
    anomalies = {"prior_period_open": 0, "next_start_missing": 0, "nested_period": 0}
    multi = p.groupby("record_id")["period_seq"].transform("size") > 1
    for _, g in p[multi].groupby("record_id", sort=False):
        k, cur_end = 1, None
        for n, (i, row) in enumerate(zip(g.index, g.itertuples())):
            if n == 0:
                cur_end = row.end_date
                continue
            earlier_end = cur_end
            if pd.isna(row.auth_date):
                # A placeholder start gives no gap to measure; treat conservatively as a new spell.
                anomalies["next_start_missing"] += 1
                k += 1
                bucket = "start_missing"
                cur_end = row.end_date
            elif pd.isna(cur_end):
                # Earlier period still open yet another period begins: they overlap -> one spell.
                anomalies["prior_period_open"] += 1
                bucket = "prior_open"
                cur_end = row.end_date
            else:
                gap = (row.auth_date - cur_end).days
                if gap <= MERGE_GAP_DAYS:
                    bucket = "overlap" if gap < 0 else "bridged_0_90"
                    if pd.isna(row.end_date):
                        cur_end = row.end_date
                    elif row.end_date < cur_end:
                        anomalies["nested_period"] += 1  # keep the later end
                    else:
                        cur_end = row.end_date
                else:
                    bucket = "gap_gt_90"
                    k += 1
                    cur_end = row.end_date
            pairs.append((bucket, earlier_end))
            p.loc[i, "spell_no"] = k
            p.loc[i, "_run_end"] = cur_end
    return p, pairs, anomalies


def main() -> None:
    ensure_dirs()
    start_log(SCRIPT)
    per = pd.read_parquet(INTERIM / "retailers_nc_clean.parquet")
    per = per.sort_values(["record_id", "period_seq"]).reset_index(drop=True)
    n_periods = len(per)

    # 1. Periods -> spells (same Record ID, gap <= 90 days or overlapping = continuous).
    p, pairs, anomalies = assign_spells(per)
    p["spell_id"] = p["record_id"].astype(str) + "-" + p["spell_no"].astype(str)

    first = p.drop_duplicates("spell_id", keep="first").set_index("spell_id")
    last = p.drop_duplicates("spell_id", keep="last").set_index("spell_id")
    spells = pd.DataFrame({
        "record_id": first["record_id"],
        "spell_seq": first["spell_no"],
        "n_periods": p.groupby("spell_id", sort=False).size(),
        "spell_start": first["auth_date"],
        "start_placeholder": first["auth_date_placeholder"],
        "spell_end": last["_run_end"],
        "store_type_first": first["store_type"],
        "store_type_last": last["store_type"],
        "address_key_first": first["address_key"],
        "address_key_last": last["address_key"],
        "store_name": last["store_name"],
        "name_std": last["name_std"],
        "street_number": last["street_number"],
        "street_name": last["street_name"],
        "city": last["city"],
        "zip5": last["zip5"],
        "county": last["county"],
        "latitude": last["latitude"],
        "longitude": last["longitude"],
        "qa_batch_end": last["qa_batch_end"],
    }).reset_index()
    # qa_batch_end is taken from the last period; make sure that period is the one that sets the end.
    end_mismatch = int((last["_run_end"].values != last["end_date"].values)[
        ~(last["_run_end"].isna().values & last["end_date"].isna().values)
    ].sum())
    log_step(SCRIPT, "periods_to_spells",
             f"merge same-Record-ID periods when gap <= {MERGE_GAP_DAYS} days or overlapping; longer gap starts a new spell. "
             f"{end_mismatch} spells have a spell_end that differs from their last period's end (nested periods)",
             "Brief re-authorization lapses are paperwork, not store exits; longer gaps are real exit + re-entry",
             n_periods, len(spells), n_periods - len(spells))

    # 2. Gap buckets between consecutive same-ID periods, reported for earlier periods that ended
    #    through DATA_THROUGH only (they depend on end dates, i.e. outcomes).
    in_scope = [b for b, e in pairs if pd.notna(e) and e <= CUTOFF]
    counts = pd.Series(in_scope).value_counts()
    bucket_txt = ", ".join(f"{b}={int(counts.get(b, 0))}" for b in ("overlap", "bridged_0_90", "gap_gt_90"))
    log_step(SCRIPT, "same_id_gap_buckets",
             f"consecutive same-Record-ID period pairs whose earlier period ended through {DATA_THROUGH}: {bucket_txt}; "
             f"anomalies (all years, structural): earlier period still open={anomalies['prior_period_open']}, "
             f"later start is placeholder={anomalies['next_start_missing']}",
             "Shows how many re-authorizations the 90-day bridge absorbs versus how many it splits",
             len(in_scope), len(in_scope), int(counts.get("overlap", 0) + counts.get("bridged_0_90", 0)))

    # 3. Ownership change: different Record ID, same address_key, successor starts -30..+90 days
    #    around this spell's end. Nearest start date wins; ties go to the lower gap, then Record ID.
    ended = spells.loc[spells["spell_end"].notna() & spells["address_key_last"].notna(),
                       ["spell_id", "record_id", "address_key_last", "spell_end"]]
    cand = spells.loc[spells["spell_start"].notna() & spells["address_key_first"].notna(),
                      ["spell_id", "record_id", "store_type_first", "address_key_first", "spell_start"]]
    m = ended.merge(cand, left_on="address_key_last", right_on="address_key_first", suffixes=("", "_succ"))
    m = m[m["record_id"] != m["record_id_succ"]].copy()
    m["gap"] = (m["spell_start"] - m["spell_end"]).dt.days
    m = m[m["gap"].between(*OWNERSHIP_WINDOW)]
    m["abs_gap"] = m["gap"].abs()
    best = (m.sort_values(["spell_id", "abs_gap", "gap", "record_id_succ"])
             .drop_duplicates("spell_id")
             .rename(columns={"spell_id_succ": "successor_spell_id", "record_id_succ": "successor_record_id",
                              "gap": "successor_gap_days", "store_type_first": "successor_store_type"})
             [["spell_id", "successor_spell_id", "successor_record_id", "successor_gap_days", "successor_store_type"]])
    spells = spells.merge(best, on="spell_id", how="left")
    spells["successor_is_grocery"] = spells["successor_store_type"].isin(GROCERY_TYPES).where(spells["successor_spell_id"].notna())
    spells["ownership_change"] = spells["successor_spell_id"].notna()
    spells["true_exit"] = spells["spell_end"].notna() & ~spells["ownership_change"]
    # exit_is_batch: only defined for true exits; nullable so non-exits are missing, not False.
    spells["exit_is_batch"] = spells["qa_batch_end"].astype("boolean").where(spells["true_exit"])

    scope = spells["spell_end"].notna() & (spells["spell_end"] <= CUTOFF)
    n_ended, n_own = int(scope.sum()), int((scope & spells["ownership_change"]).sum())
    many = spells.loc[scope & spells["ownership_change"], "successor_spell_id"].value_counts()
    log_step(SCRIPT, "ownership_change",
             f"successor = different Record ID, same address_key, starts {OWNERSHIP_WINDOW[0]}..+{OWNERSHIP_WINDOW[1]} days from spell end; "
             f"spells ended through {DATA_THROUGH}; {int((many > 1).sum())} successors are claimed by more than one predecessor",
             "Ownership transfers are not loss of access; they must not count as exits",
             n_ended, n_ended - n_own, n_own)

    te = scope & spells["true_exit"]
    n_batch = int((te & spells["exit_is_batch"].fillna(False)).sum())
    log_step(SCRIPT, "true_exit_and_batch",
             f"true_exit = ended and not ownership change; exit_is_batch = qa_batch_end among true exits (ended through {DATA_THROUGH}); rows_after = true exits",
             "Primary label counts all true exits; strict label (04) excludes batch ends",
             n_ended, int(te.sum()), n_batch)

    spells = spells[[
        "spell_id", "record_id", "spell_seq", "n_periods", "spell_start", "start_placeholder", "spell_end",
        "store_type_first", "store_type_last", "address_key_first", "address_key_last",
        "store_name", "name_std", "street_number", "street_name", "city", "zip5", "county",
        "latitude", "longitude",
        "successor_spell_id", "successor_record_id", "successor_gap_days", "successor_store_type",
        "successor_is_grocery", "ownership_change", "true_exit", "qa_batch_end", "exit_is_batch",
    ]]
    spells.to_parquet(INTERIM / "spells.parquet", index=False)
    # Location/name columns ride along so 04 can take them from the period in force on a given
    # Jan 1 (a store that moved must not be placed at its future address).
    p[["record_id", "period_seq", "spell_id", "store_type", "is_grocery", "is_convenience", "auth_date", "end_date",
       "store_name", "name_std", "address_key", "zip5", "county", "latitude", "longitude"]].to_parquet(
        INTERIM / "periods_spells.parquet", index=False)
    log_step(SCRIPT, "write_spells", "write spells.parquet and periods_spells.parquet",
             "Handoff to 04_panel", len(spells), len(spells), 0)

    # Console summary (structural counts, plus end-dependent counts through DATA_THROUGH only).
    g_last = spells["store_type_last"].isin(GROCERY_TYPES)
    g_first = spells["store_type_first"].isin(GROCERY_TYPES)
    print("\nSpell summary")
    print(f"  periods                      {n_periods:>7,}")
    print(f"  spells                       {len(spells):>7,}   (Record IDs {spells['record_id'].nunique():,})")
    print(f"  Record IDs with >1 spell     {int((spells.groupby('record_id').size() > 1).sum()):>7,}")
    print(f"  spells with >1 period        {int((spells['n_periods'] > 1).sum()):>7,}")
    print(f"  spells whose type is grocery {int((g_first | g_last).sum()):>7,}   (first or last period)")
    print(f"  start placeholder            {int(spells['start_placeholder'].sum()):>7,}")
    print(f"  --- end-dependent, spells ended through {DATA_THROUGH} ---")
    print(f"  ended                        {n_ended:>7,}")
    print(f"  ownership change             {n_own:>7,}")
    print(f"  true exit                    {int(te.sum()):>7,}  (batch {n_batch:,})")
    gscope = scope & (g_first | g_last)
    print(f"  grocery ended / own / exit   {int(gscope.sum()):>7,} / {int((gscope & spells['ownership_change']).sum()):,} / {int((gscope & spells['true_exit']).sum()):,}")
    print(f"  gap buckets (same ID)        {bucket_txt}")


if __name__ == "__main__":
    main()
