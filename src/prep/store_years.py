"""Store-year membership and labels, built from the 03_spells outputs.

Shared by 04_panel.py and the EDA label-rate script so both use one definition.

Observation: a grocery-type Record ID whose spell is active on Jan 1 of year t.
  * active on Jan 1 t = spell_start <= Jan 1 t (or start unknown: placeholder 1/1/1930 means
    "authorized before the data window") and spell_end >= Jan 1 t (or still open). A spell that
    ends exactly on Jan 1 t counts as active, matching exit_12m's window [Jan 1 t, Dec 31 t].
  * store_type is the type of the period in force on Jan 1 t (the latest period that started on
    or before Jan 1 t), not the spell's first or last type.

Labels (all about the 12 months of year t):
  * exit_12m         1 if the spell ends in t and the end is a true exit (not an ownership change),
                     batch ends included. Primary label.
  * exit_12m_strict  same, but a batch-end exit makes the label MISSING (the row is excluded from
                     strict analyses) instead of 0, because those stores did lose authorization.
  * exit_is_batch    for exits only: whether the end was a qa_batch_end; missing otherwise.
Columns prefixed qa_ describe the outcome or data quality and are never model features.
"""

import pandas as pd

from common import GROCERY_TYPES

EARLIEST = pd.Timestamp("1900-01-01")


def build_store_years(spells: pd.DataFrame, periods: pd.DataFrame, years) -> pd.DataFrame:
    # Only what membership and labels need from the spell; name/location come from the period in force.
    spells = spells[["spell_id", "record_id", "spell_start", "spell_end", "true_exit", "ownership_change", "qa_batch_end",
                     "qa_reentered_later", "qa_reentry_gap_days"]]
    attrs = ["store_name", "name_std", "address_key", "zip5", "county", "latitude", "longitude"]
    per = periods[["spell_id", "auth_date", "store_type", *attrs]].copy()
    per["key"] = per["auth_date"].fillna(EARLIEST).astype("datetime64[us]")
    per = per.sort_values("key").drop(columns="auth_date").rename(columns={"store_type": "store_type_jan1"})

    frames = []
    for y in years:
        j1 = pd.Timestamp(y, 1, 1)
        started = spells["spell_start"].isna() | (spells["spell_start"] <= j1)
        not_ended = spells["spell_end"].isna() | (spells["spell_end"] >= j1)
        a = spells[started & not_ended].copy()
        a["year"] = y
        a["jan1"] = j1
        frames.append(a)
    sy = pd.concat(frames, ignore_index=True)
    sy["jan1"] = sy["jan1"].astype("datetime64[us]")
    sy = pd.merge_asof(sy.sort_values("jan1"), per, left_on="jan1", right_on="key", by="spell_id", direction="backward")
    sy = sy[sy["store_type_jan1"].isin(GROCERY_TYPES)].copy()

    ends_in_year = sy["spell_end"].dt.year == sy["year"]
    exit_in_year = ends_in_year & sy["true_exit"]
    batch = sy["qa_batch_end"].astype(bool)
    out = pd.DataFrame({
        "record_id": sy["record_id"],
        "spell_id": sy["spell_id"],
        "year": sy["year"],
        "store_type": sy["store_type_jan1"],
        **{c: sy[c] for c in attrs},
        "qa_coord_invalid": sy["latitude"].isna() | sy["longitude"].isna(),  # 02 blanked invalid coordinates
        "exit_12m": exit_in_year.astype("int8"),
        "exit_12m_strict": exit_in_year.astype("Int8").mask(exit_in_year & batch),
        "exit_is_batch": batch.astype("boolean").where(exit_in_year),
        "qa_ownership_change_in_year": ends_in_year & sy["ownership_change"],
        "qa_spell_end": sy["spell_end"],
        # exits only: the same Record ID is authorized again in a later spell (uses events after the exit; never a feature)
        "qa_reentered_later": sy["qa_reentered_later"].astype("boolean").where(exit_in_year),
        "qa_reentry_gap_days": sy["qa_reentry_gap_days"].astype("Int64").where(exit_in_year),
    }).sort_values(["year", "record_id"]).reset_index(drop=True)
    if out.duplicated(["record_id", "year"]).any():
        raise ValueError("A Record ID has two active spells on the same Jan 1")
    return out
