"""Five EDA plots from TRAIN and VALIDATION rows only (cohort years 2008-2021).

Reads : data/processed/store_year_trainval.parquet   labels, store_type, ACS income (plots a, b, e)
        data/interim/panel_trainval.parquet           impact distance and RUCA code (plot d)
        data/interim/retailers_nc_clean.parquet       end dates, filtered to <= 2021-12-31 (plots a, c)
Writes: figures/a_yearly_exit_rate.png, b_exit_rate_by_store_type.png, c_end_dates_per_day.png,
        d_distance_by_ruca.png, e_exit_rate_by_income_quintile.png
        figures/data/*.csv   the numbers behind each plot (the table view of every chart)

Test-set discipline (hard rule 1): the reserved 2022-2024 files are never opened. Every frame is checked
with guard() (year <= 2021, no `test` split) and end dates are cut at 2021-12-31 before use.

Style follows the project dataviz method: one axis per chart, thin marks, hairline grid, a legend whenever
there are two series, colour by entity (blue = exit_12m, orange = exit_12m_strict, validated light-mode
palette), neutral ink for the batch-day overlay.
"""

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "prep"))
from common import DATA_THROUGH, FIGURES, INTERIM, PROCESSED, TRAIN_END_YEAR, VAL_END_YEAR, ensure_dirs  # noqa: E402

CUTOFF = pd.Timestamp(DATA_THROUGH)
# validated reference palette (light mode, surface #fcfcfb)
SURFACE, INK, INK2, MUTED, GRID, AXIS, TINT = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7", "#f0efec"
BLUE, ORANGE = "#2a78d6", "#eb6834"   # exit_12m (primary), exit_12m_strict
FONT = "Segoe UI" if "Segoe UI" in {f.name for f in font_manager.fontManager.ttflist} else "DejaVu Sans"
SOURCE = "Source: USDA FNS SNAP Retailer Locator; own calculations. Train 2008-2018 and validation 2019-2021 only."
PCT = FuncFormatter(lambda v, _: f"{v:.0f}%")


def guard(df: pd.DataFrame, name: str) -> pd.DataFrame:
    assert df["year"].max() <= VAL_END_YEAR, f"{name}: a year after {VAL_END_YEAR} is present"
    assert not df["split"].eq("test").any(), f"{name}: test rows present"
    return df


def style() -> None:
    plt.rcParams.update({
        "font.family": FONT, "font.size": 10, "text.color": INK, "axes.labelcolor": INK2,
        "axes.edgecolor": AXIS, "axes.linewidth": 0.8, "axes.facecolor": SURFACE, "figure.facecolor": SURFACE,
        "xtick.color": MUTED, "ytick.color": MUTED, "xtick.labelcolor": INK2, "ytick.labelcolor": INK2,
        "axes.spines.top": False, "axes.spines.right": False, "axes.spines.left": False,
        "axes.grid": False, "legend.frameon": False, "savefig.facecolor": SURFACE,
    })


def hgrid(ax) -> None:
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(length=0)


def vgrid(ax) -> None:
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(length=0)


def titles(fig, title: str, subtitle: str, top: float = 0.80, left: float | None = None, bottom: float | None = None) -> None:
    fig.text(0.012, 0.965, title, fontsize=13.5, fontweight="bold", ha="left", va="top", color=INK)
    fig.text(0.012, 0.905, subtitle, fontsize=9.5, ha="left", va="top", color=INK2)
    fig.subplots_adjust(top=top, left=left, bottom=bottom)


def footer(fig, extra: str = "", scope: str = SOURCE) -> None:
    fig.text(0.012, 0.012, (extra + " " + scope).strip(), fontsize=7.5, ha="left", va="bottom", color=MUTED)


def as_counts(t: pd.DataFrame) -> pd.DataFrame:
    """Counts come from float64 label columns (see main); show them as integers."""
    for c in ("exits", "strict_n", "strict_exits", "store_years"):
        if c in t:
            t[c] = t[c].astype(int)
    return t


def save(fig, name: str) -> None:
    FIGURES.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIGURES / name, dpi=160)
    plt.close(fig)
    print(f"  wrote figures/{name}")


def frac_year(d: pd.Series) -> np.ndarray:
    return (d.dt.year + (d.dt.day_of_year - 1) / np.where(d.dt.is_leap_year, 366, 365)).to_numpy()


# ------------------------------------------------------------------ (a) yearly exit rate -------------------------------
def plot_a(tv: pd.DataFrame, batch_dates: pd.Series, data_dir: Path) -> None:
    g = tv.groupby("year")
    t = pd.DataFrame({
        "store_years": g.size(), "exits": g["exit_12m"].sum(),
        "strict_n": g["exit_12m_strict"].count(), "strict_exits": g["exit_12m_strict"].sum(),
    }).reset_index()
    t = as_counts(t)
    t["split"] = np.where(t["year"] <= TRAIN_END_YEAR, "train", "validation")
    t["exit_rate_pct"] = 100 * t["exits"] / t["store_years"]
    t["strict_rate_pct"] = 100 * t["strict_exits"] / t["strict_n"]
    t["batch_days"] = t["year"].map(batch_dates.dt.year.value_counts()).fillna(0).astype(int)
    t.to_csv(data_dir / "a_yearly_rates.csv", index=False)

    fig = plt.figure(figsize=(10.5, 6.3))
    gs = fig.add_gridspec(2, 1, height_ratios=[7, 1.1], hspace=0.06)
    ax, rug = fig.add_subplot(gs[0]), fig.add_subplot(gs[1], sharex=None)
    x = t["year"] + 0.5
    ax.axvspan(TRAIN_END_YEAR + 1, VAL_END_YEAR + 1, color=TINT, zorder=0)
    ax.text(2008.1, 7.55, "train", color=MUTED, fontsize=9, va="top")
    ax.text(TRAIN_END_YEAR + 1.1, 7.55, "validation", color=MUTED, fontsize=9, va="top")
    for col, color, label in (("exit_rate_pct", BLUE, "exit_12m: all true exits"), ("strict_rate_pct", ORANGE, "exit_12m_strict: batch-end exits excluded")):
        ax.plot(x, t[col], color=color, linewidth=2, marker="o", markersize=7, markeredgecolor=SURFACE, markeredgewidth=1.5, label=label, zorder=3)
    last = t.iloc[-1]
    ax.text(VAL_END_YEAR + 0.5 + 0.18, last["exit_rate_pct"], f"{last['exit_rate_pct']:.1f}%", color=INK2, va="center", fontsize=9)
    ax.text(VAL_END_YEAR + 0.5 + 0.18, last["strict_rate_pct"], f"{last['strict_rate_pct']:.1f}%", color=INK2, va="center", fontsize=9)
    ax.set_xlim(2008, 2022.45)
    ax.set_ylim(0, 7.7)
    ax.yaxis.set_major_formatter(PCT)
    ax.set_ylabel("Share of grocery store-years that exit within 12 months")
    ax.set_xticks(x)
    ax.set_xticklabels([])
    hgrid(ax)
    ax.legend(loc="upper left", bbox_to_anchor=(0.0, 0.93), fontsize=9)
    ax.spines["bottom"].set_color(AXIS)

    rug.set_xlim(ax.get_xlim())
    rug.vlines(frac_year(batch_dates), 0.15, 0.85, color=INK2, linewidth=1.6)
    rug.set_ylim(0, 1)
    rug.set_yticks([])
    rug.set_xticks(x)
    rug.set_xticklabels([str(y) for y in t["year"]], fontsize=9)
    rug.spines["left"].set_visible(False)
    rug.tick_params(length=0)
    rug.set_ylabel("batch-end\ndays", fontsize=8.5, rotation=0, ha="right", va="center", labelpad=8)
    titles(fig, "Annual exit rate of SNAP grocery stores in North Carolina, 2008-2021",
           "Stores authorized on Jan 1 that lose authorization within 12 months. Ticks mark days when 40 or more NC retailers ended on the same day.", top=0.84)
    footer(fig)
    save(fig, "a_yearly_exit_rate.png")
    print(t.round(2).to_string(index=False))


# ------------------------------------------------------------------ (b) by store type -----------------------------------
def plot_b(tv: pd.DataFrame, data_dir: Path) -> None:
    tr = tv[tv["split"] == "train"]
    g = tr.groupby("store_type")
    t = pd.DataFrame({
        "store_years": g.size(), "exits": g["exit_12m"].sum(),
        "strict_n": g["exit_12m_strict"].count(), "strict_exits": g["exit_12m_strict"].sum(),
    }).reset_index()
    t["exit_rate_pct"] = 100 * t["exits"] / t["store_years"]
    t["strict_rate_pct"] = 100 * t["strict_exits"] / t["strict_n"]
    t = as_counts(t).sort_values("exit_rate_pct", ascending=False).reset_index(drop=True)
    t.to_csv(data_dir / "b_rate_by_store_type_train.csv", index=False)

    fig, ax = plt.subplots(figsize=(10.5, 5.4))
    y = np.arange(len(t))
    h = 0.34
    ax.barh(y - h / 2 - 0.01, t["exit_rate_pct"], height=h, color=BLUE, edgecolor=SURFACE, linewidth=1.5, label="exit_12m: all true exits")
    ax.barh(y + h / 2 + 0.01, t["strict_rate_pct"], height=h, color=ORANGE, edgecolor=SURFACE, linewidth=1.5, label="exit_12m_strict: batch-end exits excluded")
    for i, r in t.iterrows():
        ax.text(r["exit_rate_pct"] + 0.25, i - h / 2 - 0.01, f"{r['exit_rate_pct']:.1f}%", va="center", fontsize=9, color=INK)
        ax.text(r["strict_rate_pct"] + 0.25, i + h / 2 + 0.01, f"{r['strict_rate_pct']:.1f}%", va="center", fontsize=9, color=INK)
    ax.set_yticks(y)
    ax.set_yticklabels([f"{r.store_type}\n{r.store_years:,} store-years · {r.exits:,} exits" for r in t.itertuples()], fontsize=9.5, linespacing=1.5)
    ax.invert_yaxis()
    ax.set_xlim(0, t["exit_rate_pct"].max() * 1.12)
    ax.xaxis.set_major_formatter(PCT)
    ax.set_xlabel("Share of store-years that exit within 12 months")
    vgrid(ax)
    ax.legend(loc="lower right", fontsize=9)
    titles(fig, "Exit rate by store type, train years 2008-2018",
           "Counts under each type are for exit_12m; strict-label counts are in figures/data/b_rate_by_store_type_train.csv.", top=0.82, left=0.27)
    footer(fig)
    save(fig, "b_exit_rate_by_store_type.png")
    print(t.round(2).to_string(index=False))


# ------------------------------------------------------------------ (c) end dates per day ------------------------------
def plot_c(ret: pd.DataFrame, data_dir: Path) -> None:
    ends = ret[ret["end_date"].notna() & (ret["end_date"] <= CUTOFF)]
    assert ends["end_date"].max() <= CUTOFF
    daily = ends.groupby("end_date").agg(ends=("record_id", "size"), batch_day=("qa_batch_end", "max")).reset_index()
    daily.to_csv(data_dir / "c_end_dates_per_day.csv", index=False)
    threshold = int(daily.loc[daily["batch_day"], "ends"].min())

    fig, ax = plt.subplots(figsize=(11, 5.6))
    other, batch = daily[~daily["batch_day"]], daily[daily["batch_day"]]
    ax.vlines(other["end_date"], 0, other["ends"], color=AXIS, linewidth=0.9)
    ax.vlines(batch["end_date"], 0, batch["ends"], color=INK, linewidth=1.8)
    ax.axhline(threshold, color=MUTED, linewidth=0.8)
    top = batch.nlargest(6, "ends")
    for r in top.itertuples():
        ax.text(r.end_date, r.ends + 5, f"{r.end_date:%b %Y}\n{r.ends}", ha="center", va="bottom", fontsize=7.5, color=INK2, linespacing=1.2)
    ax.set_ylim(0, daily["ends"].max() * 1.22)
    ax.set_xlim(pd.Timestamp("2005-01-01"), pd.Timestamp("2022-01-01"))
    ax.set_ylabel("Authorizations ending that day")
    hgrid(ax)
    ax.spines["bottom"].set_color(AXIS)
    ax.legend(handles=[Line2D([0], [0], color=INK, lw=1.8, label=f"batch-end day ({len(batch)} days, {int(batch['ends'].sum()):,} ends)"),
                       Line2D([0], [0], color=AXIS, lw=1.2, label=f"other day ({len(other):,} days, {int(other['ends'].sum()):,} ends)"),
                       Line2D([0], [0], color=MUTED, lw=0.8, label=f"batch threshold: {threshold} retailers ending the same day")],
              loc="upper left", fontsize=9)
    titles(fig, "NC SNAP authorizations ending per day, all store types, 2005-2021",
           f"A few days hold a large share of all ends: {len(batch)} batch days account for {100 * batch['ends'].sum() / daily['ends'].sum():.0f}% of the {int(daily['ends'].sum()):,} ends through 2021.", top=0.84)
    footer(fig, scope="Source: USDA FNS SNAP Retailer Locator; own calculations. End dates 2005-01-01 to 2021-12-31 only; no later end date is used.")
    save(fig, "c_end_dates_per_day.png")
    print(f"  batch days {len(batch)}, batch ends {int(batch['ends'].sum()):,} of {int(daily['ends'].sum()):,}; threshold {threshold}")


# ------------------------------------------------------------------ (d) distance by RUCA group -------------------------
def ruca_label(code: float) -> str | None:
    if pd.isna(code):
        return None
    c = int(code)
    return "Urban" if c == 1 else "Metro fringe" if c in (2, 3) else "Small town" if 4 <= c <= 9 else "Rural" if c == 10 else None


def plot_d(panel: pd.DataFrame, data_dir: Path) -> None:
    ex = panel[(panel["exit_12m"] == 1) & panel["impact_dist_nearest_other_grocery_mi"].notna()].copy()
    ex["group"] = ex["ruca_primary"].map(ruca_label)
    omitted = int(ex["group"].isna().sum())
    ex = ex.dropna(subset=["group"])
    order = [("Urban", "RUCA 1"), ("Metro fringe", "RUCA 2-3"), ("Small town", "RUCA 4-9"), ("Rural", "RUCA 10")]
    rows = []
    for name, codes in order:
        d = ex.loc[ex["group"] == name, "impact_dist_nearest_other_grocery_mi"]
        rows.append({"group": name, "ruca_codes": codes, "exits": len(d), "over_1mi": int((d > 1).sum()), "over_10mi": int((d > 10).sum()),
                     "over_1mi_pct": 100 * (d > 1).mean(), "over_10mi_pct": 100 * (d > 10).mean(), "median_mi": d.median()})
    t = pd.DataFrame(rows)
    t.to_csv(data_dir / "d_distance_by_ruca_group.csv", index=False)

    fig, axes = plt.subplots(1, 2, figsize=(11, 5.0), sharey=True, gridspec_kw={"wspace": 0.12})
    y = np.arange(len(t))
    for ax, (col, n_col, title, xmax) in zip(axes, (("over_1mi_pct", "over_1mi", "More than 1 mile to the next grocery", 78), ("over_10mi_pct", "over_10mi", "More than 10 miles to the next grocery", 24))):
        ax.barh(y, t[col], height=0.5, color=BLUE, edgecolor=SURFACE, linewidth=1.5)
        for i, r in t.iterrows():
            ax.text(r[col] + xmax * 0.012, i, f"{int(r[n_col])} of {int(r['exits'])}  ({r[col]:.1f}%)", va="center", fontsize=9, color=INK)
        ax.set_xlim(0, xmax)
        ax.xaxis.set_major_formatter(PCT)
        ax.set_title(title, fontsize=10.5, color=INK2, loc="left", pad=8)
        vgrid(ax)
    axes[0].set_yticks(y)
    axes[0].set_yticklabels([f"{r.group}\n{r.ruca_codes}, {r.exits:,} exits" for r in t.itertuples()], fontsize=9.5, linespacing=1.5)
    axes[0].invert_yaxis()
    titles(fig, "How far is the next grocery when a store exits? By urban-rural group",
           "All true exits (exit_12m = 1), train and validation years 2008-2021. Share of exits whose nearest other grocery-type store still authorized after the exit is farther than the threshold.", top=0.80)
    footer(fig, f"{omitted} exit in a zero-population (RUCA 99) tract omitted. Groups: primary RUCA code, 2010 version.")
    save(fig, "d_distance_by_ruca.png")
    print(t.round(2).to_string(index=False), f"| omitted {omitted}")


# ------------------------------------------------------------------ (e) income quintile ---------------------------------
def plot_e(tv: pd.DataFrame, data_dir: Path) -> None:
    d = tv[(tv["year"] >= 2012) & tv["median_hh_income"].notna()].copy()
    # Quintiles WITHIN each cohort year: dollars are inflation-adjusted to different vintage years, so ranks, not levels, compare across years.
    d["quintile"] = d.groupby("year")["median_hh_income"].transform(lambda s: pd.qcut(s.rank(method="first"), 5, labels=False) + 1)
    g = d.groupby("quintile")
    t = pd.DataFrame({
        "store_years": g.size(), "exits": g["exit_12m"].sum(), "strict_n": g["exit_12m_strict"].count(), "strict_exits": g["exit_12m_strict"].sum(),
        "median_income_usd": g["median_hh_income"].median(),
    }).reset_index()
    t["exit_rate_pct"] = 100 * t["exits"] / t["store_years"]
    t["strict_rate_pct"] = 100 * t["strict_exits"] / t["strict_n"]
    t = as_counts(t)
    t.to_csv(data_dir / "e_rate_by_income_quintile.csv", index=False)

    fig, ax = plt.subplots(figsize=(10.5, 5.6))
    x = np.arange(len(t))
    w = 0.36
    ax.bar(x - w / 2 - 0.01, t["exit_rate_pct"], width=w, color=BLUE, edgecolor=SURFACE, linewidth=1.5, label="exit_12m: all true exits")
    ax.bar(x + w / 2 + 0.01, t["strict_rate_pct"], width=w, color=ORANGE, edgecolor=SURFACE, linewidth=1.5, label="exit_12m_strict: batch-end exits excluded")
    for i, r in t.iterrows():
        ax.text(i - w / 2 - 0.01, r["exit_rate_pct"] + 0.1, f"{r['exit_rate_pct']:.1f}%", ha="center", fontsize=9, color=INK)
        ax.text(i + w / 2 + 0.01, r["strict_rate_pct"] + 0.1, f"{r['strict_rate_pct']:.1f}%", ha="center", fontsize=9, color=INK)
    names = ["Q1 lowest", "Q2", "Q3", "Q4", "Q5 highest"]
    ax.set_xticks(x)
    ax.set_xticklabels([f"{n}\n{r.store_years:,} store-years\n{r.exits} exits" for n, r in zip(names, t.itertuples())], fontsize=9.5, linespacing=1.5)
    ax.set_ylim(0, t["exit_rate_pct"].max() * 1.22)
    ax.yaxis.set_major_formatter(PCT)
    ax.set_ylabel("Share of store-years that exit within 12 months")
    hgrid(ax)
    ax.spines["bottom"].set_color(AXIS)
    ax.legend(loc="upper right", fontsize=9)
    titles(fig, "Exit rate by tract income quintile, 2012-2021",
           "Quintiles of tract median household income, ranked within each cohort year; ACS vintage released before Jan 1 of that year. Counts are for exit_12m.", top=0.84, bottom=0.22)
    footer(fig, "ACS 5-year tract estimates; 2008-2011 cohorts have no ACS vintage.")
    save(fig, "e_exit_rate_by_income_quintile.png")
    print(t.round(2).to_string(index=False))


def main() -> None:
    ensure_dirs()
    style()
    data_dir = FIGURES / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    tv = guard(pd.read_parquet(PROCESSED / "store_year_trainval.parquet"), "store_year_trainval")
    panel = guard(pd.read_parquet(INTERIM / "panel_trainval.parquet"), "panel_trainval")
    # The labels are 8-bit integers; 100 * count would overflow. Work in float64 (missing strict label = NaN).
    for df in (tv, panel):
        df["exit_12m"] = df["exit_12m"].astype("float64")
        df["exit_12m_strict"] = df["exit_12m_strict"].astype("float64")
    ret = pd.read_parquet(INTERIM / "retailers_nc_clean.parquet")
    ret = ret[ret["end_date"].isna() | (ret["end_date"] <= CUTOFF)]  # no end date after 2021-12-31 is ever used
    batch_dates = pd.Series(sorted(ret.loc[ret["qa_batch_end"] & (ret["end_date"] >= pd.Timestamp("2008-01-01")), "end_date"].unique()))
    print(f"Plotting {len(tv):,} train+validation store-years (years {tv['year'].min()}-{tv['year'].max()}); {len(batch_dates)} batch days in 2008-2021")
    for name, fn, args in (("a", plot_a, (tv, batch_dates, data_dir)), ("b", plot_b, (tv, data_dir)), ("c", plot_c, (ret, data_dir)),
                           ("d", plot_d, (panel, data_dir)), ("e", plot_e, (tv, data_dir))):
        print(f"\n(plot {name})")
        fn(*args)


if __name__ == "__main__":
    main()
