"""Exit proximity review: how close is the next grocery when a store exits, and is it the same store?

REPORT ONLY. TRAIN and VALIDATION exits only (cohort years 2008-2021), under the CURRENT labels (the ownership-change rule of
03_spells.py, which already removes re-registered stores; see docs/label_rule_change.md for the change).

Reads : data/interim/panel_trainval.parquet, spells.parquet, periods_spells.parquet, retailers_nc_clean.parquet
Writes: docs/exit_proximity_report.md
        figures/f_exit_nearest_grocery_distance.png
        figures/data/f_exit_neighbor_classes.csv

  1. distribution of the distance from an exit to the nearest other grocery still authorized after it (0-0.5 mi)
  2. exits with another grocery within 0.15 mi, classified: same store (similar name or identical address incl. unit), a different
     store in the same plaza (same street, clearly different name), or unclear, with 15 examples

Test-set discipline: only train/validation exits are examined (asserted); no end date after 2021-12-31 is printed.
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
from common import DOCS, FIGURES, INTERIM, VAL_END_YEAR, ensure_dirs  # noqa: E402
from matching import NAME_SIM, RADIUS_MI, name_sim  # noqa: E402

CRS_GEO, CRS_PROJ, M_PER_MI = "EPSG:4269", "EPSG:32119", 1609.344
PLAZA_MAX_SIM = 0.60     # a different store: clearly different name
SURFACE, INK, INK2, MUTED, GRID, AXIS = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
BLUE, ORANGE = "#2a78d6", "#eb6834"


def street_core(core: str | None) -> str | None:
    """Street name of an address_core ('1816 GALLERIA' -> 'GALLERIA'), for the same-street test."""
    return core.split(" ", 1)[1] if isinstance(core, str) and " " in core else None


def unit_of(v) -> str | None:
    return v if isinstance(v, str) and v else None


def project(lat, lon):
    g = gpd.GeoSeries(gpd.points_from_xy(lon, lat), crs=CRS_GEO).to_crs(CRS_PROJ)
    return g.x.to_numpy(), g.y.to_numpy()


def md(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    lines += ["| " + " | ".join(str(v) for v in r) + " |" for r in df.itertuples(index=False)]
    return "\n".join(lines)


def main() -> None:
    ensure_dirs()
    panel = pd.read_parquet(INTERIM / "panel_trainval.parquet")
    assert panel["year"].max() <= VAL_END_YEAR and not panel["split"].eq("test").any()
    per = pd.read_parquet(INTERIM / "periods_spells.parquet")
    ret = pd.read_parquet(INTERIM / "retailers_nc_clean.parquet")[["record_id", "period_seq", "address_core", "unit_std"]]
    per = per.merge(ret, on=["record_id", "period_seq"], how="left")
    last = per.sort_values("period_seq").groupby("spell_id").last()

    ex = panel[panel["exit_12m"] == 1].copy().reset_index(drop=True)
    lp = last.loc[ex["spell_id"]]
    ex["end"] = pd.to_datetime(ex["qa_spell_end"])
    ex["name_std"] = lp["name_std"].to_numpy()
    ex["exit_name"] = lp["store_name"].to_numpy()
    ex["addr"] = [k.split("|")[0] if isinstance(k, str) else None for k in lp["address_key"]]
    ex["core"], ex["unit"] = lp["address_core"].to_numpy(), lp["unit_std"].to_numpy()
    ex["street"] = ex["core"].map(street_core)
    ex["ex_x"], ex["ex_y"] = project(ex["latitude"], ex["longitude"])

    per = per[per["latitude"].notna()].reset_index(drop=True)
    per["addr"] = [k.split("|")[0] if isinstance(k, str) else None for k in per["address_key"]]
    per["street"] = per["address_core"].map(street_core)
    px, py = project(per["latitude"], per["longitude"])
    far_past, far_future = pd.Timestamp("1900-01-01"), pd.Timestamp("2200-01-01")
    start_a, end_a = per["auth_date"].fillna(far_past).to_numpy(), per["end_date"].fillna(far_future).to_numpy()
    is_g, rec = per["is_grocery"].to_numpy(), per["record_id"].to_numpy()

    nearest, classes, best = np.full(len(ex), np.nan), [], []
    for k, e in ex.iterrows():
        d = np.datetime64(e["end"])
        idx = np.where(is_g & (rec != e["record_id"]) & (start_a <= d) & (end_a > d))[0]
        dist = np.hypot(px[idx] - e["ex_x"], py[idx] - e["ex_y"]) / M_PER_MI
        if len(idx):
            nearest[k] = dist.min()
        near = [(j, dj) for j, dj in zip(idx, dist) if dj <= RADIUS_MI]
        rows = []
        for j, dj in near:
            n = per.iloc[j]
            same_addr = bool(isinstance(e["core"], str) and n["address_core"] == e["core"] and unit_of(n["unit_std"]) == unit_of(e["unit"]))
            rows.append(dict(j=j, dist=dj, same_addr=same_addr, sim=name_sim(e["name_std"], n["name_std"]),
                             same_street=bool(e["street"] and n["street"] and e["street"] == n["street"])))
        if not rows:
            classes.append("none within 0.15 mi")
            best.append(None)
            continue
        r = pd.DataFrame(rows)
        same = r[(r["sim"] >= NAME_SIM) | r["same_addr"]]
        plaza = r[r["same_street"] & (r["sim"] < PLAZA_MAX_SIM) & ~r["same_addr"]]
        if len(same):
            classes.append("same store")
            best.append(same.sort_values(["same_addr", "sim", "dist"], ascending=[False, False, True]).iloc[0])
        elif len(plaza):
            classes.append("different store, same plaza")
            best.append(plaza.sort_values("dist").iloc[0])
        else:
            classes.append("unclear")
            best.append(r.sort_values("dist").iloc[0])
    ex["nearest_mi"], ex["class"] = nearest, classes
    assert np.nanmax(np.abs(ex["nearest_mi"] - ex["impact_dist_nearest_other_grocery_mi"])) < 1e-6, "recomputed distances differ from the panel"
    for col in ("nb_name", "nb_addr", "nb_start", "nb_dist", "nb_sim", "nb_same_addr"):
        ex[col] = None
    for k, b in enumerate(best):
        if b is not None:
            n = per.iloc[int(b["j"])]
            ex.loc[k, ["nb_name", "nb_addr", "nb_start", "nb_dist", "nb_sim", "nb_same_addr"]] = [n["store_name"], n["addr"], n["auth_date"], b["dist"], b["sim"], b["same_addr"]]
    ex["nb_start_vs_end_days"] = (pd.to_datetime(ex["nb_start"]) - ex["end"]).dt.days
    n_ex = len(ex)

    # ---- histogram 0-0.5 mi, coloured by class for exits whose nearest grocery is within 0.15 mi
    within = ex[ex["nearest_mi"] <= 0.5]
    edges = np.arange(0, 0.5001, 0.01)
    cls_order = [("same store", BLUE), ("different store, same plaza", ORANGE), ("unclear", MUTED), ("none within 0.15 mi", AXIS)]
    plt.rcParams.update({"font.family": "Segoe UI", "axes.facecolor": SURFACE, "figure.facecolor": SURFACE, "axes.edgecolor": AXIS,
                         "axes.spines.top": False, "axes.spines.right": False, "axes.spines.left": False})
    fig, ax = plt.subplots(figsize=(11, 5.6))
    bottom = np.zeros(len(edges) - 1)
    for cname, color in cls_order:
        h, _ = np.histogram(within.loc[within["class"] == cname, "nearest_mi"], bins=edges)
        ax.bar(edges[:-1], h, width=0.0092, align="edge", bottom=bottom, color=color, edgecolor=SURFACE, linewidth=0.6, label=f"{cname} ({int(h.sum())})")
        bottom += h
    ax.axhline(0, color=AXIS, linewidth=0.8)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(length=0, colors=INK2)
    ax.set_xlabel("Miles from the exit to the nearest other grocery still authorized after it (0.01-mile bins)", color=INK2)
    ax.set_ylabel("Exits", color=INK2)
    ax.set_xlim(0, 0.5)
    ax.legend(loc="upper right", frameon=False, fontsize=9)
    fig.text(0.012, 0.965, "Distance from an exit to the nearest other grocery, exits within 0.5 mile", fontsize=13.5, fontweight="bold", ha="left", va="top", color=INK)
    fig.text(0.012, 0.905, f"{len(within):,} of {n_ex:,} train and validation exits (2008-2021), under the current ownership-change rule. Colours classify exits whose nearest grocery is within 0.15 mile.",
             fontsize=9.5, ha="left", va="top", color=INK2)
    fig.subplots_adjust(top=0.82, bottom=0.14)
    fig.text(0.012, 0.012, "Source: USDA FNS SNAP Retailer Locator; own calculations. Train 2008-2018 and validation 2019-2021 exits only.", fontsize=7.5, color=MUTED)
    fig.savefig(FIGURES / "f_exit_nearest_grocery_distance.png", dpi=160, facecolor=SURFACE)
    plt.close(fig)
    h_all, _ = np.histogram(ex["nearest_mi"].dropna(), bins=edges)

    # ---- tables
    within15 = int((ex["nearest_mi"] <= RADIUS_MI).sum())
    spike = ex[ex["nearest_mi"] < 0.01]["class"].value_counts()
    ss = ex[ex["class"] == "same store"].copy()
    ss["match"] = np.where(ss["nb_sim"].astype(float) >= NAME_SIM, "similar name", "identical address+unit only")
    off = pd.to_numeric(ss["nb_start_vs_end_days"], errors="coerce")
    ss["neighbour started"] = pd.cut(off, [-np.inf, -366, -181, 0], labels=["more than 1 year before the exit", "181-365 days before", "within 180 days before"]).astype(object)
    ss["neighbour started"] = ss["neighbour started"].where(off.notna(), "start date unknown")
    rng = np.random.default_rng(20261028)
    pieces = [ex[ex["class"] == c].sample(min(5, int((ex["class"] == c).sum())), random_state=int(rng.integers(1e6))) for c in ("same store", "different store, same plaza", "unclear")]
    exs = pd.concat(pieces)
    show = pd.DataFrame({
        "class": exs["class"], "exit store": exs["exit_name"], "exit address": exs["addr"], "exit end": exs["end"].dt.strftime("%Y-%m-%d"),
        "nearest grocery": exs["nb_name"], "its address": exs["nb_addr"], "miles": exs["nb_dist"].astype(float).round(3),
        "name sim": exs["nb_sim"].astype(float).round(2), "same address+unit": exs["nb_same_addr"], "its start vs exit end (days)": exs["nb_start_vs_end_days"]})
    ex[["record_id", "year", "exit_name", "end", "addr", "unit", "nearest_mi", "class", "nb_name", "nb_addr", "nb_dist", "nb_sim", "nb_same_addr", "nb_start_vs_end_days"]].to_csv(
        FIGURES / "data" / "f_exit_neighbor_classes.csv", index=False)

    sp = pd.read_parquet(INTERIM / "spells.parquet")
    eg = sp[sp["record_id"] == 740603]
    eg_text = ""
    if len(eg) and bool(eg.iloc[0]["ownership_change"]):
        e0 = eg.iloc[0]
        eg_text = (f"Earth Fare 120 (Record ID 740603) is **no longer an exit**: it is an ownership change to Record ID {int(e0['successor_record_id'])} "
                   f"(basis: {e0['successor_basis']}, name similarity {e0['successor_name_sim']:.2f}, {e0['successor_distance_mi']:.3f} mile away, authorized {int(-e0['successor_gap_days'])} days before the end).")

    out = [
        "# Exit proximity review (report only)", "",
        "Generated by `src/eda/exit_proximity.py`; do not edit by hand. Train and validation exits only (2008-2021); "
        f"{n_ex:,} exits under the current labels (ownership-change rule of `03_spells.py`, see `docs/label_rule_change.md`).", "",
        "## 1. Distance to the nearest other grocery at exit, 0-0.5 mile", "",
        "![distance](../figures/f_exit_nearest_grocery_distance.png)", "",
        f"{len(within):,} of {n_ex:,} exits ({100 * len(within) / n_ex:.0f}%) have a grocery within 0.5 mile; {within15:,} ({100 * within15 / n_ex:.0f}%) within 0.15 mile. "
        f"The first ten 0.01-mile bins hold {', '.join(str(int(v)) for v in h_all[:10])} exits; the average bin from 0.20 to 0.50 mile holds {h_all[20:50].mean():.1f}. "
        f"The 0.00-0.01 bin alone holds {int(h_all[0])} exits; by class: " + ", ".join(f"{k}: {v}" for k, v in spike.items()) + ".", "",
        "## 2. Exits with another grocery within 0.15 mile", "",
        f"Neighbour = another grocery store still authorized on the exit date (the definition behind `impact_dist_nearest_other_grocery_mi`; recomputed here and checked equal to the panel). "
        f"**Same store** = a neighbour with a similar name (cleaned-name similarity >= {NAME_SIM}) or the identical standardized street address including the unit; "
        f"**different store, same plaza** = no such neighbour, but one on the same street with a clearly different name (similarity < {PLAZA_MAX_SIM}); **unclear** = the rest.", "",
        md(ex["class"].value_counts().rename_axis("class").reset_index(name="exits")), "",
        "Fifteen examples, five per group (random, seeded):", "", md(show), "",
        "The 'same store' class by how long before the exit the matching neighbour started (a neighbour that started long before cannot be a successor):", "",
        md(pd.crosstab(ss["neighbour started"], ss["match"]).reset_index()), "",
        eg_text, "",
    ]
    (DOCS / "exit_proximity_report.md").write_text("\n".join(out), encoding="utf-8")
    print(f"Wrote {DOCS / 'exit_proximity_report.md'}")


if __name__ == "__main__":
    main()
