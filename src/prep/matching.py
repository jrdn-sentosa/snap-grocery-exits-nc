"""Shared constants and helpers for the ownership-change (successor) rule used by 03_spells.py and the EDA reviews.

A different Record ID is a SUCCESSOR of an ended spell (revision 3) if
  (a) it lies within RADIUS_MI of it, the cleaned store names match (similarity >= NAME_SIM, OR one name contains the other, OR token-set
      similarity >= TOKEN_SET_SIM; store numbers already removed in name_std) and it was authorized from NAME_LOOKBACK_DAYS before to
      AFTER_DAYS after the end; or
  (b) it has the identical standardized street address (address_core and ZIP; a unit listed on only one side counts as a match,
      two different units do not) and it was authorized from ADDRESS_LOOKBACK_DAYS before to AFTER_DAYS after the end, at ANY
      distance (a far geocode for an identical address is a geocoding error) and even without coordinates; or
  (c) "the same store": a STRONG name match (containment, token-set >= TOKEN_SET_SIM or similarity >= STRONG_SIM) within SAME_STORE_RADIUS_MI
      or at the identical address, authorized any time up to AFTER_DAYS after the end however long the two records overlapped, provided it is
      still authorized after the end. The co-tenant exclusion of (a) and (b) (nothing authorized long before the end counts) therefore
      applies only when the names do not match strongly.
Record pairs in data/reference/successor_overrides.csv are never successors (reviewed by hand; each is logged by 03).
"""

from difflib import SequenceMatcher
from pathlib import Path

NAME_SIM = 0.80              # "similar name": ratio of the cleaned names (threshold used in the exit-proximity review)
RADIUS_MI = 0.15             # rule (a): successor must be this close
NAME_LOOKBACK_DAYS = 365     # rule (a): authorized up to a year before the end ...
ADDRESS_LOOKBACK_DAYS = 30   # rule (b): ... or 30 days before for an identical address
AFTER_DAYS = 90              # both: up to 90 days after the end
GENERIC_NAME_WORDS = {"FOOD", "FOODS", "MARKET", "MARKETS", "STORE", "STORES", "GROCERY", "GROCERIES", "SUPERMARKET", "SUPER", "MART",
                      "SHOP", "DELI", "MINI", "THE", "OF", "AND", "INC", "LLC", "CORP", "CO", "CENTER", "SUPERCENTER"}
MERGE_GAP_DAYS = 90          # same-Record-ID periods this close (or overlapping) are one spell

# --- revision 3: name containment / token-set match and the "same store" tier (rule (c)) ------------------------------------------
TOKEN_SET_SIM = 0.90         # names also match when their token-set similarity is at least this ...
STRONG_SIM = 0.90            # ... a "strong" name match: containment, token-set >= 0.90 or plain similarity >= 0.90
SAME_STORE_RADIUS_MI = 0.05  # strong name match this close (or the identical address) = the same store, however long the records overlapped
MIN_CONTAINED_CHARS = 3      # a contained name must have at least this many characters ("BP" inside "BP FOOD MART" proves nothing)


def ownership_rule_text() -> str:
    """The rule in words, written to Supabase (data_meta) so the dashboard shows it without hard-coding numbers."""
    return (f"An end is treated as an ownership change or re-registration, not an exit, if a different Record ID either (a) lies within {RADIUS_MI} mile, has a matching "
            f"store name (similar spelling, or one name contains the other) and was authorized from {NAME_LOOKBACK_DAYS} days before to {AFTER_DAYS} days after the end, "
            f"or (b) has the identical street address (a unit listed on only one side counts as a match) and was authorized from {ADDRESS_LOOKBACK_DAYS} days before to "
            f"{AFTER_DAYS} days after the end, or (c) is the same store registered twice: a strongly matching name within {SAME_STORE_RADIUS_MI} mile or at the identical "
            f"address, still authorized after the end, however long the two records overlapped. A short list of pairs reviewed by hand is excluded. "
            f"Periods of one Record ID {MERGE_GAP_DAYS} days apart or less count as one continuous authorization.")


OVERRIDES_CSV = Path(__file__).resolve().parents[2] / "data" / "reference" / "successor_overrides.csv"


def load_overrides():
    """(table, set of frozenset({record_id, successor_record_id})) of the hand-reviewed pairs that are NOT successors (either direction)."""
    import pandas as pd

    t = pd.read_csv(OVERRIDES_CSV, dtype={"record_id": "int64", "successor_record_id": "int64"})
    assert t["reason"].notna().all() and (t["reason"].str.strip() != "").all(), "every override needs a reason"
    return t, {frozenset((int(a), int(b))) for a, b in zip(t["record_id"], t["successor_record_id"])}


def core_name(name: str | None) -> str:
    """Name without generic words, so 'A & B FOOD MARKET' and 'C FOOD MARKET' are not 'similar' because of FOOD MARKET."""
    toks = [t for t in (name or "").split() if t not in GENERIC_NAME_WORDS]
    return " ".join(toks) or (name or "")


def name_sim(a: str | None, b: str | None) -> float:
    ca, cb = core_name(a), core_name(b)
    if not ca or not cb:
        return 0.0
    return 1.0 if ca == cb else SequenceMatcher(None, ca, cb).ratio()


def _tokens(name: str | None) -> list[str]:
    return [t for t in (name or "").split() if t not in GENERIC_NAME_WORDS]


def name_contains(a: str | None, b: str | None) -> bool:
    """One cleaned name contains the other as whole words ('COMPARE' in 'COMPARE NORTH TRYON'), so 'chain' matches 'chain + location'.
    Generic words are ignored and the shorter name needs MIN_CONTAINED_CHARS characters, so 'FOOD MART' alone never matches anything."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return False
    short, long_ = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    if len(" ".join(short)) < MIN_CONTAINED_CHARS:
        return False
    return f" {' '.join(short)} " in f" {' '.join(long_)} "


def token_set_sim(a: str | None, b: str | None) -> float:
    """Token-set similarity of the cleaned names (word order and extra words matter little): 1.0 if every word of one name is in the other."""
    ta, tb = set(_tokens(a)), set(_tokens(b))
    inter = " ".join(sorted(ta & tb))
    if not inter:
        return 0.0
    s1 = f"{inter} {' '.join(sorted(ta - tb))}".strip()
    s2 = f"{inter} {' '.join(sorted(tb - ta))}".strip()
    r = lambda x, y: SequenceMatcher(None, x, y).ratio()  # noqa: E731
    return max(r(inter, s1), r(inter, s2), r(s1, s2))


def name_scores(a: str | None, b: str | None) -> tuple[float, bool, bool]:
    """(best similarity, names match, strong match) under the refined rule. Match = ratio >= NAME_SIM, or containment, or token-set >= TOKEN_SET_SIM;
    strong = containment, token-set >= TOKEN_SET_SIM or ratio >= STRONG_SIM."""
    ratio, contains, tset = name_sim(a, b), name_contains(a, b), token_set_sim(a, b)
    match = ratio >= NAME_SIM or contains or tset >= TOKEN_SET_SIM
    strong = contains or tset >= TOKEN_SET_SIM or ratio >= STRONG_SIM
    return max(ratio, tset, 1.0 if contains else 0.0), match, strong
