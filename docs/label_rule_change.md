# Label rule changes: the ownership-change rule (2026-10-28)

A static record of how the ownership-change rule changed and what each change did to the labels. Train and validation numbers only.
Revision 1 introduced the combined rule; revision 2 loosened it after an audit of what revision 1 dropped; **revision 3 (current)** added
name containment, a "same store" tier and a hand-reviewed override list after the Compare Foods miss.

## Revision 3 (current, 2026-10-28)

### The miss that triggered it: Compare Foods, 4316 N Tryon St (Mecklenburg)
Record 824411 `COMPARE FOODS` (Super Store, authorized 2007-06-14, ended 2021-06-16, a batch-end day) was an `exit_12m` exit although record 1392295
`Compare Foods North Tryon` (the same address, 0.011 mile away, authorized 2020-03-12, still authorized at the data cut-off) is plainly the same store
re-registered. Revision 2 missed the pair on three counts: the cleaned names are `COMPARE` and `COMPARE NORTH TRYON` (similarity 0.54 < 0.80); the
successor was authorized 461 days before the end, outside the 365-day window of rule (a) and the 30-day window of rule (b); and so the old record looked
like a co-tenant of a store that was already there. Under revision 3 the pair matches (one name contains the other, token-set 1.00, 0.011 mile, the other
record still authorized after the end): the 2021 exit becomes an ownership change.

### The rule (`src/prep/03_spells.py`, thresholds and helpers in `src/prep/matching.py`)
A different Record ID is a **successor**, and the end an **ownership change** (not an exit), if any of
- **(a)** it is within **0.15 mile**, its name **matches** (cleaned-name similarity >= 0.80, **or one cleaned name contains the other as whole words, or
  token-set similarity >= 0.90**; store numbers removed, generic words such as FOOD/MARKET ignored; a contained name needs at least 3 characters) and it was
  authorized from 365 days before to 90 days after the end; or
- **(b)** the identical standardized street address (same ZIP; a unit on only one side counts as a match, two different units do not), at any distance,
  authorized from 30 days before to 90 days after the end (unchanged); or
- **(c) the same store registered twice**: a **strong** name match (containment, token-set >= 0.90 or similarity >= 0.90) within **0.05 mile** or at the
  identical address, authorized **any time** up to 90 days after the end however long the two records overlapped, provided it is **still authorized after
  the end** (a record that had already ended is an earlier record, not a successor). The 365-day co-tenant exclusion therefore applies only when the names
  do not match strongly.

**Overrides.** `data/reference/successor_overrides.csv` (committed: it is a decision, not raw data) lists record pairs that are never successors, in either
direction, each with a reason; `03` reads it and logs every override (the matches it blocked and what the end became). Five rows, four decisions:

| Record | Not a successor | Reason |
|---|---|---|
| 769554 LA PROVIDENCIA INC | 888563 La Providencia Carniceria y Taqueria | authorized 3,605 days before the end: about ten years of concurrent records = separate businesses |
| 857195 Halal Market Inc. | 976622 Halal International | one generic shared word and a ~1,000-day overlap |
| 602288 FAMILY FOODS 02 | 1164387 Discount Family Foods Inc | weak match on the single word "Family" |
| 602288 FAMILY FOODS 02 | 1059577 Family Dollar 8797 | added while applying: with the row above blocked, the rule fell through to this Family Dollar store (0.03 mile, 887 days earlier), again on the single word "Family" |
| 1270506 Jackson Grocery | 1302022 Jackson Minit Serv | the shared word is a place name |

The four decisions are the four weakest matches in the preview list; the fifth row exists only because the first Family Foods override moved the match to a
different store. All four ends are exits again.

**`qa_successor_type_change`** (03, 04; QA only, never a feature; not loaded to Supabase): for ownership changes, true when the successor's store type differs
from the ended store's. Of the 458 store-years that ended in 2008-2021 as ownership changes, 264 changed type: 139 to a non-grocery type (113 convenience
stores, 15 combination grocery/other, 11 specialty) and 125 between grocery types (for example Supermarket to Super Store).

### Before and after (train + validation)

| | Original rule | Revision 1 | Revision 2 | **Revision 3 (current)** |
|---|---|---|---|---|
| Spells ended through 2021 that are ownership changes (all store types) | 2,675 | 2,936 | 3,039 | **3,162** |
|   of which a revision 3 "same store" match | | | | 64 |
| `exit_12m` exits | 1,161 | 1,108 | 1,092 | **1,071** |
|   train (2008-2018) | 920 | 874 | 861 | 846 |
|   validation (2019-2021) | 241 | 234 | 231 | 225 |
|   2012-2018 train (the ACS comparison rows) | 678 | 652 | 641 | **632** |
|   2008-2011 | 242 | 222 | 220 | 214 |
| `exit_12m_strict` exits | 593 | 554 | 539 | **529** |
| Batch exits | 568 | 554 | 553 | 542 |
| Statewide share of exits with the next grocery > 1 mile | 262 of 1,161 (22.6%) | 254 of 1,108 (22.9%) | 250 of 1,092 (22.9%) | 250 of 1,071 (23.3%) |
| Mecklenburg share > 1 mile | 7 of 140 (5.0%) | 7 of 135 (5.2%) | 7 of 133 (5.3%) | 7 of 131 (5.3%) |
| Statewide share > 1 mile, strict-label exits | 106 of 593 (17.9%) | 100 of 554 (18.1%) | 96 of 539 (17.8%) | 96 of 529 (18.1%) |
| Exit rate, train / validation | 4.08% / 3.80% | 3.88% / 3.69% | 3.82% / 3.64% | 3.75% / 3.54% |

Store-years (28,902) and every ACS / density feature are unchanged; `n_prior_ownership_changes` can shift where a lineage gained or lost a link.
The revision 2 to revision 3 steps, in exits:
- the rule alone, before the overrides, would have moved 25 exits (1,092 to 1,067): 13 batch and 12 non-batch; the five override rows put 4 of them
  back (La Providencia, Halal Market, Family Foods 02, Jackson Grocery), so **21 exits** moved in the end (1,092 to 1,071; 11 batch, 10 non-batch;
  strict 539 to 529);
- 27 grocery spells in all changed from exit to ownership change (21 are `exit_12m` exits on a January 1; 6 ended in the year they started, so they never had
  a store-year row); the list, with names, distances, dates and why revision 2 missed each, is in `docs/successor_revision3_changes.md`;
- no revision 2 successor was lost, and the applied rule is asserted to reproduce `spells.parquet` and `exit_12m` (`src/eda/successor_revision3.py`).

### What to know about revision 3
- The new tiers lean on names. Single-word containment (a chain or place name such as "Compare", "Jackson", "Halal", "Family") produced the three weakest
  matches and the overrides remove those; a general guard against single-word matches would be a further revision.
- Same-chain stores with different store numbers at one location (Save-A-Lot 577 / 44, Walmart 1527 / 1527) are now read as the same store; the
  alternative (two stores sharing a site for years) cannot be excluded from these data alone.
- The successor search looks at all records, so a successor that started up to 90 days after a 2021 end can start in early 2022; this is the disclosure
  already in `docs/test_reservation_log.md`, and no date after 2021-12-31 is shown anywhere.

## Revision 2 and earlier (history)

### Why revision 1 was needed
The exit-proximity review (`docs/exit_proximity_report.md`) found a cluster of exits with another grocery within 0.01 mile. Many
were stores re-registered under a new Record ID (renamed, renumbered, or re-licensed after a bankruptcy), authorized months BEFORE
the old record ended. The original rule (same address key, authorized from 30 days before to 90 days after the end) could not see
them: for example Earth Fare 120's successor was authorized 252 days before the end.

### The revision 2 rule (superseded by revision 3 above; `src/prep/03_spells.py`, thresholds in `src/prep/matching.py`)
A different Record ID is a **successor**, and the end an **ownership change** (not an exit), if either
- **(a)** it is within **0.15 mile** of the ended store, its store name is similar (cleaned-name similarity >= 0.80, store numbers
  removed, generic words such as FOOD/MARKET ignored), and it was authorized **from 365 days before to 90 days after** the end; or
- **(b)** it has the **identical standardized street address** (same ZIP) and was authorized from **30 days before to 90 days after**
  the end. A unit listed on only one of the two stores counts as a match; two different units do not. Distance is not tested (an
  identical address with distant geocodes is a geocoding error) and coordinates are not needed.

No candidate authorized more than 365 days before the end is considered. Any store type can be a successor. Same-Record-ID periods
at most 90 days apart are one spell (unchanged). `02_clean.py` standardizes ordinals (FIFTH ST = 5TH ST), more suffix variants, and
extracts the unit (suite text in the street, Additional Address, or a letter after the number, as in `4816-B`) into `unit_std`;
`address_core` ignores direction and suffix words.

Revision 1 differed in (b) only: it required the identical address AND identical unit (a missing unit on one side was a conflict) AND
a distance of at most 0.15 mile.

### Before and after, revisions 1 and 2 (train + validation; the four-column table above includes them)

| | Original rule | Revision 1 | Revision 2 |
|---|---|---|---|
| Spells ended through 2021 that are ownership changes | 2,675 | 2,936 | 3,039 |
| `exit_12m` exits | 1,161 | 1,108 | **1,092** |
|   train (2008-2018) | 920 | 874 | 861 |
|   validation (2019-2021) | 241 | 234 | 231 |
|   2012-2018 train (the ACS comparison rows) | 678 | 652 | 641 |
| `exit_12m_strict` exits | 593 | 554 | **539** |
| Batch exits | 568 | 554 | 553 |
| Statewide share of exits with the next grocery > 1 mile | 262 of 1,161 (22.6%) | 254 of 1,108 (22.9%) | 250 of 1,092 (22.9%) |
| Mecklenburg share > 1 mile | 7 of 140 (5.0%) | 7 of 135 (5.2%) | 7 of 133 (5.3%) |
| Statewide share > 1 mile, strict-label exits | 106 of 593 (17.9%) | 100 of 554 (18.1%) | 96 of 539 (17.8%) |
| Exit rate, train / validation | 4.08% / 3.80% | 3.88% / 3.69% | 3.82% / 3.64% |

Store-years (28,902) and every feature are unchanged. Earth Fare 120 (Record ID 740603, exit 2021-07-19) is an ownership change to
Record ID 1429066 under both revisions (basis: name, similarity 1.00, 0.059 mile, authorized 252 days before the end).

### What moved, original to revision 2
- **Original to revision 1:** 344 spells became ownership changes (similar name 253, identical address 53, both 38; 143 of them started
  more than 30 days before the end, which only the 365-day lookback sees) and 83 stopped being ownership changes (18 grocery). At the
  store-year level 65 exits stopped being exits and 12 non-exits became exits again (net -53).
- **Revision 1 to revision 2:** 105 more spells became ownership changes (26 grocery, all matched on the identical address; 22 have no
  usable coordinate for one store and 45 are geocoded more than 0.15 mile apart) and 2 (non-grocery) dropped out. At the store-year
  level 16 exits stopped being exits (one a batch end) and none became an exit. This restores 11 of the 12 exits revision 1 had added
  back (6 with an address+unit match but distant geocodes, 5 with a unit on one side only) and adds 5 more.
- **Net, original to revision 2:** 70 exits stopped being exits, 1 non-exit became an exit (Gueros Tienda y Carniceria, unit B2,
  followed 20 days later by Friends Mini Market, unit B, at 1406 Western Blvd: two different units), net -69.
- The new address matches look like real conversions (Lowes Foods 220 to Harris Teeter 472, Winn Dixie 2076 to Food Lion 2651,
  Kroger 358 to Harris Teeter 362 at one address). The risk of a missing-unit wildcard is a second tenant in the same building being
  read as a successor (e.g. K & B Convenience Store followed 12 days later by Higgins Curb Market, unit A).

### Sensitivity: the 90-day merge threshold (kept at 90 days)
Same-Record-ID periods are merged into one spell only when the gap is at most 90 days (`MERGE_GAP_DAYS`). A longer threshold would make
some exits continuous authorization. From `docs/reentry_gap_report.md` (re-entries seen through the end of the data):

| Merge when the gap is at most | Exits that would disappear | Share of exits | Jan-1 store-years added inside those gaps |
|---|---|---|---|
| 90 days (current) | 0 | 0.0% | 0 |
| 180 days | 10 | 0.9% | 2 |
| **365 days** | **33** | **3.0%** | **17** |

At 365 days, 33 of the 1,092 exits (24 non-batch, 9 batch ends) would not be exits and 17 store-years would be added. The effect is
modest because most re-entries are long: the median gap is 310 days but a quarter of the re-entries are gone more than two years.

### What was still counted as an exit under revision 2
45 exits still have a grocery within 0.15 mile that matches by name or identical address+unit; in 21 of them the matching store started
more than a year before the exit (co-tenants or long-standing duplicates), in 11 it started 181-365 days before with only the address
in common (the name rule needs a similar name, the address rule only looks back 30 days), and 13 are identical-address matches that
started within 180 days before.

## Reproduce
`02_clean.py`, `03_spells.py`, `04_panel.py`, `05_features.py`, `05b_location_gaps.py`, then the EDA scripts (`successor_revision3.py` regenerates the revision 3 tables) and `06_load_supabase.py --replace`.
