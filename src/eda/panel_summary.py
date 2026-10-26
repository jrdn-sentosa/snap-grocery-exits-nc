"""Panel summary: store-years per split, geography coverage, and the exit-impact distance.

Reads : data/interim/panel_trainval.parquet (all columns)
        data/interim/panel_test.parquet     (ONLY year, record_id, and the geography columns:
                                             never labels, exit dates, or impact distances)
Writes: docs/panel_summary.md

Test-set discipline: the impact-distance and label tables use train + validation exits only.
"""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "prep"))
from common import DOCS, INTERIM, RUCA_GROUP_ORDER, VAL_END_YEAR, ensure_dirs  # noqa: E402

TEST_SAFE_COLUMNS = ["record_id", "year", "split", "qa_coord_invalid", "qa_tract_unmatched",
                     "tract_geoid_2010", "tract_geoid_2020", "county", "ruca_group"]
DIST = "impact_dist_nearest_other_grocery_mi"


def md_table(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    lines += ["| " + " | ".join(str(v) for v in r) + " |" for r in df.itertuples(index=False)]
    return "\n".join(lines)


def main() -> None:
    ensure_dirs()
    tv = pd.read_parquet(INTERIM / "panel_trainval.parquet")
    te = pd.read_parquet(INTERIM / "panel_test.parquet", columns=TEST_SAFE_COLUMNS)
    assert tv["year"].max() <= VAL_END_YEAR
    allrows = pd.concat([tv[TEST_SAFE_COLUMNS], te], ignore_index=True)

    # 1. store-years per split and 2. geography coverage (descriptive counts, all splits)
    order = ["train", "validation", "test"]
    rows, geo = [], []
    for s in order + ["all"]:
        g = allrows if s == "all" else allrows[allrows["split"] == s]
        yrs = f"{g['year'].min()}-{g['year'].max()}"
        rows.append({"split": s, "years": yrs, "store_years": f"{len(g):,}", "distinct Record IDs": f"{g['record_id'].nunique():,}"})
        geo.append({
            "split": s, "store_years": f"{len(g):,}",
            "qa_coord_invalid (no coords)": int(g["qa_coord_invalid"].sum()),
            "valid coords, no 2010 tract": int((~g["qa_coord_invalid"] & g["tract_geoid_2010"].isna()).sum()),
            "valid coords, no 2020 tract": int((~g["qa_coord_invalid"] & g["tract_geoid_2020"].isna()).sum()),
            "lacking any tract": int((g["tract_geoid_2010"].isna() | g["tract_geoid_2020"].isna()).sum()),
            "valid coords, no RUCA group": int((~g["qa_coord_invalid"] & g["ruca_group"].isna()).sum()),
        })

    # 3. impact distance: true exits in train/validation only, both labels, Mecklenburg vs rest of NC
    ex = tv[tv["exit_12m"] == 1].copy()
    ex["region"] = ex["county"].map(lambda c: "Mecklenburg" if c == "MECKLENBURG" else "Rest of NC")
    scopes = {"train": ex[ex["split"] == "train"], "validation": ex[ex["split"] == "validation"], "train + validation": ex}
    dist_rows = []
    for sname, e in scopes.items():
        for label, sub in (("exit_12m (all true exits)", e), ("exit_12m_strict (non-batch exits)", e[e["exit_12m_strict"] == 1])):
            for region, r in (("Mecklenburg", sub[sub["region"] == "Mecklenburg"]), ("Rest of NC", sub[sub["region"] == "Rest of NC"]), ("All NC", sub)):
                d = r[DIST].dropna()
                dist_rows.append({
                    "split": sname, "label": label, "region": region, "exits": len(r), "with distance": len(d),
                    "median mi": f"{d.median():.2f}" if len(d) else "n/a",
                    "p25-p75 mi": f"{d.quantile(.25):.2f}-{d.quantile(.75):.2f}" if len(d) else "n/a",
                    "within 0.5 mi": f"{100 * (d <= 0.5).mean():.0f}%" if len(d) else "n/a",
                })

    # 4. how far is "far"? shares of exits with no other grocery within 1 mi / 10 mi
    far_rows = []
    labels = (("exit_12m (all true exits)", ex), ("exit_12m_strict (non-batch exits)", ex[ex["exit_12m_strict"] == 1]))
    for dim, col, cats in (("RUCA group", "ruca_group", RUCA_GROUP_ORDER), ("Region", "region", ["Mecklenburg", "Rest of NC"])):
        for cat in cats:
            for label, sub in labels:
                d = sub.loc[sub[col] == cat, DIST].dropna()
                far_rows.append({
                    "dimension": dim, "group": cat, "label": label, "exits": len(d),
                    "> 1 mi (n)": int((d > 1).sum()), "> 1 mi (%)": f"{100 * (d > 1).mean():.1f}%" if len(d) else "n/a",
                    "> 10 mi (n)": int((d > 10).sum()), "> 10 mi (%)": f"{100 * (d > 10).mean():.1f}%" if len(d) else "n/a",
                })
        for label, sub in labels:
            d = sub[DIST].dropna()
            far_rows.append({
                "dimension": dim, "group": "All NC", "label": label, "exits": len(d),
                "> 1 mi (n)": int((d > 1).sum()), "> 1 mi (%)": f"{100 * (d > 1).mean():.1f}%",
                "> 10 mi (n)": int((d > 10).sum()), "> 10 mi (%)": f"{100 * (d > 10).mean():.1f}%",
            })

    out = [
        "# Panel summary",
        "",
        "Generated by `src/eda/panel_summary.py`; do not edit by hand. The test file is read for geography columns only",
        "(no labels, exit dates or impact distances); outcome and distance tables use train + validation (2008-2021) only.",
        "",
        "## 1. Store-years per split", "", md_table(pd.DataFrame(rows)), "",
        "## 2. Geography coverage (grocery store-years)", "", md_table(pd.DataFrame(geo)), "",
        "## 3. Distance to nearest other grocery at exit (train + validation exits)", "",
        "`impact_dist_nearest_other_grocery_mi`: miles from the exiting store to the nearest other grocery-type store still",
        "authorized after the exit date (others ending the same day excluded). Outcome-side column, never a predictor.",
        "",
        md_table(pd.DataFrame(dist_rows)), "",
        "## 4. Exits with no other grocery within 1 mi and within 10 mi (train + validation, 2008-2021)", "",
        "RUCA group from the 2010 codes on 2010 tracts (all train/validation years): urban = primary RUCA 1, suburban = 2-3,",
        "small town = 4-9 (micropolitan and small-town tracts), rural = 10, unclassified = 99. \"> 1 mi\" means the nearest other",
        "grocery was more than 1 mile away. Counts are exits with a distance; the label rows overlap (strict is a subset of all).",
        "",
        md_table(pd.DataFrame(far_rows)), "",
    ]
    (DOCS / "panel_summary.md").write_text("\n".join(out), encoding="utf-8")
    print(f"Wrote {DOCS / 'panel_summary.md'}")


if __name__ == "__main__":
    main()
