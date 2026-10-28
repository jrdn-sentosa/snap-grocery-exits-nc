"""Shared constants and helpers for the ownership-change (successor) rule used by 03_spells.py and the EDA reviews.

A different Record ID is a SUCCESSOR of an ended spell if it lies within RADIUS_MI of it AND either
  (a) its cleaned store name is similar (>= NAME_SIM, store numbers already removed in name_std)
      and it was authorized from NAME_LOOKBACK_DAYS before to AFTER_DAYS after the end; or
  (b) it has the identical standardized street address INCLUDING the unit (address_core + unit_std from 02_clean)
      and it was authorized from ADDRESS_LOOKBACK_DAYS before to AFTER_DAYS after the end.
No candidate authorized more than NAME_LOOKBACK_DAYS before the end is ever considered.
"""

from difflib import SequenceMatcher

NAME_SIM = 0.80              # "similar name": ratio of the cleaned names (threshold used in the exit-proximity review)
RADIUS_MI = 0.15             # successor must be this close
NAME_LOOKBACK_DAYS = 365     # rule (a): authorized up to a year before the end ...
ADDRESS_LOOKBACK_DAYS = 30   # rule (b): ... or 30 days before for an identical address
AFTER_DAYS = 90              # both: up to 90 days after the end
GENERIC_NAME_WORDS = {"FOOD", "FOODS", "MARKET", "MARKETS", "STORE", "STORES", "GROCERY", "GROCERIES", "SUPERMARKET", "SUPER", "MART",
                      "SHOP", "DELI", "MINI", "THE", "OF", "AND", "INC", "LLC", "CORP", "CO", "CENTER", "SUPERCENTER"}


def core_name(name: str | None) -> str:
    """Name without generic words, so 'A & B FOOD MARKET' and 'C FOOD MARKET' are not 'similar' because of FOOD MARKET."""
    toks = [t for t in (name or "").split() if t not in GENERIC_NAME_WORDS]
    return " ".join(toks) or (name or "")


def name_sim(a: str | None, b: str | None) -> float:
    ca, cb = core_name(a), core_name(b)
    if not ca or not cb:
        return 0.0
    return 1.0 if ca == cb else SequenceMatcher(None, ca, cb).ratio()
