"""Location-level SNAP coverage gaps (data through 2021-12-31 only).

Reads : data/processed/location_gap.parquet   (built by 05b_location_gaps.py; ends 2008-01-01 .. 2021-12-31, nothing later)
Writes: docs/location_gap_report.md, figures/h_location_gap.png, figures/data/h_location_gap.csv

For every grocery-type record that ended, how long did its LOCATION go without ANY SNAP authorization (any Record ID, any store type) until
the next one started? Overlaps count as 0. "Not re-authorized by 2021-12-31" mixes locations that never came back with ones that had not
yet (censoring); the equal-follow-up table at the end limits the ends to 2008-2018 so every one had at least three years.
"""

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "prep"))
from common import DATA_THROUGH, DOCS, FIGURES, PROCESSED, TRAIN_END_YEAR, VAL_END_YEAR, ensure_dirs  # noqa: E402

CLASSES = ["0 days", "1-90 days", "91-365 days", "more than 365 days", "not re-authorized by 2021-12-31"]
# ordered gap lengths: one blue ramp, light to dark (the validated sequential steps 250 / 400 / 550 / 700); gray = no re-authorization seen
COLORS = ["#86b6ef", "#3987e5", "#1c5cab", "#0d366b", "#c3c2b7"]
SURFACE, INK, INK2, MUTED, GRID, AXIS = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
GROCERY_ORDER = ["Supermarket", "Super Store", "Large Grocery Store", "Medium Grocery Store", "Small Grocery Store"]


def md(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    lines += ["| " + " | ".join(str(v) for v in r) + " |" for r in df.itertuples(index=False)]
    return "\n".join(lines)


def dist_row(label: str, g: pd.DataFrame) -> dict:
    n = len(g)
    row = {"group": label, "n": n}
    for c in CLASSES:
        row[c] = 100 * (g["gap_class"] == c).mean() if n else np.nan
    return row


def main() -> None:
    ensure_dirs()
    g = pd.read_parquet(PROCESSED / "location_gap.parquet")
    assert g["end_date"].max() <= pd.Timestamp(DATA_THROUGH) and g["end_year"].max() <= VAL_END_YEAR, "a date after the cut-off is present"
    g["area"] = np.where(g["county"] == "MECKLENBURG", "Mecklenburg", "Rest of NC")

    groups = [("All ended grocery records", g)]
    groups += [(t, g[g["store_type"] == t]) for t in GROCERY_ORDER]
    groups += [("Batch-end", g[g["is_batch"]]), ("Non-batch end", g[~g["is_batch"]])]
    groups += [("Mecklenburg", g[g["area"] == "Mecklenburg"]), ("Rest of NC", g[g["area"] == "Rest of NC"])]
    groups += [(f"Ended 2008-{TRAIN_END_YEAR} (train)", g[g["split"] == "train"]), (f"Ended {TRAIN_END_YEAR + 1}-{VAL_END_YEAR} (validation)", g[g["split"] == "validation"])]
    groups += [("Ended as an exit (label)", g[g["end_kind"] == "exit"]), ("Ended as an ownership change", g[g["end_kind"] == "ownership change"])]
    tbl = pd.DataFrame([dist_row(lab, d) for lab, d in groups])
    out_csv = tbl.copy()
    out_csv.to_csv(FIGURES / "data" / "h_location_gap.csv", index=False)

    # ---- figure: 100% stacked bars, one row per group; blank lines separate the blocks
    # indices into `groups`: 0 all, 1-5 types, 6-7 batch, 8-9 area, 10-11 split, 12-13 end kind; None = a blank line between blocks
    layout = [0, None, 1, 2, 3, 4, 5, None, 6, 7, None, 8, 9, None, 10, 11, None, 12, 13]
    plt.rcParams.update({"font.family": "Segoe UI", "axes.facecolor": SURFACE, "figure.facecolor": SURFACE, "axes.edgecolor": AXIS,
                         "axes.spines.top": False, "axes.spines.right": False, "axes.spines.left": False})
    fig, ax = plt.subplots(figsize=(11.5, 8.2))
    ypos, labels, y = [], [], 0
    for item in layout:
        if item is None:
            y += 0.55
            continue
        lab, d = groups[item]
        left = 0.0
        for c, color in zip(CLASSES, COLORS):
            v = 100 * (d["gap_class"] == c).mean()
            ax.barh(y, v, left=left, height=0.72, color=color, edgecolor=SURFACE, linewidth=1.2, label=c if item == 0 else None)
            if v >= 7:
                ax.text(left + v / 2, y, f"{v:.0f}%", ha="center", va="center", fontsize=8.5, color="white" if c in CLASSES[1:4] else INK)
            left += v
        ypos.append(y)
        labels.append(f"{lab}  (n={len(d):,})")
        y += 1
    ax.set_yticks(ypos)
    ax.set_yticklabels(labels, fontsize=9.5, color=INK2)
    ax.invert_yaxis()
    ax.set_xlim(0, 100)
    ax.xaxis.set_major_formatter(lambda v, _: f"{v:.0f}%")
    ax.tick_params(length=0, colors=INK2)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.set_xlabel("Share of ended grocery-type records", color=INK2)
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=5, frameon=False, fontsize=8.8, handlelength=1.2, columnspacing=1.2)
    fig.text(0.012, 0.972, "How long did a location go without any SNAP authorization after a grocery record ended there?", fontsize=13.5, fontweight="bold", ha="left", va="top", color=INK)
    fig.text(0.012, 0.935, f"{len(g):,} grocery-type records that ended 2008-2021; gap to the next authorization at the same address under any Record ID (overlaps = 0 days). Data through {DATA_THROUGH}.",
             fontsize=9.5, ha="left", va="top", color=INK2)
    fig.subplots_adjust(top=0.86, bottom=0.07, left=0.27)
    fig.text(0.012, 0.012, "Source: USDA FNS SNAP Retailer Locator; own calculations. Records that ended through 2021-12-31 only. 'Not re-authorized' includes locations that had not yet had time to come back.", fontsize=7.5, color=MUTED)
    fig.savefig(FIGURES / "h_location_gap.png", dpi=160, facecolor=SURFACE)
    plt.close(fig)

    # ---- equal follow-up: ends through 2018 only (every one has at least 3 years before the cut-off)
    eq = g[g["end_date"] <= pd.Timestamp(f"{TRAIN_END_YEAR}-12-31")]
    cutoff3 = 3 * 365
    def within(d: pd.DataFrame) -> str:
        n = len(d)
        if not n:
            return "n/a"
        k = int((d["gap_days"].notna() & (d["gap_days"] <= cutoff3)).sum())
        return f"{100 * k / n:.0f}% ({k} of {n})"
    eq_rows = [{"group": lab, "location re-authorized within 3 years": within(d)} for lab, d in
               [("All, ended 2008-2018", eq), ("Exits", eq[eq["end_kind"] == "exit"]), ("Ownership changes", eq[eq["end_kind"] == "ownership change"]),
                ("Batch-end", eq[eq["is_batch"]]), ("Non-batch end", eq[~eq["is_batch"]]), ("Mecklenburg", eq[eq["area"] == "Mecklenburg"]), ("Rest of NC", eq[eq["area"] == "Rest of NC"])]]
    eq_rows += [{"group": t, "location re-authorized within 3 years": within(eq[eq["store_type"] == t])} for t in GROCERY_ORDER]

    show = tbl.copy()
    for c in CLASSES:
        show[c] = show[c].map(lambda v: f"{v:.1f}%")
    ex = g[g["end_kind"] == "exit"]
    n_cov = int((ex["gap_days"] == 0).sum())
    overall = tbl.iloc[0]
    report = [
        "# Location-level SNAP coverage gaps (data through 2021-12-31)", "",
        f"Generated by `src/eda/location_gap_report.py` from `data/processed/location_gap.parquet` (`05b_location_gaps.py`); do not edit by hand. {len(g):,} grocery-type "
        f"records that ended between 2008-01-01 and {DATA_THROUGH}. For each, the number of days its **location** (standardized street address + ZIP; coordinates only when there is no street number) "
        "had no SNAP authorization of any kind, until the next authorization started under any Record ID. An authorization still in force when the record ended, or starting that day, counts as 0 days. "
        f"Nothing after {DATA_THROUGH} is used: a location whose next authorization came later is in the last column.", "",
        "![gaps](../figures/h_location_gap.png)", "",
        "## Distribution", "", md(show), "",
        f"Overall, {overall['0 days']:.0f}% of ended grocery records left their location covered (0 days), {overall['1-90 days']:.0f}% saw a new authorization within 90 days, "
        f"{overall['91-365 days']:.0f}% within a year, {overall['more than 365 days']:.0f}% after more than a year, and {overall['not re-authorized by 2021-12-31']:.0f}% had none by {DATA_THROUGH}.", "",
        f"Of the {len(ex):,} ends labelled **exits**, {n_cov} ({100 * n_cov / len(ex):.0f}%) happened at an address that was still covered by another authorization (co-tenants, "
        "or a duplicate the ownership-change rule could not link); the ownership-change ends are the mirror image, mostly covered at once or re-authorized within 90 days.", "",
        "## Equal follow-up", "",
        f"The last column above is censored: a record that ended in late 2021 had weeks to come back. Limiting to ends through {TRAIN_END_YEAR} gives every record at least three years.", "", md(pd.DataFrame(eq_rows)), "",
        "## Reading it", "",
        "- **0 days** means the address never lost SNAP: another store was already authorized there (a new owner, a co-tenant), so this end is not lost access at that address.",
        "- **1-90 days** is a short hand-over, typically a new owner authorized soon after.",
        "- **91-365 days and more than 365 days** are real gaps: the address went without SNAP for months or years before another authorization.",
        "- **Not re-authorized** is the lasting loss as of the cut-off (or not yet re-authorized for recent ends; see the equal-follow-up table).",
        "- The location is an address, not a building footprint: a plaza address with several tenants stays covered while one of them leaves.", "",
    ]
    (DOCS / "location_gap_report.md").write_text("\n".join(report), encoding="utf-8")
    print(f"Wrote {DOCS / 'location_gap_report.md'}")
    print(show.to_string(index=False))


if __name__ == "__main__":
    main()
