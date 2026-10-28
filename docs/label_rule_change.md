# Label rule changes: the ownership-change rule (2026-10-28)

A static record of how the ownership-change rule changed and what each change did to the labels. Train and validation numbers only.
Revision 1 introduced the combined rule; revision 2 (current) loosened it after an audit of what revision 1 dropped.

## Why
The exit-proximity review (`docs/exit_proximity_report.md`) found a cluster of exits with another grocery within 0.01 mile. Many
were stores re-registered under a new Record ID (renamed, renumbered, or re-licensed after a bankruptcy), authorized months BEFORE
the old record ended. The original rule (same address key, authorized from 30 days before to 90 days after the end) could not see
them: for example Earth Fare 120's successor was authorized 252 days before the end.

## The current rule (revision 2; `src/prep/03_spells.py`, thresholds in `src/prep/matching.py`)
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

## Before and after (train + validation)

| | Original rule | Revision 1 | Revision 2 (current) |
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

## What moved
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

## Sensitivity: the 90-day merge threshold (kept at 90 days)
Same-Record-ID periods are merged into one spell only when the gap is at most 90 days (`MERGE_GAP_DAYS`). A longer threshold would make
some exits continuous authorization. From `docs/reentry_gap_report.md` (re-entries seen through the end of the data):

| Merge when the gap is at most | Exits that would disappear | Share of exits | Jan-1 store-years added inside those gaps |
|---|---|---|---|
| 90 days (current) | 0 | 0.0% | 0 |
| 180 days | 10 | 0.9% | 2 |
| **365 days** | **33** | **3.0%** | **17** |

At 365 days, 33 of the 1,092 exits (24 non-batch, 9 batch ends) would not be exits and 17 store-years would be added. The effect is
modest because most re-entries are long: the median gap is 310 days but a quarter of the re-entries are gone more than two years.

## What is still counted as an exit
45 exits still have a grocery within 0.15 mile that matches by name or identical address+unit; in 21 of them the matching store started
more than a year before the exit (co-tenants or long-standing duplicates), in 11 it started 181-365 days before with only the address
in common (the name rule needs a similar name, the address rule only looks back 30 days), and 13 are identical-address matches that
started within 180 days before.

## Reproduce
`02_clean.py`, `03_spells.py`, `04_panel.py`, `05_features.py`, then the EDA scripts and `06_load_supabase.py --replace`.
