"""SNAP grocery store exits in North Carolina: dashboard.

Reads ONLY from Supabase, with the public (publishable / anon) key SUPABASE_KEY. The service-role key that
src/prep/06_load_supabase.py uses to write is never read here, and the app refuses to run if SUPABASE_KEY is one.
Data through 2021-12-31: train (2008-2018) and validation (2019-2021) cohorts only; the 2022-2024 test cohorts are
reserved and not in the database.

Run locally:  uv run streamlit run app/streamlit_app.py     (settings from .env; on Modal they come from a secret)
"""

import base64
import json
import os

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from supabase import create_client

try:  # local development reads .env; on Modal the environment already holds the secret
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

STORE_TYPES = ["Supermarket", "Super Store", "Large Grocery Store", "Medium Grocery Store", "Small Grocery Store"]
RUCA_ORDER = ["urban", "metro fringe", "small town", "rural"]
RUCA_LABEL = {"urban": "Urban (RUCA 1)", "metro fringe": "Metro fringe (RUCA 2-3)", "small town": "Small town (RUCA 4-9)", "rural": "Rural (RUCA 10)"}
SY_COLS = ["record_id", "year", "split", "store_type", "store_name", "county", "latitude", "longitude", "ruca_primary", "ruca_group",
           "exit_12m", "exit_12m_strict", "exit_is_batch", "impact_dist_nearest_other_grocery_mi", "qa_ownership_change_in_year"]
RET_COLS = ["end_date", "qa_batch_end", "store_type", "is_grocery", "is_convenience"]
LG_COLS = ["spell_id", "record_id", "store_name", "store_type", "county", "end_date", "end_year", "split", "is_batch", "end_kind", "gap_days", "gap_class", "reauth_same_id"]
HORIZON_DAYS = 365        # "within a year" in the re-authorization note (a parameter of the note; every share is computed)
FAR_MILES = 1             # "no other SNAP grocery within 1 mile"
GAP_RAMP = ["#86b6ef", "#3987e5", "#1c5cab", "#0d366b"]   # one blue ramp, shortest gap lightest; gray = no re-authorization seen
GAP_NONE = "#c3c2b7"
FALLBACK_DATA_THROUGH = "2021-12-31"
IMPACT_COL = "Miles to next grocery after exit"
STILL_ACTIVE = "— (still active)"
PAGE = 1000  # PostgREST returns at most 1000 rows per request
# colour = entity (same as the report figures): blue = exit_12m, orange = exit_12m_strict
BLUE, ORANGE, INK, INK2, MUTED, GRID, TINT = "#2a78d6", "#eb6834", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#f0efec"
FONT = "system-ui, -apple-system, 'Segoe UI', sans-serif"

st.set_page_config(page_title="SNAP grocery exits, NC", page_icon="\U0001f6d2", layout="wide")


# --------------------------------------------------------------------------- data access ----------------------------------
def _get_secret(key: str) -> str:
    """Read from st.secrets (Streamlit secrets file) or the environment (.env locally, Modal secret when deployed)."""
    try:
        return st.secrets[key]
    except Exception:
        pass
    value = os.environ.get(key)
    if not value:
        raise RuntimeError(f"Missing required setting: {key}")
    return value


def _assert_public_key(key: str) -> None:
    """The dashboard must only ever hold the read-only key. Refuse a secret / service-role key."""
    if key.startswith("sb_secret_"):
        raise RuntimeError("SUPABASE_KEY is a secret key. Use the publishable (anon) key in the dashboard.")
    parts = key.split(".")
    if len(parts) == 3:  # legacy JWT keys: check the role claim
        try:
            claims = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
        except Exception:
            return
        if claims.get("role") == "service_role":
            raise RuntimeError("SUPABASE_KEY is a service-role key. Use the anon key in the dashboard.")


@st.cache_resource
def _make_client(url: str, key: str):
    return create_client(url, key)


def get_client():
    key = _get_secret("SUPABASE_KEY")
    _assert_public_key(key)  # not cached: checked on every run, whatever the cache holds
    return _make_client(_get_secret("SUPABASE_URL"), key)


def fetch_all(table: str, columns: list[str], order: list[str], not_null: str | None = None) -> pd.DataFrame:
    """Every row of a table, in pages of 1000, in primary-key order."""
    rows, start = [], 0
    while True:
        q = get_client().table(table).select(",".join(columns))
        if not_null:
            q = q.not_.is_(not_null, "null")
        for col in order:
            q = q.order(col)
        page = q.range(start, start + PAGE - 1).execute().data or []
        rows += page
        if len(page) < PAGE:
            break
        start += PAGE
    return pd.DataFrame(rows, columns=columns)


@st.cache_data(ttl=3600, show_spinner="Loading store-years from Supabase...")
def load_store_year() -> pd.DataFrame:
    df = fetch_all("store_year", SY_COLS, ["record_id", "year"])
    for c in ("exit_12m", "exit_12m_strict", "latitude", "longitude", "impact_dist_nearest_other_grocery_mi", "ruca_primary", "year"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["exit_is_batch"] = df["exit_is_batch"].astype("boolean")
    return df


@st.cache_data(ttl=3600, show_spinner="Loading retailers from Supabase...")
def load_end_dates() -> pd.DataFrame:
    df = fetch_all("snap_retailers_nc", RET_COLS, ["record_id", "period_seq"], not_null="end_date")
    df["end_date"] = pd.to_datetime(df["end_date"])
    return df


@st.cache_data(ttl=3600)
def load_cleaning_log() -> pd.DataFrame:
    return fetch_all("cleaning_log", ["script", "seq", "step", "rule", "why", "rows_before", "rows_after", "rows_affected"], ["script", "seq"])


@st.cache_data(ttl=3600)
def load_meta() -> dict[str, str]:
    return {r["key"]: r["value"] for r in (get_client().table("data_meta").select("key,value").execute().data or [])}


@st.cache_data(ttl=3600, show_spinner="Loading coverage gaps from Supabase...")
def load_location_gap() -> pd.DataFrame:
    df = fetch_all("location_gap", LG_COLS, ["spell_id"])
    df["end_date"] = pd.to_datetime(df["end_date"])
    for c in ("gap_days", "end_year"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    for c in ("is_batch", "reauth_same_id"):
        df[c] = df[c].fillna(False).astype(bool)
    return df


def get_location_gap() -> tuple[pd.DataFrame | None, str | None]:
    """The coverage-gap table, or (None, reason) if it has not been created/loaded yet; the rest of the dashboard still works."""
    try:
        return load_location_gap(), None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {str(exc)[:160]}"


# --------------------------------------------------------------------------- aggregation ----------------------------------
def rates(d: pd.DataFrame, by: str) -> pd.DataFrame:
    """Exit counts and rates for both labels per group (strict rate is over rows with a strict label)."""
    g = d.groupby(by)
    t = pd.DataFrame({
        "store_years": g.size(), "exits": g["exit_12m"].sum(),
        "strict_n": g["exit_12m_strict"].count(), "strict_exits": g["exit_12m_strict"].sum(),
    }).reset_index()
    t[["exits", "strict_exits"]] = t[["exits", "strict_exits"]].astype(int)
    t["exit_rate"] = 100 * t["exits"] / t["store_years"]
    t["strict_rate"] = 100 * t["strict_exits"] / t["strict_n"].where(t["strict_n"] > 0)
    return t


def gap_classes(lg: pd.DataFrame) -> list[str]:
    """Gap classes from the shortest to the longest gap, 'no re-authorization' last. The order comes from the days in the data, not a fixed list."""
    first = lg.groupby("gap_class")["gap_days"].min()
    return sorted(first.index, key=lambda c: (pd.isna(first[c]), 0 if pd.isna(first[c]) else first[c]))


def gap_colors(lg: pd.DataFrame) -> dict[str, str]:
    first = lg.groupby("gap_class")["gap_days"].min()
    order = gap_classes(lg)
    ramp = iter(GAP_RAMP)
    return {c: (GAP_NONE if pd.isna(first[c]) else next(ramp, GAP_RAMP[-1])) for c in order}


def batch_stats(ends: pd.DataFrame) -> dict:
    """Batch days and the threshold, from the end dates in Supabase: a batch day is one flagged in the data; the threshold is the smallest daily count among them."""
    daily = ends.groupby("end_date").agg(ends=("end_date", "size"), batch=("qa_batch_end", "max")).reset_index()
    batch = daily[daily["batch"] == True]  # noqa: E712
    return {"daily": daily, "batch_days": batch, "threshold": int(batch["ends"].min()) if len(batch) else None}


def far_summary(base: pd.DataFrame) -> str:
    """Share of exits with no other SNAP grocery within FAR_MILES, Mecklenburg vs statewide, with counts (exit_12m exits that have a distance)."""
    ex = base[(base["exit_12m"] == 1) & base["impact_dist_nearest_other_grocery_mi"].notna()]
    def one(s: pd.Series) -> str:
        n, k = len(s), int((s > FAR_MILES).sum())
        return f"{k:,} of {n:,} exits ({100 * k / n:.1f}%)" if n else "no exits"
    col = "impact_dist_nearest_other_grocery_mi"
    return (f"**No other SNAP grocery within {FAR_MILES} mile of the exited store: Mecklenburg {one(ex.loc[ex['county'] == 'MECKLENBURG', col])}; "
            f"statewide {one(ex[col])}** (exit_12m exits in the selected years and store types).")


CAVEATS = ("Distance is measured from the exited store, not from where residents live. \"Next grocery\" includes small groceries (any of the five SNAP grocery store types), "
           "so a nearby small store counts as access. Straight-line distance ignores transit, driving and barriers such as highways or rivers.")


def reauth_trend(lg: pd.DataFrame, data_through: str) -> str | None:
    """Computed sentence on same-Record-ID returns within HORIZON_DAYS, for exits with a full horizon inside the data: train-year ends vs validation-year ends."""
    cut = pd.Timestamp(data_through) - pd.Timedelta(days=HORIZON_DAYS)
    e = lg[(lg["end_kind"] == "exit") & (lg["end_date"] <= cut)].copy()
    e["back"] = e["reauth_same_id"] & (e["gap_days"] <= HORIZON_DAYS)
    tr, va = e[e["split"] == "train"], e[e["split"] == "validation"]
    if tr.empty or va.empty:
        return None
    a, b = 100 * tr["back"].mean(), 100 * va["back"].mean()
    yrs = lambda s: f"{int(s['end_year'].min())}-{int(s['end_year'].max())}"  # noqa: E731
    verb = "rose" if b > a else "did not rise"
    more = "became more common" if b > a else "did not become more common"
    return (f"**Re-authorizations {more} in the later years.** Among exits with a full year of follow-up in the data, the share whose Record ID was authorized again within a year "
            f"{verb} from {a:.1f}% ({int(tr['back'].sum())} of {len(tr)}, ended {yrs(tr)}) to {b:.1f}% ({int(va['back'].sum())} of {len(va)}, ended {yrs(va)}). "
            "So an exit is more often temporary in recent years.")


def style(fig: go.Figure, height: int = 420) -> go.Figure:
    fig.update_layout(template="plotly_white", height=height, font={"family": FONT, "color": INK2}, margin={"l": 10, "r": 10, "t": 30, "b": 10},
                      legend={"orientation": "h", "y": 1.12, "x": 0}, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    fig.update_xaxes(gridcolor=GRID, zeroline=False)
    fig.update_yaxes(gridcolor=GRID, zeroline=False)
    return fig


# --------------------------------------------------------------------------- page -----------------------------------------
st.title("SNAP grocery store exits in North Carolina")
try:
    _assert_public_key(_get_secret("SUPABASE_KEY"))  # every run, before any (possibly cached) data is shown
    meta = load_meta()
    sy_all = load_store_year()
except Exception as exc:
    st.error(f"Could not load the data from Supabase: {type(exc).__name__}: {str(exc)[:300]}")
    st.info("Check that the schema (supabase/schema.sql) has been run, that `src/prep/06_load_supabase.py` has loaded the tables, "
            "and that SUPABASE_URL and SUPABASE_KEY (the publishable key) are set.")
    st.stop()

DATA_THROUGH = meta.get("data_through", FALLBACK_DATA_THROUGH)
_span = lambda split: (lambda y: f"{int(y.min())}-{int(y.max())}")(sy_all.loc[sy_all["split"] == split, "year"])  # noqa: E731
TRAIN_SPAN, VAL_SPAN = _span("train"), _span("validation")
# shown on every view: it sits above the tabs and the sidebar
st.info(f"**Data through {DATA_THROUGH}.** Train ({TRAIN_SPAN}) and validation ({VAL_SPAN}) cohorts only. {meta.get('test_set', '')} "
        "A store-year is a grocery store authorized on Jan 1 that exits (its SNAP authorization ends, ownership changes excluded) within the next 12 months.", icon="\U0001f4c5")

with st.sidebar:
    st.header("Filters")
    yr = st.slider("Cohort years", int(sy_all["year"].min()), int(sy_all["year"].max()), (int(sy_all["year"].min()), int(sy_all["year"].max())))
    types = st.multiselect("Store types", STORE_TYPES, default=STORE_TYPES)
    area = st.radio("Area", ["All NC", "Mecklenburg County", "Rest of NC"])
    st.caption(f"Data through {DATA_THROUGH}")

d = sy_all[sy_all["year"].between(*yr) & sy_all["store_type"].isin(types)]
if area == "Mecklenburg County":
    d = d[d["county"] == "MECKLENBURG"]
elif area == "Rest of NC":
    d = d[d["county"] != "MECKLENBURG"]
if d.empty:
    st.warning("No store-years match these filters.")
    st.stop()

tab_map, tab_trend, tab_impact, tab_gap, tab_quality = st.tabs(["Map", "Exit rates", "Impact by urban-rural group", "SNAP coverage gaps", "Data quality"])
# the filters of the sidebar except the area, for the Mecklenburg-vs-statewide captions
base_all = sy_all[sy_all["year"].between(*yr) & sy_all["store_type"].isin(types)]

# --------------------------------------------------------------------------- map ------------------------------------------
with tab_map:
    lg_all, lg_err = get_location_gap()
    ends_all = load_end_dates()
    bs = batch_stats(ends_all)
    n_exits_all, n_own_all = int(sy_all["exit_12m"].sum()), int(sy_all["qa_ownership_change_in_year"].fillna(False).astype(bool).sum())
    n_batch_exits = int((sy_all["exit_is_batch"] == True).sum())  # noqa: E712
    with st.expander("About this data"):
        st.markdown(
            "**What an exit means.** An exit is a grocery store whose SNAP authorization ended (USDA stopped authorizing it). That is not necessarily a closure: "
            "a store can lose authorization over paperwork, be re-registered under a new ID, or be authorized again later.\n\n"
            f"**Data through {DATA_THROUGH}.** {meta.get('test_set', '')}\n\n"
            f"**Ownership changes and re-registrations are not exits.** {meta.get('ownership_rule', '')} "
            f"In these data {n_own_all:,} store-years ended as an ownership change or re-registration, against {n_exits_all:,} exits.\n\n"
            + (f"**Batch deauthorizations.** On {len(bs['batch_days']):,} days at least {bs['threshold']} NC retailers lost authorization at once, which looks like an administrative action "
               f"rather than store decisions; {n_batch_exits:,} of the {n_exits_all:,} exits ({100 * n_batch_exits / max(n_exits_all, 1):.0f}%) ended on such a day. "
               "The strict label leaves them out.\n\n" if bs["threshold"] else "")
            + ((reauth_trend(lg_all, DATA_THROUGH) or "") if lg_all is not None else "*The re-authorization trend appears once the coverage-gap table is loaded.*"))
    c1, c2 = st.columns([2, 1])
    year = c1.select_slider("Cohort year", options=sorted(d["year"].unique()), value=int(d["year"].max()))
    label = c2.radio("Label", ["exit_12m: all true exits", "exit_12m_strict: batch-end exits excluded"], horizontal=False)
    strict = label.startswith("exit_12m_strict")
    col = "exit_12m_strict" if strict else "exit_12m"
    m = d[(d["year"] == year) & d[col].notna() & d["latitude"].notna()].copy()
    m["status"] = m[col].map({0: "Stayed authorized", 1: "Exited within 12 months"})
    m["size"] = m[col].map({0: 4, 1: 9})
    m["impact"] = m["impact_dist_nearest_other_grocery_mi"].round(2)
    # The distance is measured only for stores that exit, so an active store has none. Say that instead of showing a null.
    m[IMPACT_COL] = m["impact"].map(lambda v: f"{v:.2f}" if pd.notna(v) else None)
    m.loc[m[col] == 0, IMPACT_COL] = STILL_ACTIVE
    m.loc[(m[col] == 1) & m["impact"].isna(), IMPACT_COL] = "— (not available)"
    n_missing = int(((m[col] == 1) & m["impact"].isna()).sum())
    if n_missing:
        st.warning(f"{n_missing} exited store(s) have no distance in the database.")
    n_exit = int(m[col].sum())
    k1, k2, k3 = st.columns(3)
    k1.metric("Stores authorized on Jan 1", f"{len(m):,}")
    k2.metric("Exited within 12 months", f"{n_exit:,}")
    k3.metric("Exit rate", f"{100 * n_exit / len(m):.1f}%" if len(m) else "n/a")
    if strict:
        st.caption("Strict label: stores whose exit was an administrative batch end are left off the map.")
    charlotte = area == "Mecklenburg County"
    exit_color = ORANGE if strict else BLUE
    fig = px.scatter_map(
        m.sort_values(col), lat="latitude", lon="longitude", color="status", size="size", size_max=9,
        color_discrete_map={"Stayed authorized": "#9a9890", "Exited within 12 months": exit_color},
        category_orders={"status": ["Stayed authorized", "Exited within 12 months"]},
        hover_name="store_name", hover_data={"store_type": True, "county": True, IMPACT_COL: True, "status": False, "size": False, "latitude": False, "longitude": False},
        labels={"store_type": "Type", "county": "County"},
        center={"lat": 35.23, "lon": -80.84} if charlotte else {"lat": 35.6, "lon": -79.4}, zoom=10.2 if charlotte else 6.0,
        map_style="carto-positron", height=620,
    )
    fig.update_layout(margin={"l": 0, "r": 0, "t": 0, "b": 0}, legend={"orientation": "h", "y": 0.01, "x": 0.01, "bgcolor": "rgba(255,255,255,0.8)"})
    st.plotly_chart(fig, width="stretch")
    st.caption(f"Each dot is a grocery-type store authorized on Jan 1, {year}; larger dots exited by Dec 31. "
               f"\"{IMPACT_COL}\" is the distance from an exited store to the nearest other grocery still authorized after the exit; "
               f"stores that stayed show \"{STILL_ACTIVE}\" because there is no exit to measure. "
               "Use the Area filter for the Charlotte-Mecklenburg view. Data through " + DATA_THROUGH + ".")
    st.markdown(far_summary(base_all) + " " + CAVEATS)
    with st.expander("Table view of the map"):
        tbl = (m.sort_values([col, "impact"], ascending=[False, False])[["store_name", "store_type", "county", "status", "impact"]]
                .rename(columns={"impact": IMPACT_COL}))
        # numbers stay numeric (sorting works); the placeholder is display-only
        st.dataframe(tbl.style.format({IMPACT_COL: "{:.2f}"}, na_rep=STILL_ACTIVE), hide_index=True, width="stretch")

# --------------------------------------------------------------------------- exit rates -----------------------------------
with tab_trend:
    by_year = rates(d, "year")
    fig = go.Figure()
    _tr_end, _va_end = int(sy_all.loc[sy_all["split"] == "train", "year"].max()), int(sy_all.loc[sy_all["split"] == "validation", "year"].max())
    fig.add_vrect(x0=_tr_end + 0.5, x1=_va_end + 0.5, fillcolor=TINT, line_width=0, layer="below", annotation_text="validation", annotation_position="top left")
    for name, col_, color, n_col, e_col in (("exit_12m: all true exits", "exit_rate", BLUE, "store_years", "exits"),
                                            ("exit_12m_strict: batch-end exits excluded", "strict_rate", ORANGE, "strict_n", "strict_exits")):
        fig.add_trace(go.Scatter(x=by_year["year"], y=by_year[col_], mode="lines+markers", name=name, line={"color": color, "width": 2.5},
                                 marker={"size": 8, "line": {"color": "white", "width": 1.5}}, customdata=by_year[[e_col, n_col]],
                                 hovertemplate="%{x}: %{y:.1f}%<br>%{customdata[0]} exits of %{customdata[1]:,} store-years<extra></extra>"))
    fig.update_yaxes(title="Share exiting within 12 months", ticksuffix="%", rangemode="tozero")
    fig.update_xaxes(dtick=1, title=None)
    st.subheader("Exit rate by year")
    st.plotly_chart(style(fig), width="stretch")

    by_type = rates(d, "store_type").sort_values("exit_rate", ascending=False)
    fig2 = go.Figure()
    ylab = [f"{r.store_type}<br><sub>{r.store_years:,} store-years, {r.exits:,} exits</sub>" for r in by_type.itertuples()]
    for name, col_, color, n_col, e_col in (("exit_12m: all true exits", "exit_rate", BLUE, "store_years", "exits"),
                                            ("exit_12m_strict: batch-end exits excluded", "strict_rate", ORANGE, "strict_n", "strict_exits")):
        fig2.add_trace(go.Bar(y=ylab, x=by_type[col_], orientation="h", name=name, marker={"color": color}, text=by_type[col_].round(1).astype(str) + "%",
                              textposition="outside", customdata=by_type[[e_col, n_col]],
                              hovertemplate="%{x:.1f}%<br>%{customdata[0]} exits of %{customdata[1]:,}<extra></extra>"))
    fig2.update_layout(barmode="group", bargap=0.35)
    fig2.update_yaxes(autorange="reversed")
    fig2.update_xaxes(ticksuffix="%", title="Share exiting within 12 months")
    st.subheader("Exit rate by store type")
    st.plotly_chart(style(fig2, 460), width="stretch")
    if len(d) < 300:
        st.warning(f"Only {len(d):,} store-years match these filters, so rates are imprecise.")
    with st.expander("Table view"):
        st.dataframe(by_year.round(2), hide_index=True, width="stretch")
        st.dataframe(by_type.round(2), hide_index=True, width="stretch")

# --------------------------------------------------------------------------- impact ----------------------------------------
with tab_impact:
    st.subheader("How far is the next grocery when a store exits?")
    st.caption("Miles from the exiting store to the nearest other grocery-type store still authorized after the exit date. "
               "Urban-rural groups come from USDA RUCA codes (metro fringe = codes 2-3, commuting-linked tracts).")
    ex = d[(d["exit_12m"] == 1) & d["impact_dist_nearest_other_grocery_mi"].notna() & d["ruca_group"].isin(RUCA_ORDER)]
    if ex.empty:
        st.warning("No exits match these filters.")
    else:
        rows = []
        for grp in RUCA_ORDER:
            for name, sub in (("exit_12m: all true exits", ex), ("exit_12m_strict: batch-end exits excluded", ex[ex["exit_12m_strict"] == 1])):
                dist = sub.loc[sub["ruca_group"] == grp, "impact_dist_nearest_other_grocery_mi"]
                if len(dist):
                    rows.append({"group": RUCA_LABEL[grp], "label": name, "exits": len(dist), "over_1": int((dist > 1).sum()), "over_10": int((dist > 10).sum()),
                                 "pct_1": 100 * (dist > 1).mean(), "pct_10": 100 * (dist > 10).mean(), "median_mi": dist.median()})
        t = pd.DataFrame(rows)
        left, right = st.columns(2)
        for panel, (pct, n, title) in zip((left, right), (("pct_1", "over_1", "More than 1 mile to the next grocery"), ("pct_10", "over_10", "More than 10 miles to the next grocery"))):
            fig = go.Figure()
            for name, color in (("exit_12m: all true exits", BLUE), ("exit_12m_strict: batch-end exits excluded", ORANGE)):
                s = t[t["label"] == name]
                fig.add_trace(go.Bar(y=s["group"], x=s[pct], orientation="h", name=name, marker={"color": color}, customdata=s[[n, "exits"]],
                                     text=s.apply(lambda r: f"{int(r[n])} of {int(r['exits'])}", axis=1), textposition="outside",
                                     hovertemplate="%{x:.1f}%  (%{customdata[0]} of %{customdata[1]} exits)<extra></extra>"))
            fig.update_layout(barmode="group", bargap=0.35, title={"text": title, "font": {"size": 14}})
            fig.update_yaxes(autorange="reversed", categoryorder="array", categoryarray=[RUCA_LABEL[g] for g in RUCA_ORDER])
            fig.update_xaxes(ticksuffix="%", rangemode="tozero")
            panel.plotly_chart(style(fig, 400), width="stretch")
        with st.expander("Table view"):
            st.dataframe(t.rename(columns={"over_1": "exits > 1 mi", "over_10": "exits > 10 mi", "pct_1": "% > 1 mi", "pct_10": "% > 10 mi", "median_mi": "median miles"}).round(2),
                         hide_index=True, width="stretch")
        st.caption("Small groups (rural, metro fringe) have few exits, so their percentages are imprecise; hover for the counts.")
    st.markdown(far_summary(base_all) + " " + CAVEATS)

# --------------------------------------------------------------------------- coverage gaps -------------------------------------
with tab_gap:
    st.subheader("SNAP coverage gaps at store locations")
    st.caption("For every grocery-type record that ended, how long its location (street address) went without ANY SNAP authorization, under any Record ID or store type, "
               f"until the next one started. Data through {DATA_THROUGH}; nothing later is used.")
    lg, lg_error = get_location_gap()
    if lg is None:
        st.info("The coverage-gap table is not available yet. Run the updated `supabase/schema.sql` in the Supabase SQL editor, then "
                "`uv run python src/prep/06_load_supabase.py --tables location_gap`.")
        st.caption(f"Reason: {lg_error}")
    else:
        f1, f2, f3 = st.columns([2, 2, 1.4])
        counties = sorted(lg["county"].dropna().unique())
        chosen_counties = f1.multiselect("County", counties, default=[], placeholder="All counties")
        type_opts = [t for t in STORE_TYPES if t in set(lg["store_type"])]
        chosen_types = f2.multiselect("Store type", type_opts, default=type_opts)
        split_by = f3.selectbox("Split by", ["Nothing", "Store type", "Batch vs non-batch end", "Exit vs ownership change", "Train vs validation years"])
        g = lg[lg["store_type"].isin(chosen_types)]
        if chosen_counties:
            g = g[g["county"].isin(chosen_counties)]
        classes, colors = gap_classes(lg), gap_colors(lg)         # order and colours come from the whole table, so a filter never repaints a class
        if g.empty:
            st.warning("No ended grocery records match these filters.")
        else:
            key = {"Nothing": None, "Store type": "store_type", "Batch vs non-batch end": "_batch", "Exit vs ownership change": "end_kind", "Train vs validation years": "split"}[split_by]
            g = g.assign(_batch=np.where(g["is_batch"], "batch-end", "non-batch end"), _all="All selected")
            grp = key or "_all"
            order = sorted(g[grp].unique())
            rows = []
            for name in order:
                s = g[g[grp] == name]
                rows.append({"group": name, "n": len(s), **{c: 100 * (s["gap_class"] == c).mean() for c in classes}})
            dist = pd.DataFrame(rows)
            first, last = classes[0], classes[-1]
            overall = {c: 100 * (g["gap_class"] == c).mean() for c in classes}
            m1, m2, m3 = st.columns(3)
            m1.metric("Ended grocery records", f"{len(g):,}")
            m2.metric(f"Location never uncovered ({first})", f"{overall[first]:.0f}%")
            m3.metric(f"No new authorization seen ({last})", f"{overall[last]:.0f}%")
            fig = go.Figure()
            for c in classes:
                fig.add_trace(go.Bar(y=[f"{r.group} (n={r.n:,})" for r in dist.itertuples()], x=dist[c], orientation="h", name=c, marker={"color": colors[c]},
                                     text=[f"{v:.0f}%" if v >= 7 else "" for v in dist[c]], textposition="inside", insidetextanchor="middle",
                                     textfont={"color": "#0b0b0b" if colors[c] in (GAP_NONE, GAP_RAMP[0]) else "white"},
                                     hovertemplate="%{y}<br>" + c + ": %{x:.1f}%<extra></extra>"))
            fig.update_layout(barmode="stack", bargap=0.3)
            fig.update_yaxes(autorange="reversed")
            fig.update_xaxes(ticksuffix="%", range=[0, 100], title="Share of ended grocery-type records")
            st.plotly_chart(style(fig, 200 + 55 * len(dist)), width="stretch")
            with st.expander("How to read this"):
                st.markdown(
                    f"- **{first}** (the lightest): the address was never left without SNAP: another authorization was already in force when the record ended or started that day (a new owner, or a co-tenant), so that end did not uncover the address.\n"
                    "- The **middle classes** are gaps: the address went without SNAP for that many days before another authorization started, under any Record ID.\n"
                    f"- **{last}** (gray): no authorization started at the address by {DATA_THROUGH}. This includes addresses that had not yet had time to come back, so recent ends look worse than they will turn out to be.\n"
                    "- A location is a street address, not a building footprint: a plaza address with several tenants stays covered while one of them leaves.\n"
                    "- It counts records that ended, whatever the reason (exits and ownership changes); use *Split by* to separate them.")
            with st.expander("Table view"):
                st.dataframe(dist.round(1), hide_index=True, width="stretch")

# --------------------------------------------------------------------------- data quality ---------------------------------
with tab_quality:
    st.subheader("Cleaning log")
    st.caption("Every cleaning rule with row counts before and after (rows are authorization periods unless a step says otherwise).")
    log = load_cleaning_log()
    script = st.selectbox("Script", ["all"] + sorted(log["script"].unique()))
    view = log if script == "all" else log[log["script"] == script]
    st.dataframe(view, hide_index=True, width="stretch", column_config={"rule": st.column_config.TextColumn(width="large"), "why": st.column_config.TextColumn(width="large")})

    st.subheader("Batch-end days")
    ends = load_end_dates()
    daily = ends.groupby("end_date").agg(ends=("end_date", "size"), batch=("qa_batch_end", "max")).reset_index()
    batch_days = daily[daily["batch"] == True]  # noqa: E712
    threshold = int(batch_days["ends"].min()) if len(batch_days) else None
    c1, c2, c3 = st.columns(3)
    c1.metric(f"Authorizations ended (through {DATA_THROUGH})", f"{len(ends):,}")
    c2.metric("Batch-end days", f"{len(batch_days):,}")
    c3.metric("Share of all ends on batch days", f"{100 * batch_days['ends'].sum() / len(ends):.0f}%" if len(ends) else "n/a")
    fig = go.Figure()
    other = daily[daily["batch"] != True]  # noqa: E712
    fig.add_trace(go.Bar(x=other["end_date"], y=other["ends"], name="other day", marker={"color": "#c3c2b7"}, hovertemplate="%{x|%Y-%m-%d}: %{y} ends<extra></extra>"))
    fig.add_trace(go.Bar(x=batch_days["end_date"], y=batch_days["ends"], name="batch-end day", marker={"color": INK}, hovertemplate="%{x|%Y-%m-%d}: %{y} ends<extra></extra>"))
    if threshold:
        fig.add_hline(y=threshold, line={"color": MUTED, "width": 1}, annotation_text=f"batch threshold: {threshold} ends on one day", annotation_position="top left")
    fig.update_yaxes(title="Authorizations ending that day")
    fig.update_layout(barmode="overlay", bargap=0)
    st.plotly_chart(style(fig, 380), width="stretch")
    st.caption(f"All store types, statewide. A day is a batch day when {threshold} or more NC retailers ended on it (flagged in the data from the daily counts through {DATA_THROUGH}); "
               "such days look like administrative actions by USDA rather than store decisions. "
               "The primary label includes them; the strict label leaves them out." if threshold else "No batch days in the data.")
    mix = ends[ends["qa_batch_end"] == True].assign(  # noqa: E712
        grocery=lambda x: x["is_grocery"] == True, convenience=lambda x: x["is_convenience"] == True)  # noqa: E712
    table = mix.groupby("end_date").agg(total=("end_date", "size"), grocery=("grocery", "sum"), convenience=("convenience", "sum")).reset_index()
    table["other"] = table["total"] - table["grocery"] - table["convenience"]
    table["end_date"] = table["end_date"].dt.strftime("%Y-%m-%d")
    with st.expander("Batch days and their store-type mix"):
        st.dataframe(table.sort_values("end_date"), hide_index=True, width="stretch")
