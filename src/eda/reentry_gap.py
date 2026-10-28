"""Re-authorization gap analysis: exits whose Record ID is authorized again later (more than 90 days after the end).

REPORT ONLY (labels unchanged). TRAIN and VALIDATION exits only (cohort years 2008-2021), under the CURRENT labels.

Reads : data/interim/panel_trainval.parquet, spells.parquet, periods_spells.parquet, retailers_nc_clean.parquet
Writes: docs/reentry_gap_report.md, figures/g_reentry_gap.png, figures/data/g_reentry_gap.csv

Same-Record-ID periods separated by 90 days or less are already ONE spell (03_spells.py), so every re-entry here is a gap of more
than 90 days and counts as an exit followed by a re-entry. `qa_reentered_later` / `qa_reentry_gap_days` (never features) use events up
to the end of the data (Dec 2025); every number is also given for re-entries that started by 2021-12-31.
"""

import sys
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "prep"))
from common import DATA_THROUGH, DOCS, FIGURES, INTERIM, VAL_END_YEAR, ensure_dirs  # noqa: E402
from matching import RADIUS_MI  # noqa: E402

CUTOFF = pd.Timestamp(DATA_THROUGH)
SURFACE, INK, INK2, MUTED, GRID, AXIS = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
BLUE, ORANGE = "#2a78d6", "#eb6834"      # blue = exit_12m only (batch ends), orange = exit_12m_strict
BUCKETS = [(91, 180, "91-180 days"), (181, 365, "181-365 days"), (366, 730, "1-2 years"), (731, 10_000, "more than 2 years")]
MERGE_ALTERNATIVES = (180, 365)


def md(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    lines += ["| " + " | ".join(str(v) for v in r) + " |" for r in df.itertuples(index=False)]
    return "\n".join(lines)


def summarize(label: str, base: pd.DataFrame, re_: pd.DataFrame) -> dict:
    g = re_["gap"]
    return {"exits": label, "n": len(base), "re-entered later": len(re_), "share": f"{100 * len(re_) / len(base):.1f}%" if len(base) else "n/a",
            "median gap (days)": int(g.median()) if len(g) else "n/a", "25th-75th pct (days)": f"{int(g.quantile(.25))}-{int(g.quantile(.75))}" if len(g) else "n/a",
            "median gap (years)": f"{g.median() / 365.25:.1f}" if len(g) else "n/a"}


def main() -> None:
    ensure_dirs()
    panel = pd.read_parquet(INTERIM / "panel_trainval.parquet")
    assert panel["year"].max() <= VAL_END_YEAR and not panel["split"].eq("test").any()
    ex = panel[panel["exit_12m"] == 1].copy().reset_index(drop=True)
    ex["end"] = pd.to_datetime(ex["qa_spell_end"])
    ex["re"] = ex["qa_reentered_later"].fillna(False).astype(bool)
    ex["gap"] = ex["qa_reentry_gap_days"].astype("float")
    ex["re_start"] = ex["end"] + pd.to_timedelta(ex["gap"], unit="D")
    re_all = ex[ex["re"]].copy()
    re_21 = re_all[re_all["re_start"] <= CUTOFF]
    batch, nonbatch = ex[ex["exit_is_batch"] == True], ex[ex["exit_is_batch"] == False]  # noqa: E712
    headline = pd.DataFrame([
        summarize("all exits, re-entry seen through the end of the data (Dec 2025)", ex, re_all),
        summarize("  batch-end exits (exit_12m only)", batch, re_all[re_all["exit_is_batch"] == True]),  # noqa: E712
        summarize("  non-batch exits (exit_12m_strict)", nonbatch, re_all[re_all["exit_is_batch"] == False]),  # noqa: E712
        summarize("all exits, re-entry started by 2021-12-31 only", ex, re_21),
        summarize("  non-batch exits, by 2021-12-31 only", nonbatch, re_21[re_21["exit_is_batch"] == False]),  # noqa: E712
    ])

    def bucket_table(r: pd.DataFrame) -> pd.DataFrame:
        rows = []
        for lo, hi, name in BUCKETS:
            sel = r[(r["gap"] >= lo) & (r["gap"] <= hi)]
            rows.append({"gap": name, "all exits": len(sel), "batch": int((sel["exit_is_batch"] == True).sum()), "non-batch": int((sel["exit_is_batch"] == False).sum())})  # noqa: E712
        return pd.DataFrame(rows)

    gaps_tbl = bucket_table(re_all)

    # ---- by split, store type, exit year (right-censoring: later exits had less time to come back)
    # Equal follow-up for every exit year: came back within 3 years (every exit through 2021 has at least 4 years of data after it).
    ex["re3"] = ex["re"] & (ex["gap"] <= 3 * 365)
    by_year = ex.groupby("year").agg(exits=("re", "size"), re_entered=("re", "sum"), re_within_3y=("re3", "sum")).reset_index()
    by_year["share"] = (100 * by_year["re_entered"] / by_year["exits"]).round(1).astype(str) + "%"
    by_year["share within 3 years"] = (100 * by_year["re_within_3y"] / by_year["exits"]).round(1).astype(str) + "%"
    early, late = ex[ex["year"] <= 2018], ex[ex["year"] >= 2019]
    drift = (f"**The share that returns rises sharply for recent exits, and not because of follow-up time.** Within 3 years of the exit, "
             f"{100 * early['re3'].mean():.1f}% ({int(early['re3'].sum())} of {len(early)}) of the 2008-2018 (train) exits came back under the same Record ID, "
             f"against {100 * late['re3'].mean():.1f}% ({int(late['re3'].sum())} of {len(late)}) of the 2019-2021 (validation) exits; the median gap of the "
             f"re-entries fell from {int(early.loc[early['re'], 'gap'].median())} to {int(late.loc[late['re'], 'gap'].median())} days. "
             "Either USDA started keeping the Record ID when a lapsed store is re-authorized, or lapses and renewals became more common (for example around 2020-2021), "
             "so recent exits are more often temporary. The cause is not identified here.")
    ex_type = ex.groupby("store_type").agg(exits=("re", "size"), re_entered=("re", "sum")).reset_index()
    ex_type["share"] = (100 * ex_type["re_entered"] / ex_type["exits"]).round(1).astype(str) + "%"
    ex_type = ex_type.sort_values("exits", ascending=False)

    # ---- where do they come back? exit spell's last period vs the re-entry spell's first period
    per = pd.read_parquet(INTERIM / "periods_spells.parquet")
    ret = pd.read_parquet(INTERIM / "retailers_nc_clean.parquet")[["record_id", "period_seq", "address_core", "unit_std"]]
    per = per.merge(ret, on=["record_id", "period_seq"], how="left").sort_values(["spell_id", "period_seq"])
    lastp, firstp = per.groupby("spell_id").last(), per.groupby("spell_id").first()
    nxt = [f"{r}-{int(s.split('-')[1]) + 1}" for r, s in zip(re_all["record_id"], re_all["spell_id"])]
    a, b = lastp.loc[re_all["spell_id"]].reset_index(), firstp.loc[nxt].reset_index()
    xa = gpd.GeoSeries(gpd.points_from_xy(a["longitude"], a["latitude"]), crs="EPSG:4269").to_crs("EPSG:32119")
    xb = gpd.GeoSeries(gpd.points_from_xy(b["longitude"], b["latitude"]), crs="EPSG:4269").to_crs("EPSG:32119")
    dist = np.array([p.distance(q) / 1609.344 if (pd.notna(la) and pd.notna(lb)) else np.nan for p, q, la, lb in zip(xa, xb, a["latitude"], b["latitude"])])
    unit = lambda s: s.where(s.notna(), None)  # noqa: E731
    same_core = (a["address_core"].values == b["address_core"].values) & a["address_core"].notna().values
    same_unit = np.array([(u1 if isinstance(u1, str) else None) == (u2 if isinstance(u2, str) else None) for u1, u2 in zip(a["unit_std"], b["unit_std"])])
    where = np.select(
        [np.isnan(dist), same_core & same_unit, same_core & ~same_unit, dist <= RADIUS_MI],
        ["coordinates missing", "same address and unit", "same street address, different unit", f"different address within {RADIUS_MI} mile"],
        default=f"more than {RADIUS_MI} mile away")
    where_tbl = pd.Series(where).value_counts().rename_axis("re-entry location vs the exit").reset_index(name="exits")
    # same Record ID but a different store name? (renamed on return)
    same_name = (a["name_std"].values == b["name_std"].values)
    name_line = f"{int(same_name.sum())} of {len(re_all)} re-entries keep the same standardized store name."

    # ---- what would a longer merge threshold do? (exits that would disappear; Jan-1 store-years that would be added inside the gap)
    alt = []
    for th in (90,) + MERGE_ALTERNATIVES:
        sel = re_all[re_all["gap"] <= th]
        added = 0
        for e, s in zip(sel["end"], sel["re_start"]):
            added += sum(pd.Timestamp(y, 1, 1) > e and pd.Timestamp(y, 1, 1) < s for y in range(e.year, s.year + 2))
        alt.append({"merge same-Record-ID periods when the gap is <= (days)": th, "exits that would disappear": len(sel),
                    "share of exits": f"{100 * len(sel) / len(ex):.1f}%", "Jan-1 store-years added inside those gaps": added})
    alt_tbl = pd.DataFrame(alt)

    # ---- figure: gap histogram, stacked batch vs non-batch
    edges = np.arange(90, 1465, 90)
    fig, ax = plt.subplots(figsize=(10.5, 5.2))
    plt.rcParams.update({"font.family": "Segoe UI", "axes.facecolor": SURFACE, "figure.facecolor": SURFACE, "axes.edgecolor": AXIS,
                         "axes.spines.top": False, "axes.spines.right": False, "axes.spines.left": False})
    bottom = np.zeros(len(edges) - 1)
    for sel, color, lab in ((re_all[re_all["exit_is_batch"] == False], ORANGE, "non-batch exits (in exit_12m_strict)"),  # noqa: E712
                            (re_all[re_all["exit_is_batch"] == True], BLUE, "batch-end exits (exit_12m only)")):  # noqa: E712
        h, _ = np.histogram(sel["gap"].clip(upper=edges[-1] - 1), bins=edges)
        ax.bar(edges[:-1], h, width=82, align="edge", bottom=bottom, color=color, edgecolor=SURFACE, linewidth=0.8, label=f"{lab}: {len(sel)}")
        bottom += h
    ax.set_xlim(90, edges[-1])
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(length=0, colors=INK2)
    ax.set_xlabel("Days from the exit to the start of the later authorization of the same Record ID (90-day bins; last bin includes longer gaps)", color=INK2)
    ax.set_ylabel("Exits", color=INK2)
    ax.legend(frameon=False, fontsize=9)
    fig.text(0.012, 0.965, "Exits that come back under the same Record ID: how long were they gone?", fontsize=13.5, fontweight="bold", ha="left", va="top", color=INK)
    fig.text(0.012, 0.905, f"{len(re_all)} of {len(ex):,} train and validation exits (2008-2021) are authorized again later (re-entry seen through the end of the data).",
             fontsize=9.5, ha="left", va="top", color=INK2)
    fig.subplots_adjust(top=0.82, bottom=0.16)
    fig.text(0.012, 0.012, "Source: USDA FNS SNAP Retailer Locator; own calculations. Train 2008-2018 and validation 2019-2021 exits only.", fontsize=7.5, color=MUTED)
    fig.savefig(FIGURES / "g_reentry_gap.png", dpi=160, facecolor=SURFACE)
    plt.close(fig)
    gaps_tbl.to_csv(FIGURES / "data" / "g_reentry_gap.csv", index=False)

    out = [
        "# Re-authorization gap analysis (report only; labels unchanged)", "",
        "Generated by `src/eda/reentry_gap.py`; do not edit by hand. Train and validation exits only (2008-2021), under the current labels "
        f"({len(ex):,} exits, {len(nonbatch):,} of them non-batch). A re-entry is the same Record ID authorized again in a LATER spell, so the gap is always more than "
        "90 days (shorter gaps are one spell). `qa_reentered_later` / `qa_reentry_gap_days` are QA columns, never features, because they use events after the exit.", "",
        "![gap](../figures/g_reentry_gap.png)", "",
        "## Headline", "", md(headline), "",
        "Re-entries observed only through 2021-12-31 undercount, because later exits and later years had less time to return; the first row also includes re-entries in 2022-2025.", "",
        "## How long were they gone?", "", md(gaps_tbl), "",
        "## Where do they come back?", "", md(where_tbl), "", name_line, "",
        "## By exit year and store type", "", md(by_year[["year", "exits", "re_entered", "share", "share within 3 years"]]), "", drift, "",
        md(ex_type[["store_type", "exits", "re_entered", "share"]]), "",
        "## What would a longer merge threshold do?", "",
        "Today periods of one Record ID are merged into one spell when the gap is at most 90 days (`MERGE_GAP_DAYS` in `03_spells.py`). A longer threshold would make the exits below "
        "continuous authorization, but the store-years that fall inside such gaps would then count as active on Jan 1.", "", md(alt_tbl), "",
    ]
    (DOCS / "reentry_gap_report.md").write_text("\n".join(out), encoding="utf-8")
    print(f"Wrote {DOCS / 'reentry_gap_report.md'}")


if __name__ == "__main__":
    main()
