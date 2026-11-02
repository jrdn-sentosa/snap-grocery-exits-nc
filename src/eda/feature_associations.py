"""Univariate feature associations with exit_12m, TRAINING rows 2012-2018 only.

Reads : data/processed/store_year_trainval.parquet (filtered to split == 'train' and year >= 2012 at once;
        validation rows are dropped before anything is computed, and the test file is never opened)
Writes: docs/feature_associations.md, docs/feature_associations_groups.csv

For every model feature (the `feature` role in docs/data_dictionary.md): exit_12m rate and row count by quintile
(numeric) or by category, and the rate ratio between the highest-rate-end groups (highest group / lowest group: Q5 / Q1, or the last/first group when ties give fewer quintiles;
for categories, the group with the highest rate / the lowest rate among groups with >= MIN_N rows).
The five numeric features with the largest ratio are then repeated within store-type groups, with quintile
cut points recomputed inside each group so that store type is held fixed.
These are descriptive associations on training data: not causal, not model results.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "prep"))
from common import DOCS, PROCESSED, TRAIN_END_YEAR, ensure_dirs  # noqa: E402

FIRST_YEAR = 2012  # first cohort with ACS features; the same rows the D3 baseline and models will use
MIN_N = 30  # smaller groups are shown but not used as the top/bottom group (a ratio from a handful of rows is noise)
MAX_CATS = 6  # numeric columns with at most this many distinct values are treated as categories, not quintiled
STRATA = {
    "small/medium grocery": ["Small Grocery Store", "Medium Grocery Store"],
    "supermarket/super/large": ["Supermarket", "Super Store", "Large Grocery Store"],
}
# `feature` role in docs/data_dictionary.md; calendar year and every qa_/impact_/exit_/bias_ column are excluded
FEATURES = [
    "store_type", "store_age_years", "auth_date_placeholder", "n_prior_spells_same_id", "n_prior_ownership_changes",
    "chain_size", "n_grocery_05mi", "n_grocery_1mi", "n_convenience_1mi", "convenience_to_grocery_ratio_1mi",
    "n_grocery_ends_1mi_prior12m", "acs_population", "pop_density_sqmi", "pct_poverty", "median_hh_income",
    "pct_no_vehicle", "pct_snap_hh", "pct_renter", "pct_age_65_plus", "unemployment_rate",
]


def num(v: float) -> str:
    return f"{v:,.0f}" if abs(v) >= 1000 else f"{v:.3g}"


def groups(df: pd.DataFrame, col: str) -> pd.DataFrame:
    """Rate and count per group, ordered low to high on the feature (categories: as listed)."""
    x = df[col]
    kind = "category"
    if x.dtype == bool or x.dtype == object or x.dropna().nunique() <= MAX_CATS:
        key = x.astype("object").where(x.notna())
    else:
        xf = x.astype(float)
        # ties are kept together (duplicates dropped), so heavily tied counts give fewer than five groups
        q = pd.qcut(xf, 5, duplicates="drop", labels=False)
        if q.dropna().nunique() >= 3:
            kind, key = "quintile", q
        else:
            # one value holds most rows (e.g. 80% of small-store chain_size is 1): use the values themselves,
            # pooling the sparse top into "cap+" so that every group is large enough to compare
            xs = xf.dropna()
            cap = min(v for v in xs.unique() if (xs >= v).mean() <= 0.05)
            key = xf.clip(upper=cap)
    g = df.groupby(key, observed=True)["exit_12m"].agg(n="size", exits="sum").reset_index(names="group")
    g["rate"] = g["exits"] / g["n"]
    g["kind"] = kind
    if kind == "quintile":
        # label each quintile by the feature values it actually holds
        span = x.astype(float).groupby(key, observed=True).agg(["min", "max"])
        g["group"] = [f"Q{int(k) + 1}: {num(span.loc[k, 'min'])} to {num(span.loc[k, 'max'])}" for k in g["group"]]
    elif x.dtype != bool and x.dtype != object and x.dropna().nunique() > MAX_CATS:
        top = g["group"].max()
        g["group"] = [f"{v:g}+" if v == top else f"{v:g}" for v in g["group"]]
    else:
        g["group"] = g["group"].astype(str)
    return g


def ratio(g: pd.DataFrame) -> tuple[pd.Series, pd.Series, float]:
    """(bottom group, top group, rate ratio). Quintile: Q5 / Q1. Category: highest rate / lowest rate, n >= MIN_N."""
    if g["kind"].iloc[0] == "quintile":
        lo, hi = g.iloc[0], g.iloc[-1]
    else:
        ok = g[g["n"] >= MIN_N]
        if len(ok) < 2:
            return g.iloc[0], g.iloc[-1], np.nan
        lo, hi = ok.loc[ok["rate"].idxmin()], ok.loc[ok["rate"].idxmax()]
    return lo, hi, (hi["rate"] / lo["rate"] if lo["rate"] > 0 else np.inf)


def fmt_rr(r: float) -> str:
    return "n/a" if np.isnan(r) else ("inf (bottom has 0 exits)" if np.isinf(r) else f"{r:.2f}")


# Written from the table this script produced on the 2012-2018 training rows; re-read it if the data or labels change.
SUMMARY = """Store type is by far the strongest single association (small grocery stores exit at 15.8% against 1.6% for supermarkets, a 9.7x ratio), followed by `chain_size` (stores sharing a name with 497 or more NC retailers exit at 0.7%, against 7.9% for names shared by 12 or fewer; the ratio is 0.08), `store_age_years` (newest quintile 9.2%, oldest 2.5%) and the tract measures of disadvantage (`pct_poverty`, `pct_snap_hh`, `pct_no_vehicle`, `unemployment_rate`, low `median_hh_income`: roughly 1.8x to 2.5x between the extreme quintiles), plus `n_convenience_1mi` (2.2x). Holding store type fixed shrinks most of these: the tract poverty and SNAP-household ratios fall to 0.94 and 1.14 among small and medium grocery stores (they stay at 1.64 and 1.54 among supermarkets, super stores and large groceries, where exits are rare and each quintile has only a few dozen exits), `store_age_years` weakens from 0.27 to 0.65 and 0.77, and `chain_size` reverses sign among small and medium stores (1.70) while keeping its direction among large formats (0.31), so its overall association largely reflects that chains are mostly large formats. Only `n_convenience_1mi` (1.30 and 1.91) and, weakly, `pct_snap_hh` (1.14 and 1.54) stay above 1 in both groups. `pop_density_sqmi` has no association (1.01). These are univariate associations on training rows only (2012-2018), not causal effects and not model results: features are correlated with each other and with store type, group sizes in the stratified columns are small, and `unemployment_rate` is missing for the whole 2012 cohort."""


def main() -> None:
    ensure_dirs()
    tv = pd.read_parquet(PROCESSED / "store_year_trainval.parquet")
    df = tv[(tv["split"] == "train") & (tv["year"].between(FIRST_YEAR, TRAIN_END_YEAR))].copy()
    del tv  # validation rows are never used here
    assert df["year"].max() <= TRAIN_END_YEAR and set(df["split"]) == {"train"}
    n_rows, n_exit = len(df), int(df["exit_12m"].sum())
    print(f"train {FIRST_YEAR}-{TRAIN_END_YEAR}: {n_rows:,} store-years, {n_exit} exits")

    detail, summary = [], []
    for col in FEATURES:
        g = groups(df, col)
        detail.append(g.assign(feature=col, scope="all"))
        lo, hi, rr = ratio(g)
        summary.append({"feature": col, "kind": g["kind"].iloc[0], "lo": lo, "hi": hi, "rr": rr,
                        "n_missing": int(df[col].isna().sum()), "log_rr": abs(np.log(rr)) if np.isfinite(rr) and rr > 0 else -1})
    s = pd.DataFrame(summary)

    # top 5 numeric features by distance of the rate ratio from 1; store_type is the stratifier, so it is not repeated
    cand = s[(s["feature"] != "store_type") & np.isfinite(s["rr"])].sort_values("log_rr", ascending=False)
    top5 = cand["feature"].head(5).tolist()
    strat = {}
    for name, types in STRATA.items():
        sub = df[df["store_type"].isin(types)]
        for col in top5:
            g = groups(sub, col)
            detail.append(g.assign(feature=col, scope=name))
            strat[(col, name)] = (len(sub), int(sub["exit_12m"].sum()), *ratio(g))
    pd.concat(detail).to_csv(DOCS / "feature_associations_groups.csv", index=False)

    # ----- the one table -----
    def cell(grp: pd.Series) -> str:
        return f"{grp['group']}: {100 * grp['rate']:.1f}% (n={int(grp['n']):,})"

    head = ["feature", "bottom group: rate (n)", "top group: rate (n)", "rate ratio top/bottom"] + [f"RR within {n}" for n in STRATA]
    rows = []
    for _, r in s.sort_values("log_rr", ascending=False).iterrows():
        row = [("**" if r["feature"] in top5 else "") + r["feature"] + ("**" if r["feature"] in top5 else ""),
               cell(r["lo"]), cell(r["hi"]), fmt_rr(r["rr"])]
        for name in STRATA:
            if (r["feature"], name) in strat:
                _, _, lo, hi, rr = strat[(r["feature"], name)]
                row.append(f"{fmt_rr(rr)} ({100 * lo['rate']:.1f}% to {100 * hi['rate']:.1f}%)")
            else:
                row.append("")
        rows.append(row)
    table = "\n".join(["| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|"] +
                      ["| " + " | ".join(r) + " |" for r in rows])
    sizes = "; ".join(f"{n}: {strat[(top5[0], n)][0]:,} store-years, {strat[(top5[0], n)][1]} exits" for n in STRATA)
    miss = ", ".join(f"`{r['feature']}` {r['n_missing']:,}" for _, r in s.iterrows() if r["n_missing"])

    out = f"""# Feature associations with exit_12m (training rows 2012-2018)

Generated by `src/eda/feature_associations.py`; do not edit by hand. Rows: {n_rows:,} train store-years from cohorts {FIRST_YEAR}-{TRAIN_END_YEAR}
with {n_exit} `exit_12m` exits (primary label, batch ends included). Validation and test rows are not used.

Numeric features are cut into quintiles of the feature (ties kept together, so heavily tied counts give fewer than five groups; a feature with at most {MAX_CATS} distinct values is treated as categories). The rate ratio compares the top and bottom quintile; for categories,
the highest-rate and lowest-rate group with at least {MIN_N} rows. Bold features are the five numeric features with the largest ratio; for those, the last two columns repeat the
calculation inside each store-type group with the quintile cut points recomputed within the group ({sizes}). Rates and counts for every quintile
are in `feature_associations_groups.csv`. Rows missing the feature are left out of that feature's groups ({miss}).

{table}

{SUMMARY}
"""
    (DOCS / "feature_associations.md").write_text(out, encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
