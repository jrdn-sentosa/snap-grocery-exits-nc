"""What revision 3 of the ownership-change (successor) rule changed: counts under three rules and every grocery end it reclassified.

Reads : data/interim/retailers_nc_clean.parquet, periods_spells.parquet, spells.parquet, panel_trainval.parquet (train + validation only),
        data/reference/successor_overrides.csv
Writes: docs/successor_revision3_changes.md, docs/successor_revision3_changes.csv

Three rules are re-run on the same spells (nothing is read back from labels except as a check):
  revision 2     name similarity >= 0.80 within 0.15 mi (365-day lookback) or the identical address (30-day lookback)   [find_successors(refined=False)]
  revision 3, no overrides   + name containment / token-set >= 0.90, + "same store" tier (strong name match within 0.05 mi or at the identical address, any overlap)
  revision 3 (applied)       + the hand-reviewed pairs in successor_overrides.csv are never successors
The applied rule must reproduce data/interim/spells.parquet and the panel's exit_12m (both asserted).

Test-set discipline (hard rule 1): only spells that ended through 2021-12-31 and the train/validation panel are summarized or listed. A successor's start
after 2021-12-31 is shown as "after cut-off"; no successor end date is shown. (The successor search itself, like 03, looks at all records; a successor can
start up to 90 days after an end, as disclosed in docs/test_reservation_log.md.)
"""

import importlib.util
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "prep"))
from common import DATA_THROUGH, DOCS, GROCERY_TYPES, INTERIM, TRAIN_END_YEAR  # noqa: E402
from matching import (ADDRESS_LOOKBACK_DAYS, GENERIC_NAME_WORDS, NAME_LOOKBACK_DAYS, NAME_SIM, SAME_STORE_RADIUS_MI, load_overrides, name_contains,  # noqa: E402
                      name_sim, token_set_sim)

CUTOFF = pd.Timestamp(DATA_THROUGH)
spec = importlib.util.spec_from_file_location("spells03", ROOT / "src" / "prep" / "03_spells.py")
s03 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(s03)
D = "impact_dist_nearest_other_grocery_mi"


def md(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    return "\n".join(["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
                     + ["| " + " | ".join("" if pd.isna(v) else str(v) for v in r) + " |" for r in df.itertuples(index=False)])


def spell_inputs() -> pd.DataFrame:
    """The frame 03 hands to find_successors, rebuilt from the interim files (no 03 side effects such as cleaning-log rows)."""
    per = pd.read_parquet(INTERIM / "retailers_nc_clean.parquet").merge(
        pd.read_parquet(INTERIM / "periods_spells.parquet")[["record_id", "period_seq", "spell_id"]], on=["record_id", "period_seq"])
    per = per.sort_values(["record_id", "period_seq"])
    first, last = per.drop_duplicates("spell_id", keep="first").set_index("spell_id"), per.drop_duplicates("spell_id", keep="last").set_index("spell_id")
    sp = pd.read_parquet(INTERIM / "spells.parquet").set_index("spell_id")
    return pd.DataFrame({
        "record_id": sp["record_id"], "spell_start": sp["spell_start"], "spell_end": sp["spell_end"], "store_type_first": sp["store_type_first"],
        "store_type_last": sp["store_type_last"], "store_name": sp["store_name"], "name_std": sp["name_std"], "zip5": sp["zip5"], "county": sp["county"],
        "latitude": sp["latitude"], "longitude": sp["longitude"], "qa_batch_end": sp["qa_batch_end"],
        "address_core_last": last["address_core"], "unit_last": last["unit_std"], "name_std_first": first["name_std"],
        "address_core_first": first["address_core"], "unit_first": first["unit_std"], "zip5_first": first["zip5"],
        "latitude_first": first["latitude"], "longitude_first": first["longitude"], "store_name_first": first["store_name"],
    }).reset_index()


def main() -> None:
    sp_in = spell_inputs()
    ov_table, ov_pairs = load_overrides()
    r2 = s03.find_successors(sp_in, refined=False).set_index("spell_id")
    r3_raw = s03.find_successors(sp_in, refined=True).set_index("spell_id")
    r3 = s03.find_successors(sp_in, refined=True, overrides=ov_pairs).set_index("spell_id")
    spells = pd.read_parquet(INTERIM / "spells.parquet").set_index("spell_id")
    assert set(r3.index) == set(spells.index[spells["ownership_change"]]), "the applied rule does not reproduce spells.parquet"
    sp = sp_in.set_index("spell_id")
    scope = sp["spell_end"].notna() & (sp["spell_end"] <= CUTOFF) & sp["store_type_last"].isin(GROCERY_TYPES)

    panel = pd.read_parquet(INTERIM / "panel_trainval.parquet")
    ended = panel[panel["qa_spell_end"].notna() & (panel["qa_spell_end"].dt.year == panel["year"])]       # store-years whose spell ended that year
    batch = sp["qa_batch_end"].astype(bool)
    assert int((~ended["spell_id"].isin(r3.index)).sum()) == int(panel["exit_12m"].sum()), "the applied rule does not reproduce exit_12m"

    def counts(rule: pd.DataFrame, label: str) -> dict:
        ex = ended[~ended["spell_id"].isin(rule.index)]
        b = ex["spell_id"].map(batch).astype(bool)
        tr, va = ex["split"] == "train", ex["split"] == "validation"
        return {"": label, "exit_12m exits": len(ex), "train": int(tr.sum()), "validation": int(va.sum()),
                "2012-2018 train": int((tr & (ex["year"] > 2011)).sum()), "strict exits": int((~b).sum()), "batch exits": int(b.sum()),
                "exit rate train / validation": f"{100 * tr.sum() / (panel['split'] == 'train').sum():.2f}% / {100 * va.sum() / (panel['split'] == 'validation').sum():.2f}%",
                "ownership-change spells (grocery, ended through 2021)": int((scope & sp.index.isin(rule.index)).sum())}

    table = pd.DataFrame([counts(r2, "Revision 2"), counts(r3_raw, "Revision 3 without the overrides"), counts(r3, "Revision 3 (applied)")])
    exits = panel[panel["exit_12m"] == 1]
    sw, mk = exits[D].dropna(), exits[exits["county"] == "MECKLENBURG"][D].dropna()
    far = f"statewide {int((sw > 1).sum())} of {len(sw)} ({100 * (sw > 1).mean():.1f}%); Mecklenburg {int((mk > 1).sum())} of {len(mk)} ({100 * (mk > 1).mean():.1f}%)"
    print(table.T.to_string(header=False))
    print("exits with no other grocery within 1 mile, revision 3 applied:", far)

    gone_vs_r2 = [s for s in r2.index if s in sp.index and scope[s] and s not in r3.index]
    assert not gone_vs_r2, "a revision 2 successor was lost"
    reclass = pd.Index([s for s in r3.index if s in sp.index and scope[s] and s not in r2.index])
    exit_ids = set(exits["spell_id"])  # exits under the applied rule; reclassified ones are no longer exits, so use revision 2's exit rows instead
    r2_exit_ids = set(ended.loc[~ended["spell_id"].isin(r2.index), "spell_id"])

    def listing(ids: pd.Index, rule: pd.DataFrame, rule_name: str) -> pd.DataFrame:
        rows = []
        for sid in ids:
            e, nw = sp.loc[sid], rule.loc[sid]
            c = sp.loc[nw["successor_spell_id"]]
            u1 = e["unit_last"] if isinstance(e["unit_last"], str) and e["unit_last"] else None
            u2 = c["unit_first"] if isinstance(c["unit_first"], str) and c["unit_first"] else None
            same_addr = (isinstance(e["address_core_last"], str) and c["address_core_first"] == e["address_core_last"] and c["zip5_first"] == e["zip5"]
                         and (u1 is None or u2 is None or u1 == u2))
            gap, d = int(nw["successor_gap_days"]), float(nw["successor_distance_mi"])
            ratio, tset, cont = name_sim(e["name_std"], c["name_std_first"]), token_set_sim(e["name_std"], c["name_std_first"]), name_contains(e["name_std"], c["name_std_first"])
            why = []
            if ratio < NAME_SIM:
                why.append(f"name similarity {ratio:.2f} < {NAME_SIM}")
            if gap < -NAME_LOOKBACK_DAYS:
                why.append(f"authorized {-gap} days before the end (> {NAME_LOOKBACK_DAYS})")
            if same_addr and gap < -ADDRESS_LOOKBACK_DAYS and not why:
                why.append(f"identical address but {-gap} days before the end (> {ADDRESS_LOOKBACK_DAYS})")
            shared = (set(e["name_std"].split()) & set(c["name_std_first"].split())) - GENERIC_NAME_WORDS
            rows.append({
                "rule": rule_name, "record_id": int(e["record_id"]), "store": e["store_name"], "county": str(e["county"]).title(), "type": e["store_type_last"],
                "ended": f"{e['spell_end']:%Y-%m-%d}", "batch end": bool(e["qa_batch_end"]), "store-year exit under revision 2": bool(sid in r2_exit_ids),
                "successor id": int(nw["successor_record_id"]), "successor": c["store_name_first"], "successor type": nw["successor_store_type"],
                "type change": bool(nw["successor_store_type"] != e["store_type_last"]),
                "successor authorized": f"{c['spell_start']:%Y-%m-%d}" if c["spell_start"] <= CUTOFF else "after cut-off",
                "days from end": gap, "miles": round(d, 3), "same address": same_addr, "similarity": round(ratio, 2), "token-set": round(tset, 2), "contains": cont,
                "basis": nw["successor_basis"], "why revision 2 missed it": "; ".join(why) or "outside the old window",
                "read twice": ("successor is not a grocery type; " if nw["successor_store_type"] not in GROCERY_TYPES else "") + ("one shared word only; " if len(shared) == 1 and not same_addr else "")})
        return pd.DataFrame(rows).sort_values(["county", "ended", "store"])

    L = listing(reclass, r3, "applied")
    blocked_ids = pd.Index([s for s in r3_raw.index if s in sp.index and scope[s] and s not in r2.index and s not in r3.index])
    L_blocked = listing(blocked_ids, r3_raw, "blocked by an override")
    pd.concat([L, L_blocked]).to_csv(DOCS / "successor_revision3_changes.csv", index=False)

    n_exit = int(L["store-year exit under revision 2"].sum())
    show = ["store", "county", "type", "ended", "batch end", "store-year exit under revision 2", "successor", "successor type", "type change", "successor authorized",
            "days from end", "miles", "same address", "similarity", "token-set", "contains", "basis", "why revision 2 missed it"]
    comp = L[L["store"].str.upper().str.contains("COMPARE")]
    change = pd.Series(r3["qa_successor_type_change"] if "qa_successor_type_change" in r3 else [], dtype="boolean")
    own_all = spells[spells["ownership_change"] & scope.reindex(spells.index, fill_value=False)]
    report = [
        "# Revision 3 of the ownership-change rule: what changed", "",
        f"Generated by `src/eda/successor_revision3.py`; train and validation years only (spells ended through {DATA_THROUGH}). Rule definitions: `docs/label_rule_change.md`. "
        "The applied rule is asserted to reproduce `spells.parquet` and the panel's `exit_12m`.", "",
        "## Counts under the three rules (train + validation)", "", md(table), "",
        f"Revision 3 (applied): exits with no other SNAP grocery within 1 mile: {far}.", "",
        f"## Grocery ends reclassified from exit to ownership change, revision 2 to revision 3 ({len(L)} spells, {n_exit} of them `exit_12m` exits)", "",
        md(L[show]), "",
        f"## Matched by the rule but blocked by `data/reference/successor_overrides.csv` ({len(L_blocked)} spells)", "",
        md(L_blocked[show]) if len(L_blocked) else "None.", "",
        "### The override file", "", md(ov_table[["record_id", "store_name", "successor_record_id", "successor_name", "reason"]]), "",
        "## Example: Compare Foods", "",
        "Record 824411 `COMPARE FOODS` (4316 N TRYON ST, authorized 2007-06-14, ended 2021-06-16) and record 1392295 `Compare Foods North Tryon` (the same address, authorized "
        "2020-03-12, still authorized at the cut-off) are 0.011 mile apart. Revision 2 missed the pair: the cleaned names are `COMPARE` and `COMPARE NORTH TRYON` (similarity 0.54 < 0.80) "
        "and the successor was authorized 461 days before the end, outside both lookback windows, so the old record looked like a co-tenant. Revision 3 matches them: one name contains the "
        f"other, token-set 1.00, {SAME_STORE_RADIUS_MI} mile or less, and the other record is still authorized after the end. "
        + ("Found in the table above." if len(comp) else ""), "",
        f"## Ownership changes whose successor is a different store type (`qa_successor_type_change`)", "",
        f"Of the {len(own_all)} grocery spells that ended through {DATA_THROUGH} as ownership changes, "
        f"{int(own_all['qa_successor_type_change'].fillna(False).sum())} have a successor of a different store type; "
        f"{int((~own_all['successor_store_type'].isin(GROCERY_TYPES)).sum())} of them have a non-grocery successor (a grocery that became, for example, a convenience store). "
        "QA only, never a feature.", "",
        "Columns: *days from end* = successor start minus end (negative = authorized before the end); *miles* = distance between the two stores; *same address* = identical standardized "
        "street address and a compatible unit; *similarity* = revision 2's cleaned-name similarity; *token-set* and *contains* = the new name tests; *basis* = which part of the rule matched. "
        "Dates after 2021-12-31 are not shown.", "",
    ]
    (DOCS / "successor_revision3_changes.md").write_text("\n".join(report), encoding="utf-8")
    print(f"wrote docs/successor_revision3_changes.md: {len(L)} reclassified ({n_exit} exits), {len(L_blocked)} blocked by overrides; applied rule reproduces spells and exit_12m")
    print(comp[["store", "successor", "ended", "days from end", "miles"]].to_string(index=False))


if __name__ == "__main__":
    main()
