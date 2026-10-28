"""03: turn authorization periods into spells and classify how each spell ended.

Reads : data/interim/retailers_nc_clean.parquet  (all NC retailers, one row per period)
Writes: data/interim/spells.parquet           one row per continuous spell per Record ID
        data/interim/periods_spells.parquet   every period with its spell_id (04 uses it to get
                                              the store type that was active on a given Jan 1)

Rules (all logged via common.log_step):
  * Same-Record-ID periods separated by <= 90 days (or overlapping) are ONE spell; a longer gap
    ends the spell and the later period starts a new one (exit, then re-entry).
  * Ownership change: a DIFFERENT Record ID within 0.15 mile whose spell is authorized (a) from 365 days before to
    90 days after this spell's end AND has a similar store name (store numbers removed), or (b) from 30 days before
    to 90 days after AND has the identical standardized street address including the unit. The end is then NOT an
    exit. (Definitions and thresholds: matching.py. Replaces the earlier same-address-key, -30/+90-day rule.)
  * true_exit = spell has an end date and is not an ownership change.
  * exit_is_batch = qa_batch_end for true exits (missing otherwise). Never a model feature.

Test-set discipline: structural counts (periods -> spells) cover all years, but any count that
depends on how spells ENDED (gap buckets, ownership changes, exits, batch exits) is reported
only for end dates through DATA_THROUGH (2021-12-31). Per-row classifications are stored for all
years because 04 needs them to build labels; nobody summarizes them for 2022+.
"""

import geopandas as gpd
import numpy as np
import pandas as pd

from common import DATA_THROUGH, GROCERY_TYPES, INTERIM, ensure_dirs, log_step, start_log
from matching import ADDRESS_LOOKBACK_DAYS, AFTER_DAYS, NAME_LOOKBACK_DAYS, NAME_SIM, RADIUS_MI, name_sim

SCRIPT = "03_spells"
MERGE_GAP_DAYS = 90
CUTOFF = pd.Timestamp(DATA_THROUGH)
CRS_GEO, CRS_PROJ, M_PER_MI = "EPSG:4269", "EPSG:32119", 1609.344


def project(lat: pd.Series, lon: pd.Series) -> tuple[np.ndarray, np.ndarray]:
    """State Plane (metres) coordinates; NaN where a coordinate is missing."""
    x, y = np.full(len(lat), np.nan), np.full(len(lat), np.nan)
    ok = (lat.notna() & lon.notna()).to_numpy()
    if ok.any():
        g = gpd.GeoSeries(gpd.points_from_xy(lon[ok], lat[ok]), crs=CRS_GEO).to_crs(CRS_PROJ)
        x[ok], y[ok] = g.x.to_numpy(), g.y.to_numpy()
    return x, y


def _unit(v) -> str | None:
    return v if isinstance(v, str) and v else None


def find_successors(spells: pd.DataFrame) -> pd.DataFrame:
    """For every ended spell, the best successor under the ownership-change rule (see the module docstring), if any.

    Candidates are spells of OTHER Record IDs with a known start within [end - 365 days, end + 90 days] and within RADIUS_MI
    of the ended spell. Rule (a): name similarity >= NAME_SIM (any start in that window). Rule (b): identical address_core
    and unit_std and a start no earlier than 30 days before the end. Preference: address match, then name similarity, then
    the smallest |gap|, then Record ID.
    """
    ended = spells[spells["spell_end"].notna() & spells["latitude"].notna()].reset_index(drop=True)
    cand = spells[spells["spell_start"].notna() & spells["latitude_first"].notna()].sort_values("spell_start").reset_index(drop=True)
    ex_x, ex_y = project(ended["latitude"], ended["longitude"])
    cd_x, cd_y = project(cand["latitude_first"], cand["longitude_first"])
    starts = cand["spell_start"].to_numpy()
    c_rec, c_name, c_core = cand["record_id"].to_numpy(), cand["name_std_first"].to_numpy(object), cand["address_core_first"].to_numpy(object)
    c_unit, c_id, c_type = cand["unit_first"].to_numpy(object), cand["spell_id"].to_numpy(object), cand["store_type_first"].to_numpy(object)
    out = []
    for i, e in enumerate(ended.itertuples()):
        end = np.datetime64(e.spell_end)
        a = np.searchsorted(starts, end - np.timedelta64(NAME_LOOKBACK_DAYS, "D"), "left")
        b = np.searchsorted(starts, end + np.timedelta64(AFTER_DAYS, "D"), "right")
        if b <= a:
            continue
        dist = np.hypot(cd_x[a:b] - ex_x[i], cd_y[a:b] - ex_y[i]) / M_PER_MI
        for j in np.where((dist <= RADIUS_MI) & (c_rec[a:b] != e.record_id))[0] + a:
            gap = int((starts[j] - end) / np.timedelta64(1, "D"))
            same_addr = isinstance(e.address_core_last, str) and c_core[j] == e.address_core_last and _unit(c_unit[j]) == _unit(e.unit_last)
            by_addr = bool(same_addr and gap >= -ADDRESS_LOOKBACK_DAYS)
            sim = name_sim(e.name_std, c_name[j])
            by_name = sim >= NAME_SIM
            if by_addr or by_name:
                out.append((e.spell_id, c_id[j], int(c_rec[j]), gap, c_type[j], "both" if by_addr and by_name else "address" if by_addr else "name",
                            sim, float(dist[j - a]), by_addr))
    cols = ["spell_id", "successor_spell_id", "successor_record_id", "successor_gap_days", "successor_store_type",
            "successor_basis", "successor_name_sim", "successor_distance_mi", "_addr"]
    m = pd.DataFrame(out, columns=cols)
    m["_abs"] = m["successor_gap_days"].abs()
    best = m.sort_values(["spell_id", "_addr", "successor_name_sim", "_abs", "successor_record_id"], ascending=[True, False, False, True, True])
    return best.drop_duplicates("spell_id").drop(columns=["_addr", "_abs"])


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
        # what the ownership-change rule compares: the ended spell's LAST period against a candidate's FIRST period
        "address_core_last": last["address_core"], "unit_last": last["unit_std"],
        "name_std_first": first["name_std"], "address_core_first": first["address_core"], "unit_first": first["unit_std"],
        "latitude_first": first["latitude"], "longitude_first": first["longitude"],
    }).reset_index()
    # Re-entry: the same Record ID is authorized again in a LATER spell (so after a gap of more than 90 days). It looks at events up to
    # the end of the data (Dec 2025), i.e. it uses information from after the exit: a QA flag, never a model feature.
    next_start = spells.groupby("record_id")["spell_start"].shift(-1)
    has_next = spells.groupby("record_id").cumcount(ascending=False) > 0
    spells["qa_reentered_later"] = has_next
    spells["qa_reentry_gap_days"] = ((next_start - spells["spell_end"]).dt.days).astype("Int64").where(has_next)
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

    # 3. Ownership change under the combined rule (module docstring). A renamed or re-registered store opens a new Record ID
    #    near, and often months BEFORE, the old one ends (e.g. Earth Fare, authorized 252 days before the old record ended),
    #    which a same-address-key window of -30/+90 days could not see.
    best = find_successors(spells)
    spells = spells.merge(best, on="spell_id", how="left")
    spells["successor_is_grocery"] = spells["successor_store_type"].isin(GROCERY_TYPES).where(spells["successor_spell_id"].notna())
    spells["ownership_change"] = spells["successor_spell_id"].notna()
    spells["true_exit"] = spells["spell_end"].notna() & ~spells["ownership_change"]
    # exit_is_batch: only defined for true exits; nullable so non-exits are missing, not False.
    spells["exit_is_batch"] = spells["qa_batch_end"].astype("boolean").where(spells["true_exit"])

    scope = spells["spell_end"].notna() & (spells["spell_end"] <= CUTOFF)
    n_ended, n_own = int(scope.sum()), int((scope & spells["ownership_change"]).sum())
    many = spells.loc[scope & spells["ownership_change"], "successor_spell_id"].value_counts()
    basis = spells.loc[scope & spells["ownership_change"], "successor_basis"].value_counts().to_dict()
    log_step(SCRIPT, "ownership_change",
             f"successor = different Record ID within {RADIUS_MI} mile that (a) has a similar name (>= {NAME_SIM}, store numbers removed) and was authorized "
             f"from {NAME_LOOKBACK_DAYS} days before to {AFTER_DAYS} days after the end, or (b) has the identical street address incl. unit and was authorized from "
             f"{ADDRESS_LOOKBACK_DAYS} days before to {AFTER_DAYS} days after; spells ended through {DATA_THROUGH}: basis name={basis.get('name', 0)}, "
             f"address={basis.get('address', 0)}, both={basis.get('both', 0)}; {int((many > 1).sum())} successors are claimed by more than one predecessor",
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
        "successor_basis", "successor_name_sim", "successor_distance_mi",
        "successor_is_grocery", "ownership_change", "true_exit", "qa_batch_end", "exit_is_batch",
        "qa_reentered_later", "qa_reentry_gap_days",
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
