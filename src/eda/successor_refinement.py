"""Preview of the proposed refinement of the ownership-change (successor) rule. NOTHING is applied to the labels here.

Reads : data/interim/retailers_nc_clean.parquet, periods_spells.parquet, spells.parquet, panel_trainval.parquet (train + validation only)
Writes: docs/successor_refinement_preview.md, docs/successor_refinement_reclassified.csv

The proposal (matching.py, find_successors(refined=True) in 03_spells.py):
  1. Name match: also when one cleaned name contains the other (whole words, generic words ignored) or the token-set similarity >= 0.90,
     so "chain name" matches "chain name + location".
  2. Co-tenant exclusion (nothing authorized more than 365 days before the end counts) applies only when the names do not match strongly:
     a strong name match (containment, token-set >= 0.90 or similarity >= 0.90) within 0.05 mile, or at the identical address, is the same
     store (a duplicate or re-registration) however long the two records overlapped, provided the other record is still authorized after the end.
Sensitivity: the exclusion lifted for ANY name match within 0.15 mile.

Test-set discipline (hard rule 1): only spells that ended through 2021-12-31 and the train/validation panel are summarized or listed. A successor's
start date after 2021-12-31 is shown as "after cut-off" and no end date of a successor is ever shown. (The successor search itself, like 03, looks at
all records; a successor can start up to 90 days after an end, as already disclosed in docs/test_reservation_log.md.)
"""

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "prep"))
from common import DATA_THROUGH, DOCS, GROCERY_TYPES, INTERIM, TRAIN_END_YEAR  # noqa: E402
from matching import (ADDRESS_LOOKBACK_DAYS, NAME_LOOKBACK_DAYS, NAME_SIM, RADIUS_MI, SAME_STORE_RADIUS_MI, name_contains, name_sim,  # noqa: E402
                      token_set_sim)

CUTOFF = pd.Timestamp(DATA_THROUGH)
spec = importlib.util.spec_from_file_location("spells03", ROOT / "src" / "prep" / "03_spells.py")
s03 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(s03)
D = "impact_dist_nearest_other_grocery_mi"
GENERIC = {"FOOD", "FOODS", "MARKET", "MARKETS", "STORE", "STORES", "GROCERY", "GROCERIES", "SUPERMARKET", "SUPER", "MART", "SHOP", "DELI", "MINI", "THE", "OF", "AND", "INC", "LLC", "CORP", "CO", "CENTER", "SUPERCENTER"}


def md(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    return "\n".join(["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
                     + ["| " + " | ".join("" if pd.isna(v) else str(v) for v in r) + " |" for r in df.itertuples(index=False)])


def spell_inputs() -> pd.DataFrame:
    """The frame 03 hands to find_successors (rebuilt from the interim files, so no 03 side effects such as cleaning-log rows)."""
    per = pd.read_parquet(INTERIM / "retailers_nc_clean.parquet").merge(
        pd.read_parquet(INTERIM / "periods_spells.parquet")[["record_id", "period_seq", "spell_id"]], on=["record_id", "period_seq"])
    per = per.sort_values(["record_id", "period_seq"])
    first, last = per.drop_duplicates("spell_id", keep="first").set_index("spell_id"), per.drop_duplicates("spell_id", keep="last").set_index("spell_id")
    sp = pd.read_parquet(INTERIM / "spells.parquet").set_index("spell_id")
    out = pd.DataFrame({
        "record_id": sp["record_id"], "spell_start": sp["spell_start"], "spell_end": sp["spell_end"], "store_type_first": sp["store_type_first"],
        "store_type_last": sp["store_type_last"], "store_name": sp["store_name"], "name_std": sp["name_std"], "zip5": sp["zip5"], "county": sp["county"],
        "latitude": sp["latitude"], "longitude": sp["longitude"], "qa_batch_end": sp["qa_batch_end"],
        "address_core_last": last["address_core"], "unit_last": last["unit_std"], "name_std_first": first["name_std"],
        "address_core_first": first["address_core"], "unit_first": first["unit_std"], "zip5_first": first["zip5"],
        "latitude_first": first["latitude"], "longitude_first": first["longitude"],
        "store_name_first": first["store_name"],
    }).reset_index()
    return out


def main() -> None:
    sp_in = spell_inputs()
    cur_file = pd.read_parquet(INTERIM / "spells.parquet").set_index("spell_id")
    cur = s03.find_successors(sp_in).set_index("spell_id")
    # regression: the default (refined=False) must reproduce the pipeline's own successors exactly
    same = cur["successor_spell_id"].reindex(cur_file.index).fillna("").equals(cur_file["successor_spell_id"].fillna("").astype(str))
    ref = s03.find_successors(sp_in, refined=True).set_index("spell_id")
    lift = s03.find_successors(sp_in, refined=True, lift_for_any_name_match=True).set_index("spell_id")
    print(f"default rule reproduces spells.parquet: {same}; successors current {len(cur):,}, refined {len(ref):,}, lifted-for-any-name-match {len(lift):,}")

    sp = sp_in.set_index("spell_id")
    scope = sp["spell_end"].notna() & (sp["spell_end"] <= CUTOFF) & sp["store_type_last"].isin(GROCERY_TYPES)
    panel = pd.read_parquet(INTERIM / "panel_trainval.parquet")
    exit_rows = panel[panel["exit_12m"] == 1]

    def reclassified(new: pd.DataFrame) -> pd.Index:
        return pd.Index([s for s in new.index if s in sp.index and scope[s] and s not in cur.index])

    r_main, r_lift = reclassified(ref), reclassified(lift)
    r_extra = r_lift.difference(r_main)
    print(f"grocery spells ended through {DATA_THROUGH} newly classed as ownership changes: refined {len(r_main)}, lifted-for-any-name-match {len(r_lift)} (+{len(r_extra)})")

    def counts(ids: pd.Index, label: str) -> dict:
        gone = exit_rows[exit_rows["spell_id"].isin(ids)]
        left = exit_rows[~exit_rows["spell_id"].isin(ids)]
        st = panel[(panel["exit_12m_strict"] == 1)]
        st_left = st[~st["spell_id"].isin(ids)]
        mk = left[left["county"] == "MECKLENBURG"][D].dropna()
        sw = left[D].dropna()
        acs = left[(left["year"] > 2011) & (left["year"] <= TRAIN_END_YEAR)]
        return {"": label, "exit_12m exits": len(left), "train": int((left["split"] == "train").sum()), "validation": int((left["split"] == "validation").sum()),
                "2012-2018 train": len(acs), "strict exits": len(st_left), "batch exits": int((left["exit_is_batch"] == True).sum()),  # noqa: E712
                "exits reclassified": len(gone), ">1 mi statewide": f"{int((sw > 1).sum())} of {len(sw)} ({100 * (sw > 1).mean():.1f}%)",
                ">1 mi Mecklenburg": f"{int((mk > 1).sum())} of {len(mk)} ({100 * (mk > 1).mean():.1f}%)",
                "exit rate train / validation": f"{100 * (left['split'] == 'train').sum() / (panel['split'] == 'train').sum():.2f}% / {100 * (left['split'] == 'validation').sum() / (panel['split'] == 'validation').sum():.2f}%"}

    table = pd.DataFrame([counts(pd.Index([]), "Current rule"), counts(r_main, "Refined rule (proposed)"), counts(r_lift, "Sensitivity: exclusion lifted for any name match <= 0.15 mi")])
    print(table.T.to_string(header=False))

    # ---- the list: every grocery spell the refinement reclassifies, with why the current rule missed it
    cand = sp_in.set_index("spell_id")

    def listing(ids: pd.Index, new: pd.DataFrame, kind: str) -> pd.DataFrame:
        rows = []
        for sid in ids:
            e, nw = sp.loc[sid], new.loc[sid]
            c = cand.loc[nw["successor_spell_id"]]
            u1, u2 = (e["unit_last"] if isinstance(e["unit_last"], str) and e["unit_last"] else None), (c["unit_first"] if isinstance(c["unit_first"], str) and c["unit_first"] else None)
            same_addr = (isinstance(e["address_core_last"], str) and c["address_core_first"] == e["address_core_last"] and c["zip5_first"] == e["zip5"]
                         and (u1 is None or u2 is None or u1 == u2))
            gap, d = int(nw["successor_gap_days"]), float(nw["successor_distance_mi"])
            ratio, tset, cont = name_sim(e["name_std"], c["name_std_first"]), token_set_sim(e["name_std"], c["name_std_first"]), name_contains(e["name_std"], c["name_std_first"])
            why = []
            if ratio < NAME_SIM:
                why.append(f"name similarity {ratio:.2f} < {NAME_SIM}")
            if gap < -NAME_LOOKBACK_DAYS:
                why.append(f"authorized {-gap} days before the end (> {NAME_LOOKBACK_DAYS})")
            if not (ratio < NAME_SIM or gap < -NAME_LOOKBACK_DAYS):
                why.append("outside the old window")
            if same_addr and gap < -ADDRESS_LOOKBACK_DAYS:
                why.append(f"identical address but {-gap} days before the end (> {ADDRESS_LOOKBACK_DAYS})")
            rows.append({
                "kind": kind, "record_id": int(e["record_id"]), "store": e["store_name"], "county": str(e["county"]).title(), "type": e["store_type_last"],
                "ended": f"{e['spell_end']:%Y-%m-%d}", "batch end": bool(e["qa_batch_end"]),
                "store-year exit": bool(sid in set(exit_rows["spell_id"])),
                "successor id": int(nw["successor_record_id"]), "successor": c["store_name_first"], "successor type": nw["successor_store_type"],
                "successor authorized": (f"{sp.loc[nw['successor_spell_id'], 'spell_start']:%Y-%m-%d}" if sp.loc[nw["successor_spell_id"], "spell_start"] <= CUTOFF else "after cut-off"),
                "days from end": gap, "miles": round(d, 3), "same address": same_addr, "similarity": round(ratio, 2), "token-set": round(tset, 2), "contains": cont,
                "why the current rule missed it": "; ".join(why),
                "read twice": ("successor is not a grocery type; " if nw["successor_store_type"] not in GROCERY_TYPES else "")
                              + ("one shared word only; " if len(set(e["name_std"].split()) & set(c["name_std_first"].split()) - GENERIC) == 1 and ratio < 0.8 and not same_addr else "")})
        return pd.DataFrame(rows).sort_values(["county", "ended", "store"])

    L_main, L_extra = listing(r_main, ref, "refined rule"), listing(r_extra, lift, "only if lifted for any name match")
    pd.concat([L_main, L_extra]).to_csv(DOCS / "successor_refinement_reclassified.csv", index=False)
    in_scope_exit = L_main["store-year exit"].sum()
    comp = L_main[L_main["store"].str.upper().str.contains("COMPARE")]
    why_counts = pd.Series(["name" if "name similarity" in w else "" for w in L_main["why the current rule missed it"]]).value_counts()
    n_name = int(L_main["why the current rule missed it"].str.contains("name similarity").sum())
    n_time = int(L_main["why the current rule missed it"].str.contains("days before the end").sum())
    n_both = int((L_main["why the current rule missed it"].str.contains("name similarity") & L_main["why the current rule missed it"].str.contains("days before the end")).sum())
    kind_mix = L_main["successor type"].value_counts().to_dict()

    show_cols = ["store", "county", "type", "ended", "batch end", "store-year exit", "successor", "successor type", "successor authorized", "days from end", "miles", "same address",
                 "similarity", "token-set", "contains", "why the current rule missed it", "read twice"]
    report = [
        "# Preview: refining the ownership-change rule (NOT applied)", "",
        f"Generated by `src/eda/successor_refinement.py`; train and validation years only (spells ended through {DATA_THROUGH}). The labels, `spells.parquet` and Supabase are unchanged: "
        "this is the evidence for a decision. `03_spells.py --refined` does not exist yet; the proposal lives in `find_successors(refined=True)` and the default still reproduces "
        f"the current spells exactly ({'verified' if same else 'NOT VERIFIED'}).", "",
        "## Proposal",
        f"1. **Name match.** A similar name also means one cleaned name contains the other (whole words, generic words such as FOOD/MARKET ignored, at least 3 characters) or the "
        f"token-set similarity is at least 0.90, in addition to the current similarity of at least {NAME_SIM}. 'COMPARE FOODS' and 'COMPARE FOODS NORTH TRYON' then match.",
        f"2. **Co-tenant exclusion only when the names do not match.** Today nothing authorized more than {NAME_LOOKBACK_DAYS} days before the end counts. Now a *strong* name match "
        f"(containment, token-set >= 0.90 or similarity >= 0.90) within {SAME_STORE_RADIUS_MI} mile, or at the identical address, is the same store (a duplicate or re-registration) "
        "however long the two records overlapped. The other record must still be authorized after the end; a record that had already ended is an earlier record, not a successor. "
        "Everything else keeps the current windows.", "",
        "## Before and after (train + validation)", "", md(table), "",
        f"The refinement reclassifies **{len(r_main)} grocery spells** as ownership changes, of which **{int(in_scope_exit)}** are `exit_12m` exits in the store-year table "
        f"(the rest ended in the year they started, so they were never on a January 1). Why the current rule missed them: name {n_name - n_both}, timing {n_time - n_both}, both {n_both}, "
        f"neither {len(r_main) - n_name - n_time + n_both}. Successor store types: {kind_mix}.", "",
        f"The sensitivity (exclusion lifted for any name match within {RADIUS_MI} mile) would reclassify {len(r_extra)} more spells; they are listed separately below.", "",
        "## The Compare Foods pair", "",
        "Record 824411 'COMPARE FOODS' (4316 N TRYON ST, Super Store, authorized 2007-06-14, ended 2021-06-16, a batch-end day) and record 1392295 'Compare Foods North Tryon' "
        "(the same address, authorized 2020-03-12, still authorized at the cut-off) are 0.011 mile apart. The current rule misses the pair three ways: the cleaned names are "
        "'COMPARE' and 'COMPARE NORTH TRYON' (similarity 0.54 < 0.80), the successor was authorized 461 days before the end (outside the 365-day window of rule (a) and the 30-day "
        "window of rule (b)), so the old record looked like a co-tenant. Under the proposal the pair matches: containment, token-set 1.00, 0.011 mile, the other record still authorized. "
        + ("It is in the list below." if len(comp) else "(It is not in the list; see the check in the console output.)"), "",
        f"## Every exit-spell the refinement reclassifies ({len(L_main)})", "", md(L_main[show_cols]), "",
        f"## Additionally reclassified only if the exclusion is lifted for any name match within {RADIUS_MI} mile ({len(L_extra)})", "",
        md(L_extra[show_cols]) if len(L_extra) else "None.", "",
        "Columns: *store-year exit* = the spell is an `exit_12m` exit in the store-year table; *days from end* = successor start minus end (negative = authorized before the end); "
        "*miles* = distance between the two stores; *same address* = identical standardized street address and a compatible unit; *similarity* = current cleaned-name similarity; "
        "*token-set* and *contains* = the new name tests. Dates after 2021-12-31 are not shown.", "",
    ]
    (DOCS / "successor_refinement_preview.md").write_text("\n".join(report), encoding="utf-8")
    print(f"wrote docs/successor_refinement_preview.md ({len(L_main)} listed + {len(L_extra)} sensitivity)")
    print("Compare Foods in list:\n", comp[["store", "successor", "ended", "days from end", "miles", "why the current rule missed it"]].to_string(index=False))


if __name__ == "__main__":
    main()
