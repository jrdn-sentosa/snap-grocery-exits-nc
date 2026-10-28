"""03: turn authorization periods into spells and classify how each spell ended.

Reads : data/interim/retailers_nc_clean.parquet  (all NC retailers, one row per period)
Writes: data/interim/spells.parquet           one row per continuous spell per Record ID
        data/interim/periods_spells.parquet   every period with its spell_id (04 uses it to get
                                              the store type that was active on a given Jan 1)

Rules (all logged via common.log_step):
  * Same-Record-ID periods separated by <= 90 days (or overlapping) are ONE spell; a longer gap
    ends the spell and the later period starts a new one (exit, then re-entry).
  * Ownership change (revision 3): a DIFFERENT Record ID that is authorized (a) from 365 days before to 90 days after this spell's end,
    within 0.15 mile, with a matching store name (similar, or one contains the other; store numbers removed), or (b) from 30 days
    before to 90 days after with the identical standardized street address (same ZIP, a unit listed on only one side counts as a
    match) at ANY distance, or (c) a strong name match within 0.05 mile / at the identical address that is still authorized after the
    end, however long the two overlapped. The end is then NOT an exit. Pairs in data/reference/successor_overrides.csv are never
    successors (logged one by one). (Definitions and thresholds: matching.py; history in docs/label_rule_change.md.)
  * qa_successor_type_change: the successor's store type differs from the ended spell's (e.g. grocery -> convenience). Never a feature.
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
from matching import (ADDRESS_LOOKBACK_DAYS, AFTER_DAYS, MERGE_GAP_DAYS, NAME_LOOKBACK_DAYS, NAME_SIM, RADIUS_MI, SAME_STORE_RADIUS_MI, load_overrides,
                      name_scores, name_sim)

SCRIPT = "03_spells"
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


def find_successors(spells: pd.DataFrame, refined: bool = True, lift_for_any_name_match: bool = False, overrides: set | None = None) -> pd.DataFrame:
    """For every ended spell, the best successor under the ownership-change rule (see the module docstring), if any.

    Candidates are spells of OTHER Record IDs with a known start within [end - 365 days, end + 90 days]. Rule (a): within RADIUS_MI
    of the ended spell and name similarity >= NAME_SIM (any start in that window). Rule (b): identical address_core and ZIP, units
    compatible (equal, or listed on only one side), a start no earlier than 30 days before the end, any distance (the same street
    address with distant geocodes is a geocoding error) and no coordinates needed. Preference: address match, then name
    similarity, then the smallest |gap|, then Record ID.

    refined=True (revision 3, the pipeline rule; refined=False reproduces revision 2 for src/eda/successor_refinement.py): (1) "similar name" also
    means one cleaned name contains the other or the token-set similarity is >= 0.90 (matching.name_scores); (2) the 365-day
    co-tenant exclusion is lifted for a strong name match within SAME_STORE_RADIUS_MI (or the identical address): the candidate may
    have been authorized any time before the end, but must still be authorized after it (not ended before it), because otherwise it
    is an earlier, finished record and not a successor. lift_for_any_name_match=True (sensitivity only) lifts it for any name match
    within RADIUS_MI instead. overrides = {frozenset({record_id, successor_record_id})}: reviewed pairs that are never successors; a pair
    the rule would have accepted is recorded in the result's attrs["blocked"] so the caller can log it.
    """
    ended = spells[spells["spell_end"].notna()].reset_index(drop=True)
    cand = spells[spells["spell_start"].notna()].sort_values("spell_start").reset_index(drop=True)
    ex_x, ex_y = project(ended["latitude"], ended["longitude"])          # NaN where a store has no valid coordinates
    cd_x, cd_y = project(cand["latitude_first"], cand["longitude_first"])
    starts = cand["spell_start"].to_numpy()
    c_rec, c_name, c_core = cand["record_id"].to_numpy(), cand["name_std_first"].to_numpy(object), cand["address_core_first"].to_numpy(object)
    c_unit, c_id, c_type = cand["unit_first"].to_numpy(object), cand["spell_id"].to_numpy(object), cand["store_type_first"].to_numpy(object)
    c_zip = cand["zip5_first"].to_numpy(object)
    c_end = cand["spell_end"].to_numpy()                      # NaT = still authorized; only used as "authorized after this end?"
    by_addr_key: dict[tuple, list[int]] = {}      # (address_core, zip5) -> candidate rows: rule (b) needs no coordinates
    for j, (core, z) in enumerate(zip(c_core, c_zip)):
        if isinstance(core, str):
            by_addr_key.setdefault((core, z), []).append(j)
    out, blocked = [], []
    for i, e in enumerate(ended.itertuples()):
        end = np.datetime64(e.spell_end)
        a = np.searchsorted(starts, end - np.timedelta64(NAME_LOOKBACK_DAYS, "D"), "left")
        b = np.searchsorted(starts, end + np.timedelta64(AFTER_DAYS, "D"), "right")
        lo = 0 if refined else a      # refined: candidates authorized long before the end are looked at too (kept only if "the same store")
        if b <= lo:
            continue
        dist_all = np.hypot(cd_x[lo:b] - ex_x[i], cd_y[lo:b] - ex_y[i]) / M_PER_MI       # NaN comparisons are False: no name match without coordinates
        dist = dist_all[a - lo:]
        idxs = set((np.where(dist <= RADIUS_MI)[0] + a).tolist()) if b > a else set()
        if isinstance(e.address_core_last, str):
            idxs.update(j for j in by_addr_key.get((e.address_core_last, e.zip5), []) if a <= j < b)
        if refined:
            far = dist_all[:max(a - lo, 0)]
            idxs.update((np.where(far <= (RADIUS_MI if lift_for_any_name_match else SAME_STORE_RADIUS_MI))[0] + lo).tolist())
            if isinstance(e.address_core_last, str):
                idxs.update(j for j in by_addr_key.get((e.address_core_last, e.zip5), []) if lo <= j < a)
        for j in idxs:
            if c_rec[j] == e.record_id:
                continue
            gap = int((starts[j] - end) / np.timedelta64(1, "D"))
            u1, u2 = _unit(e.unit_last), _unit(c_unit[j])
            # (b) identical street address (same ZIP): any distance (a far geocode is a data error), and a unit listed on only one side is a match
            same_addr = isinstance(e.address_core_last, str) and c_core[j] == e.address_core_last and c_zip[j] == e.zip5 and (u1 is None or u2 is None or u1 == u2)
            by_addr = bool(same_addr and gap >= -ADDRESS_LOOKBACK_DAYS)
            d = float(dist_all[j - lo])
            if not refined:
                sim = name_sim(e.name_std, c_name[j])
                by_name = bool(d <= RADIUS_MI and sim >= NAME_SIM)
                same_store = False
            else:
                sim, names_ok, strong = name_scores(e.name_std, c_name[j])
                still_on = bool(pd.isna(c_end[j]) or c_end[j] > end)
                by_name = bool(d <= RADIUS_MI and names_ok and gap >= -NAME_LOOKBACK_DAYS)
                # the same store registered twice, or re-registered: a strong name match this close (or at the identical address), whatever the overlap
                near = (d <= (RADIUS_MI if lift_for_any_name_match else SAME_STORE_RADIUS_MI)) or same_addr
                same_store = bool((strong or (lift_for_any_name_match and names_ok)) and near and still_on and not (by_addr or by_name))
            if by_addr or by_name or same_store:
                basis_ = "same store" if same_store else "both" if by_addr and by_name else "address" if by_addr else "name"
                if overrides and frozenset((int(e.record_id), int(c_rec[j]))) in overrides:
                    blocked.append((e.spell_id, int(e.record_id), int(c_rec[j]), basis_))
                    continue
                out.append((e.spell_id, c_id[j], int(c_rec[j]), gap, c_type[j], basis_, sim, d, by_addr))
    cols = ["spell_id", "successor_spell_id", "successor_record_id", "successor_gap_days", "successor_store_type",
            "successor_basis", "successor_name_sim", "successor_distance_mi", "_addr"]
    m = pd.DataFrame(out, columns=cols)
    m["_abs"] = m["successor_gap_days"].abs()
    best = m.sort_values(["spell_id", "_addr", "successor_name_sim", "_abs", "successor_record_id"], ascending=[True, False, False, True, True])
    best = best.drop_duplicates("spell_id").drop(columns=["_addr", "_abs"])
    best.attrs["blocked"] = pd.DataFrame(blocked, columns=["spell_id", "record_id", "successor_record_id", "basis"])
    return best


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
        "name_std_first": first["name_std"], "address_core_first": first["address_core"], "unit_first": first["unit_std"], "zip5_first": first["zip5"],
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
    ov_table, ov_pairs = load_overrides()
    best = find_successors(spells, overrides=ov_pairs)
    blocked = best.attrs["blocked"]
    spells = spells.merge(best, on="spell_id", how="left")
    spells["successor_is_grocery"] = spells["successor_store_type"].isin(GROCERY_TYPES).where(spells["successor_spell_id"].notna())
    spells["ownership_change"] = spells["successor_spell_id"].notna()
    spells["true_exit"] = spells["spell_end"].notna() & ~spells["ownership_change"]
    # QA only (never a feature): the successor is a different store type than the ended spell (e.g. grocery -> convenience)
    spells["qa_successor_type_change"] = (spells["successor_store_type"] != spells["store_type_last"]).astype("boolean").where(spells["ownership_change"])
    # exit_is_batch: only defined for true exits; nullable so non-exits are missing, not False.
    spells["exit_is_batch"] = spells["qa_batch_end"].astype("boolean").where(spells["true_exit"])

    scope = spells["spell_end"].notna() & (spells["spell_end"] <= CUTOFF)
    n_ended, n_own = int(scope.sum()), int((scope & spells["ownership_change"]).sum())
    many = spells.loc[scope & spells["ownership_change"], "successor_spell_id"].value_counts()
    basis = spells.loc[scope & spells["ownership_change"], "successor_basis"].value_counts().to_dict()
    log_step(SCRIPT, "ownership_change",
             f"successor = different Record ID that (a) is within {RADIUS_MI} mile, has a matching name (similarity >= {NAME_SIM}, or one name contains the other, or token-set >= 0.90; "
             f"store numbers removed) and was authorized from {NAME_LOOKBACK_DAYS} days before to {AFTER_DAYS} days after the end, or (b) has the identical street address "
             f"(same ZIP; a unit listed on only one side counts as a match; any distance) and was authorized from {ADDRESS_LOOKBACK_DAYS} days before to {AFTER_DAYS} days after, "
             f"or (c) 'same store': a strong name match within {SAME_STORE_RADIUS_MI} mile or at the identical address, still authorized after the end, any overlap; "
             f"{len(ov_table)} reviewed pairs are never successors; spells ended through {DATA_THROUGH}: basis name={basis.get('name', 0)}, "
             f"address={basis.get('address', 0)}, both={basis.get('both', 0)}, same store={basis.get('same store', 0)}; {int((many > 1).sum())} successors are claimed by more than one predecessor "
             f"(at most {int(many.max())} each): two ended records taken over by the same later record, usually duplicate records of one store (spelling variants, or a store registered twice) "
             "that ended together, so each one is still an ownership change but together they are one store that was taken over, not two that left",
             "Ownership transfers are not loss of access; they must not count as exits",
             n_ended, n_ended - n_own, n_own)

    # hand-reviewed pairs that must not be successors (data/reference/successor_overrides.csv): one log line each
    for o in ov_table.itertuples():
        hit = blocked[((blocked["record_id"] == o.record_id) & (blocked["successor_record_id"] == o.successor_record_id))
                      | ((blocked["record_id"] == o.successor_record_id) & (blocked["successor_record_id"] == o.record_id))]
        now = spells[spells["spell_id"].isin(hit["spell_id"])]
        after = "; the end is now " + ", ".join(f"an ownership change to record {int(r.successor_record_id)}" if r.ownership_change else "an exit" for r in now.itertuples())
        log_step(SCRIPT, f"override_{o.record_id}_{o.successor_record_id}",
                 f"override: record {o.record_id} ({o.store_name}) and record {o.successor_record_id} ({o.successor_name}) are NOT successors (either direction); "
                 + (f"the rule would have matched them {len(hit)} time(s){after}" if len(hit) else "a stale override: the rule matches nothing here any more"),
                 str(o.reason), len(hit), 0, len(hit))
        if not len(hit):
            print(f"  WARNING: override {o.record_id} / {o.successor_record_id} blocks nothing (stale?)")
    own = scope & spells["ownership_change"]
    chg = int((own & spells["qa_successor_type_change"].fillna(False)).sum())
    to_non = int((own & spells["store_type_last"].isin(GROCERY_TYPES) & ~spells["successor_store_type"].isin(GROCERY_TYPES)).sum())
    log_step(SCRIPT, "successor_type_change",
             f"qa_successor_type_change = the successor's store type differs from the ended spell's; ownership changes ended through {DATA_THROUGH}: {chg} of {int(own.sum())} "
             f"(grocery -> non-grocery {to_non})",
             "A re-registration as a different kind of store (e.g. a grocery that became a convenience store) is worth a second look; QA only, never a feature",
             int(own.sum()), int(own.sum()), chg)

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
        "successor_is_grocery", "ownership_change", "true_exit", "qa_batch_end", "exit_is_batch", "qa_successor_type_change",
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
