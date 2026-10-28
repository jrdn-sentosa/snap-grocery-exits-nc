# Label rule change: the ownership-change rule (2026-10-28)

A static record of one change to the labels and what it did. Train and validation numbers only.

## Why
The exit-proximity review (`docs/exit_proximity_report.md`) found a cluster of exits with another grocery within 0.01 mile. Many
were stores re-registered under a new Record ID (renamed, renumbered, or re-licensed after a bankruptcy), authorized months BEFORE
the old record ended. The old rule (same address key, authorized from 30 days before to 90 days after the end) could not see them:
for example Earth Fare 120's successor was authorized 252 days before the end.

## The new rule (`src/prep/03_spells.py`, thresholds in `src/prep/matching.py`)
A different Record ID is a **successor**, and the end an **ownership change** (not an exit), if it is within **0.15 mile** of the ended
store and either
- **(a)** its store name is similar (cleaned-name similarity >= 0.80, store numbers removed, generic words such as FOOD/MARKET ignored)
  and it was authorized **from 365 days before to 90 days after** the end; or
- **(b)** it has the **identical standardized street address including the unit** and was authorized from 30 days before to 90 days
  after the end.

No candidate authorized more than 365 days before the end is considered. Any store type can be a successor. `02_clean.py` now
standardizes ordinals (FIFTH ST = 5TH ST), more suffix variants, and extracts the unit (suite text in the street, Additional Address,
or a letter after the number, as in `4816-B`) into `unit_std`; `address_core` ignores direction and suffix words and is only used with
the distance limit.

## Before and after

| Train + validation | Before | After |
|---|---|---|
| Spells ended through 2021 that are ownership changes | 2,675 | 2,936 |
| `exit_12m` exits | 1,161 | **1,108** |
|   train (2008-2018) | 920 | 874 |
|   validation (2019-2021) | 241 | 234 |
|   2012-2018 train (the ACS comparison rows) | 678 | 652 |
| `exit_12m_strict` exits | 593 | **554** |
| Batch exits | 568 | 554 |
| Statewide share of exits with the next grocery > 1 mile | 262 of 1,161 (22.6%) | 254 of 1,108 (22.9%) |
| Mecklenburg share > 1 mile | 7 of 140 (5.0%) | 7 of 135 (5.2%) |
| Statewide share > 1 mile, strict-label exits | 106 of 593 (17.9%) | 100 of 554 (18.1%) |
| Exit rate, train / validation | 4.08% / 3.80% | 3.88% / 3.69% |

Store-years (28,902) and every feature are unchanged. Earth Fare 120 (Record ID 740603, exit 2021-07-19) is now an ownership change to
Record ID 1429066 (basis: name, similarity 1.00, 0.059 mile, authorized 252 days before the end).

## What moved, in both directions
- **Spells ended through 2021:** 344 became ownership changes (basis: similar name 253, identical address 53, both 38; 143 of them
  started more than 30 days before the end, which only the 365-day lookback sees) and 83 stopped being ownership changes (18 grocery).
- **Store-year exits:** 65 exits are no longer exits, 12 non-exits became exits: net -53.
- **Why 12 became exits again** (they were ownership changes under the old rule): 6 have an identical address and unit but geocodes more
  than 0.15 mile apart (0.16 to 4.9 miles), and 6 have a different unit (in 5 of them exactly one of the two stores lists a unit, e.g.
  Food Lion 150 followed 11 days later by The Fresh Market at the same address, unit A3).

## Judgment calls the rule leaves open (not applied)
Counts are of the 12 store-year exits above.

| Possible loosening | Exits it would restore to ownership change |
|---|---|
| Treat a missing unit as a wildcard (conflict only when both stores list a unit and the units differ) | 5 |
| Accept identical address + unit even when the two geocodes are more than 0.15 mile apart | 6 |
| Both | 11 |

The 0.15-mile test also cannot be applied when a store has no valid coordinates (3 grocery spells dropped for that reason; none is a
train/validation store-year exit).

## What is still counted as an exit
45 exits still have a grocery within 0.15 mile that matches by name or identical address+unit; in 21 of them the matching store started
more than a year before the exit (co-tenants or long-standing duplicates), in 11 it started 181-365 days before with only the address
in common (the name rule needs a similar name, the address rule only looks back 30 days), and 13 are identical-address matches that
started within 180 days before.

## Reproduce
`02_clean.py`, `03_spells.py`, `04_panel.py`, `05_features.py`, then the EDA scripts and `06_load_supabase.py --replace`.
