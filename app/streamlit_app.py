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
import plotly.io as pio
import streamlit as st
from supabase import create_client

try:  # local development reads .env; on Modal the environment already holds the secret
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

STORE_TYPES = ["Supermarket", "Super Store", "Large Grocery Store", "Medium Grocery Store", "Small Grocery Store"]
RUCA_ORDER = ["urban", "metro fringe", "small town", "rural"]
RUCA_LABEL = {"urban": "Urban", "metro fringe": "Metro fringe", "small town": "Small town", "rural": "Rural"}   # RUCA codes appear only in footnotes
SY_COLS = ["record_id", "year", "split", "store_type", "store_name", "county", "latitude", "longitude", "ruca_primary", "ruca_group",
           "exit_12m", "exit_12m_strict", "exit_is_batch", "impact_dist_nearest_other_grocery_mi", "qa_ownership_change_in_year"]
RET_COLS = ["end_date", "qa_batch_end", "store_type", "is_grocery", "is_convenience"]
LG_COLS = ["spell_id", "record_id", "store_name", "store_type", "county", "end_date", "end_year", "split", "is_batch", "end_kind", "gap_days", "gap_class", "reauth_same_id"]
HORIZON_DAYS = 365        # "within a year" in the re-authorization note (a parameter of the note; every share is computed)
FAR_MILES = 1             # "no other SNAP grocery within 1 mile"
GAP_RAMP = ["#a9ddd0", "#4fb59e", "#1d8a77", "#0b5447"]   # one teal ramp, shortest gap lightest (teal, so it is never read as the "exits" blue); gray = no re-authorization seen
GAP_NAMES = {"0 days": "Never uncovered (0 days)", "1-90 days": "1–90 days", "91-365 days": "91–365 days", "more than 365 days": "More than a year",
             "not re-authorized by 2021-12-31": "No new authorization by 2021-12-31"}   # plain-English names for the gap classes stored in the database
GAP_NONE = "#c3c2b7"
FALLBACK_DATA_THROUGH = "2021-12-31"
IMPACT_COL = "Miles to next grocery after exit"
STILL_ACTIVE = "— (still active)"
PAGE = 1000  # PostgREST returns at most 1000 rows per request
# colour = entity, the same on every tab: dark blue = all SNAP exits, a lighter shade of the same blue = excluding batch deauthorizations
# (the database columns are exit_12m and exit_12m_strict; those names never appear on screen)
ALL_LABEL, STRICT_LABEL = "All SNAP exits", "Excluding batch deauthorizations"
BLUE, LIGHT_BLUE, INK, INK2, MUTED, GRID, AXIS, TINT = "#2a78d6", "#8fbcf0", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7", "#f0efec"
SMALL_N = 50              # groups with fewer exits than this get a "small sample" footnote
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


@st.cache_data(ttl=3600, show_spinner="Loading stores from Supabase...")
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
            f"statewide {one(ex[col])}** (all SNAP exits in the selected years and store types).")


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
    return (f"**Re-authorizations {more} in the later years.** Among exits with a full year of follow-up in the data, the share that were authorized again under the same ID within a year "
            f"{verb} from {a:.1f}% ({int(tr['back'].sum())} of {len(tr)}, ended {yrs(tr)}) to {b:.1f}% ({int(va['back'].sum())} of {len(va)}, ended {yrs(va)}). "
            "So an exit is more often temporary in recent years.")




# --------------------------------------------------------------------------- shared look -------------------------------------
# One Plotly template for every chart: transparent background, no gridlines between categories (each chart turns on the light
# gridlines of its value axis only), a horizontal legend pinned to the BOTTOM of the figure and the title pinned to the TOP, so they
# can never overlap. The same blue always means "all SNAP exits"; the lighter blue is "excluding batch deauthorizations".
pio.templates["snap"] = go.layout.Template(layout={
    "font": {"family": FONT, "color": INK2, "size": 13},
    "colorway": [BLUE, LIGHT_BLUE, "#898781"],
    "paper_bgcolor": "rgba(0,0,0,0)", "plot_bgcolor": "rgba(0,0,0,0)",
    "title": {"x": 0, "xanchor": "left", "xref": "container", "y": 1, "yanchor": "top", "yref": "container", "pad": {"t": 6, "l": 4}, "font": {"size": 17, "color": INK}},
    "legend": {"traceorder": "normal", "orientation": "h", "x": 0, "xanchor": "left", "y": 0, "yanchor": "bottom", "yref": "container", "font": {"size": 12}, "title": {"text": ""}},
    "xaxis": {"showgrid": False, "zeroline": False, "linecolor": AXIS, "tickfont": {"size": 12}},
    "yaxis": {"showgrid": False, "zeroline": False, "linecolor": AXIS, "tickfont": {"size": 12}},
    "hoverlabel": {"font": {"family": FONT, "size": 13}},
})
TEMPLATE = "plotly_white+snap"


def finish(fig: go.Figure, title: str, subtitle: str, height: int = 420, value_axis: str = "y", bottom: int = 64) -> go.Figure:
    """Title + one-line subtitle above the chart (see show), legend below it, light gridlines on the value axis only."""
    fig.update_layout(template=TEMPLATE, height=height, margin={"l": 10, "r": 24, "t": 10, "b": bottom}, meta={"title": title, "subtitle": subtitle})
    (fig.update_yaxes if value_axis == "y" else fig.update_xaxes)(showgrid=True, gridcolor=GRID, gridwidth=1)
    return fig


def show(fig: go.Figure) -> None:
    """The chart's title and subtitle are page text (they wrap on a narrow screen); the legend sits inside the figure, below the plot."""
    meta_ = fig.layout.meta or {}
    if meta_.get("title"):
        st.markdown(f"**{meta_['title']}**")
        st.caption(meta_["subtitle"])
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})


def rate_axis(fig: go.Figure, top: float, axis: str = "x") -> None:
    """Percent axis with room to the right of the longest bar for its label ('13.7% (91 of 662)'), so a label is never clipped."""
    hi = max(top * 1.7, 6.0)
    step = 2 if hi <= 12 else 5 if hi <= 30 else 10 if hi <= 60 else 20
    ticks = [float(v) for v in np.arange(0, min(hi, 100) + 0.001, step)]
    (fig.update_xaxes if axis == "x" else fig.update_yaxes)(range=[0, hi], tickvals=ticks, ticktext=[f"{v:.0f}%" for v in ticks], automargin=True)


def share_label(rate: float, k: int, n: int, small: bool) -> str:
    """'13.7% (91 of 662)'; a star marks a group with fewer than SMALL_N exits (the caller says which count that is)."""
    if not n or pd.isna(rate):
        return ""
    return f"{rate:.1f}% ({k:,} of {n:,}){'*' if small else ''}"


def table(df: pd.DataFrame, config: dict, order: list[str], height: int | None = None) -> None:
    """A plain-English table: no index, chosen columns in order, sensible height."""
    st.dataframe(df, hide_index=True, width="stretch", column_config=config, column_order=order, height=height or int(min(40 + 35 * len(df), 420)))


def n_col(label: str, fmt: str = "localized", **kw) -> st.column_config.NumberColumn:
    return st.column_config.NumberColumn(label, format=fmt, **kw)


def pct_col(label: str, **kw) -> st.column_config.NumberColumn:
    return st.column_config.NumberColumn(label, format="%.1f%%", **kw)


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
TEST_NOTE = "The most recent years are held back for testing and are not shown."
_span = lambda split: (lambda y: f"{int(y.min())}-{int(y.max())}")(sy_all.loc[sy_all["split"] == split, "year"])  # noqa: E731
TRAIN_SPAN, VAL_SPAN = _span("train"), _span("validation")
# shown on every view, small: it sits above the tabs
st.caption(f"\U0001f4c5 Data through {DATA_THROUGH} \u00b7 covers {TRAIN_SPAN} and {VAL_SPAN} \u00b7 {TEST_NOTE}")

with st.sidebar:
    st.header("Filters")
    yr = st.slider("Years (January 1 of each year)", int(sy_all["year"].min()), int(sy_all["year"].max()), (int(sy_all["year"].min()), int(sy_all["year"].max())))
    types = st.multiselect("Store types", STORE_TYPES, default=STORE_TYPES)
    area = st.radio("Area", ["All NC", "Mecklenburg County", "Rest of NC"])
    st.caption(f"Data through {DATA_THROUGH}")

d = sy_all[sy_all["year"].between(*yr) & sy_all["store_type"].isin(types)]
if area == "Mecklenburg County":
    d = d[d["county"] == "MECKLENBURG"]
elif area == "Rest of NC":
    d = d[d["county"] != "MECKLENBURG"]
if d.empty:
    st.warning("No stores match these filters.")
    st.stop()
YEARS = f"{yr[0]}–{yr[1]}" if yr[0] != yr[1] else str(yr[0])
WHERE = {"All NC": "North Carolina", "Mecklenburg County": "Mecklenburg County", "Rest of NC": "North Carolina outside Mecklenburg"}[area]

tab_map, tab_trend, tab_impact, tab_gap, tab_quality = st.tabs(["Map", "Exit rates", "Distance to next grocery", "SNAP coverage gaps", "Data quality"])
# the filters of the sidebar except the area, for the Mecklenburg-vs-statewide captions
base_all = sy_all[sy_all["year"].between(*yr) & sy_all["store_type"].isin(types)]

# --------------------------------------------------------------------------- map ------------------------------------------
with tab_map:
    st.markdown("**Each dot is a grocery store with SNAP authorization on January 1 of the chosen year; the larger dots lost that authorization within 12 months.** "
                "Hover over a dot for the store and the distance to the next grocery.")
    lg_all, lg_err = get_location_gap()
    ends_all = load_end_dates()
    bs = batch_stats(ends_all)
    n_exits_all, n_own_all = int(sy_all["exit_12m"].sum()), int(sy_all["qa_ownership_change_in_year"].fillna(False).astype(bool).sum())
    n_batch_exits = int((sy_all["exit_is_batch"] == True).sum())  # noqa: E712
    with st.expander("About this data"):
        st.markdown(
            "**What an exit means.** An exit is a grocery store whose SNAP authorization ended (USDA stopped authorizing it). That is not necessarily a closure: "
            "a store can lose authorization over paperwork, be re-registered under a new ID, or be authorized again later.\n\n"
            f"**Data through {DATA_THROUGH}.** {TEST_NOTE} Nothing after that date is used anywhere on this page.\n\n"
            f"**Ownership changes and re-registrations are not exits.** {meta.get('ownership_rule', '')} "
            f"In these data {n_own_all:,} store-years ended as an ownership change or re-registration, against {n_exits_all:,} exits.\n\n"
            + (f"**Batch deauthorizations.** On {len(bs['batch_days']):,} days at least {bs['threshold']} NC retailers lost authorization at once, which looks like an administrative action "
               f"rather than store decisions; {n_batch_exits:,} of the {n_exits_all:,} exits ({100 * n_batch_exits / max(n_exits_all, 1):.0f}%) ended on such a day. "
               f"\"{STRICT_LABEL}\" leaves them out.\n\n" if bs["threshold"] else "")
            + ((reauth_trend(lg_all, DATA_THROUGH) or "") if lg_all is not None else "*The re-authorization trend appears once the coverage-gap table is loaded.*"))
    c1, c2 = st.columns([2, 1])
    year = c1.select_slider("Year (January 1)", options=sorted(d["year"].unique()), value=int(d["year"].max()))
    label = c2.radio("Which exits", [ALL_LABEL, STRICT_LABEL], horizontal=False)
    strict = label == STRICT_LABEL
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
    gone = m.loc[m[col] == 1, "impact"].dropna()
    n_far = int((gone > FAR_MILES).sum())
    k1, k2, k3, k4 = st.columns(4)
    k1.metric(f"Stores authorized on Jan 1, {year}", f"{len(m):,}")
    k2.metric("Exits within 12 months", f"{n_exit:,}", help=f"{label}. An exit is a store whose SNAP authorization ended and was not taken over by another owner.")
    k3.metric("Exit rate", f"{100 * n_exit / len(m):.1f}%" if len(m) else "n/a", delta=f"{n_exit:,} of {len(m):,} stores", delta_color="off", delta_arrow="off")
    k4.metric(f"Exits with no grocery within {FAR_MILES} mile", f"{100 * n_far / len(gone):.1f}%" if len(gone) else "n/a",
              delta=f"{n_far:,} of {len(gone):,} exits" if len(gone) else None, delta_color="off", delta_arrow="off",
              help="Share of this year's exits where the nearest other SNAP grocery was more than 1 mile away.")
    charlotte = area == "Mecklenburg County"
    exit_color = LIGHT_BLUE if strict else BLUE
    fig = px.scatter_map(
        m.sort_values(col), lat="latitude", lon="longitude", color="status", size="size", size_max=9,
        color_discrete_map={"Stayed authorized": "#9a9890", "Exited within 12 months": exit_color},
        category_orders={"status": ["Stayed authorized", "Exited within 12 months"]},
        hover_name="store_name", hover_data={"store_type": True, "county": True, IMPACT_COL: True, "status": False, "size": False, "latitude": False, "longitude": False},
        labels={"store_type": "Type", "county": "County"},
        center={"lat": 35.23, "lon": -80.84} if charlotte else {"lat": 35.6, "lon": -79.4}, zoom=10.2 if charlotte else 6.0,
        map_style="carto-positron",
    )
    finish(fig, f"SNAP grocery stores in {WHERE}, January 1, {year}",
           f"{len(m):,} stores; {n_exit:,} lost SNAP authorization within 12 months ({label})", height=640, bottom=56)
    fig.update_layout(margin={"l": 0, "r": 0, "t": 0, "b": 56}, legend_title_text="")
    show(fig)
    st.caption(f"\"{IMPACT_COL}\" is the distance from an exited store to the nearest other grocery still authorized after the exit; "
               f"stores that stayed show \"{STILL_ACTIVE}\" because there is no exit to measure. Use the Area filter for the Charlotte-Mecklenburg view."
               + (" Stores whose exit was a batch deauthorization are left off this map." if strict else ""))
    st.markdown(far_summary(base_all) + " " + CAVEATS)
    with st.expander("Table view of the map"):
        tbl = (m.sort_values([col, "impact"], ascending=[False, False])[["store_name", "store_type", "county", "status", "impact"]]
                .rename(columns={"impact": IMPACT_COL}))
        # numbers stay numeric (sorting works); the placeholder is display-only
        st.dataframe(tbl.style.format({IMPACT_COL: "{:.2f}"}, na_rep=STILL_ACTIVE), hide_index=True, width="stretch", height=int(min(40 + 35 * len(tbl), 420)),
                     column_order=["store_name", "store_type", "county", "status", IMPACT_COL],
                     column_config={"store_name": st.column_config.TextColumn("Store", width="medium"), "store_type": st.column_config.TextColumn("Store type"),
                                    "county": st.column_config.TextColumn("County"), "status": st.column_config.TextColumn("Status"),
                                    IMPACT_COL: st.column_config.NumberColumn(IMPACT_COL, help="Blank or '— (still active)': the store did not exit, so there is nothing to measure.")})

# --------------------------------------------------------------------------- exit rates -----------------------------------
with tab_trend:
    st.markdown("**These charts show what share of SNAP grocery stores lost authorization within 12 months of January 1.** "
                "A higher point or a longer bar means more of the stores exited; the darker blue counts every exit, the lighter blue leaves out batch deauthorizations.")
    SERIES = ((ALL_LABEL, "exit_rate", BLUE, "store_years", "exits"), (STRICT_LABEL, "strict_rate", LIGHT_BLUE, "strict_n", "strict_exits"))
    by_year = rates(d, "year")
    fig = go.Figure()
    _tr_end, _va_end = int(sy_all.loc[sy_all["split"] == "train", "year"].max()), int(sy_all.loc[sy_all["split"] == "validation", "year"].max())
    fig.add_vrect(x0=_tr_end + 0.5, x1=_va_end + 0.5, fillcolor=TINT, line_width=0, layer="below", annotation_text=f"later years ({VAL_SPAN})", annotation_position="top left",
                  annotation_font={"size": 11, "color": MUTED})
    for name, col_, color, nc, ec in SERIES:
        fig.add_trace(go.Scatter(x=by_year["year"], y=by_year[col_], mode="lines+markers", name=name, line={"color": color, "width": 2.5},
                                 marker={"size": 8, "line": {"color": "white", "width": 1.5}}, customdata=by_year[[ec, nc]],
                                 hovertemplate="%{x}: %{y:.1f}% (%{customdata[0]} of %{customdata[1]:,} stores)<extra>" + name + "</extra>"))
    rate_axis(fig, float(np.nanmax(by_year[["exit_rate", "strict_rate"]].to_numpy())) / 1.7 * 1.25, axis="y")
    _years = sorted(by_year["year"].astype(int))
    fig.update_xaxes(tickvals=_years[::-1][::2][::-1], range=[_years[0] - 0.5, _years[-1] + 0.5], title=None)
    finish(fig, "Share of grocery stores that lost SNAP authorization, by year",
           f"Percent of stores authorized on January 1 that exited within 12 months, {YEARS}, {WHERE}", height=440, value_axis="y")
    show(fig)
    small_years = [str(int(r.year)) for r in by_year.itertuples() if r.exits < SMALL_N]
    if small_years:
        st.caption(f"Years with fewer than {SMALL_N} exits: {', '.join(small_years)}. Small sample; interpret with caution.")

    by_type = rates(d, "store_type").sort_values("exit_rate", ascending=False)
    fig2 = go.Figure()
    for name, col_, color, nc, ec in SERIES:
        fig2.add_trace(go.Bar(y=by_type["store_type"], x=by_type[col_], orientation="h", name=name, marker={"color": color},
                              text=[share_label(r, k, n, k < SMALL_N) for r, k, n in zip(by_type[col_], by_type[ec], by_type[nc])], textposition="outside", cliponaxis=False,
                              textfont={"size": 12, "color": INK2}, customdata=by_type[[ec, nc]],
                              hovertemplate="%{y}: %{x:.1f}% (%{customdata[0]} of %{customdata[1]:,} stores)<extra>" + name + "</extra>"))
    fig2.update_layout(barmode="group", bargap=0.3, bargroupgap=0.05)
    fig2.update_yaxes(autorange="reversed")
    rate_axis(fig2, float(np.nanmax(by_type[["exit_rate", "strict_rate"]].to_numpy())), axis="x")
    finish(fig2, "Share of grocery stores that lost SNAP authorization, by store type",
           f"Percent of stores authorized on January 1 that exited within 12 months, {YEARS}, {WHERE}", height=480, value_axis="x")
    show(fig2)
    if (by_type["exits"] < SMALL_N).any() or (by_type["strict_exits"] < SMALL_N).any():
        st.caption(f"\\* Fewer than {SMALL_N} exits. Small sample; interpret with caution.")
    if len(d) < 300:
        st.warning(f"Only {len(d):,} stores match these filters, so rates are imprecise.")
    with st.expander("Table view"):
        table(by_year.sort_values("year"), {"year": n_col("Year", "%d"), "store_years": n_col("Stores on Jan 1"), "exits": n_col(ALL_LABEL), "exit_rate": pct_col("Exit rate"),
                                            "strict_exits": n_col("Exits excl. batch"), "strict_rate": pct_col("Rate excl. batch")},
              ["year", "store_years", "exits", "exit_rate", "strict_exits", "strict_rate"])
        table(by_type.sort_values("exits", ascending=False), {"store_type": st.column_config.TextColumn("Store type"), "store_years": n_col("Stores on Jan 1"), "exits": n_col(ALL_LABEL),
                                                              "exit_rate": pct_col("Exit rate"), "strict_exits": n_col("Exits excl. batch"), "strict_rate": pct_col("Rate excl. batch")},
              ["store_type", "store_years", "exits", "exit_rate", "strict_exits", "strict_rate"])

# --------------------------------------------------------------------------- impact ----------------------------------------
with tab_impact:
    st.markdown("**When a SNAP grocery store exits, how far away is the next one?** Each bar is the share of exits in an area type where the nearest other SNAP grocery "
                "was farther than the distance in the chart title; a longer bar means more exits left a bigger hole.")
    ex = d[(d["exit_12m"] == 1) & d["impact_dist_nearest_other_grocery_mi"].notna() & d["ruca_group"].isin(RUCA_ORDER)]
    if ex.empty:
        st.warning("No exits match these filters.")
    else:
        rows = []
        for grp in RUCA_ORDER:
            for name, sub in ((ALL_LABEL, ex), (STRICT_LABEL, ex[ex["exit_12m_strict"] == 1])):
                dist = sub.loc[sub["ruca_group"] == grp, "impact_dist_nearest_other_grocery_mi"]
                if len(dist):
                    rows.append({"group": RUCA_LABEL[grp], "label": name, "exits": len(dist), "over_1": int((dist > 1).sum()), "over_10": int((dist > 10).sum()),
                                 "pct_1": 100 * (dist > 1).mean(), "pct_10": 100 * (dist > 10).mean(), "median_mi": dist.median()})
        t = pd.DataFrame(rows)
        for pct, n, miles in (("pct_1", "over_1", 1), ("pct_10", "over_10", 10)):
            fig = go.Figure()
            for name, color in ((ALL_LABEL, BLUE), (STRICT_LABEL, LIGHT_BLUE)):
                s = t[t["label"] == name]
                fig.add_trace(go.Bar(y=s["group"], x=s[pct], orientation="h", name=name, marker={"color": color}, customdata=s[[n, "exits"]],
                                     text=[share_label(p, int(k), int(e), e < SMALL_N) for p, k, e in zip(s[pct], s[n], s["exits"])], textposition="outside", cliponaxis=False,
                                     textfont={"size": 12, "color": INK2},
                                     hovertemplate="%{y}: %{x:.1f}% (%{customdata[0]} of %{customdata[1]} exits)<extra>" + name + "</extra>"))
            fig.update_layout(barmode="group", bargap=0.3, bargroupgap=0.05)
            fig.update_yaxes(autorange="reversed", categoryorder="array", categoryarray=[RUCA_LABEL[g] for g in RUCA_ORDER])
            rate_axis(fig, float(t[pct].max()), axis="x")
            finish(fig, f"Exits with no other SNAP grocery within {miles} mile{'s' if miles > 1 else ''}",
                   f"Percent of exits by area type, {YEARS}, {WHERE}; distance from the exited store", height=420, value_axis="x")
            show(fig)
        st.caption("Area types come from USDA's Rural-Urban Commuting Area (RUCA) codes: urban = code 1, metro fringe = codes 2–3 (areas linked to a city by commuting), "
                   "small town = codes 4–9, rural = code 10. \\* Fewer than 50 exits. Small sample; interpret with caution.")
        with st.expander("Table view"):
            tt = t.assign(sort=t["group"].map({RUCA_LABEL[g]: i for i, g in enumerate(RUCA_ORDER)})).sort_values(["sort", "label"])
            table(tt, {"group": st.column_config.TextColumn("Area type"), "label": st.column_config.TextColumn("Which exits"), "exits": n_col("Exits"),
                       "over_1": n_col("Exits > 1 mile"), "pct_1": pct_col("% > 1 mile"), "over_10": n_col("Exits > 10 miles"), "pct_10": pct_col("% > 10 miles"),
                       "median_mi": st.column_config.NumberColumn("Median miles", format="%.2f")},
                  ["group", "label", "exits", "over_1", "pct_1", "over_10", "pct_10", "median_mi"])
    st.markdown(far_summary(base_all) + " " + CAVEATS)

# --------------------------------------------------------------------------- coverage gaps -------------------------------------
with tab_gap:
    st.markdown("**When a grocery store's SNAP record ended, how long did its address go without any SNAP authorization?** "
                "Each bar splits the ended records by the length of that gap; the wider the dark and gray parts, the longer the address stayed without SNAP.")
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
        split_by = f3.selectbox("Split by", ["Nothing", "Store type", "Batch vs non-batch end", "Exit vs ownership change", "Earlier vs later years"])
        g = lg[lg["store_type"].isin(chosen_types)]
        if chosen_counties:
            g = g[g["county"].isin(chosen_counties)]
        classes, colors = gap_classes(lg), gap_colors(lg)         # order and colours come from the whole table, so a filter never repaints a class
        if g.empty:
            st.warning("No ended grocery records match these filters.")
        else:
            key = {"Nothing": None, "Store type": "store_type", "Batch vs non-batch end": "_batch", "Exit vs ownership change": "end_kind", "Earlier vs later years": "split"}[split_by]
            g = g.assign(_batch=np.where(g["is_batch"], "Batch deauthorization", "Other end"), _all="All selected records",
                         end_kind=g["end_kind"].map({"exit": "Exit", "ownership change": "Ownership change"}).fillna(g["end_kind"]),
                         split=g["split"].map({"train": f"Ended {TRAIN_SPAN}", "validation": f"Ended {VAL_SPAN}"}))
            grp = key or "_all"
            order = sorted(g[grp].unique(), key=lambda v: (STORE_TYPES.index(v) if v in STORE_TYPES else 0, str(v)))
            rows = []
            for name in order:
                s = g[g[grp] == name]
                rows.append({"group": name, "n": len(s), **{c: 100 * (s["gap_class"] == c).mean() for c in classes}})
            dist = pd.DataFrame(rows)
            first, last = classes[0], classes[-1]
            overall = {c: 100 * (g["gap_class"] == c).mean() for c in classes}
            m1, m2, m3 = st.columns(3)
            m1.metric("Ended grocery records", f"{len(g):,}")
            m2.metric("Never uncovered", f"{overall[first]:.0f}%", help="Share of ended records whose address was never left without SNAP: another authorization was already in force there when the record ended.")
            m3.metric("No new authorization", f"{overall[last]:.0f}%", help=f"Share of ended records whose address had no new SNAP authorization by {DATA_THROUGH}. Includes addresses that had not yet had time to come back.")
            fig = go.Figure()
            ycats = [f"{r.group}{'*' if r.n < SMALL_N else ''} (n={r.n:,})" for r in dist.itertuples()]
            for c in classes:
                fig.add_trace(go.Bar(y=ycats, x=dist[c], orientation="h", name=GAP_NAMES.get(c, c), marker={"color": colors[c], "line": {"color": "white", "width": 1}},
                                     text=[f"{v:.0f}%" if v >= 7 else "" for v in dist[c]], textposition="inside", insidetextanchor="middle",
                                     textfont={"size": 12, "color": "#0b0b0b" if colors[c] in (GAP_NONE, GAP_RAMP[0]) else "white"},
                                     hovertemplate="%{y}<br>" + GAP_NAMES.get(c, c) + ": %{x:.1f}%<extra></extra>"))
            fig.update_layout(barmode="stack", bargap=0.3)
            fig.update_yaxes(autorange="reversed")
            fig.update_xaxes(range=[0, 100], tickvals=[0, 20, 40, 60, 80, 100], ticktext=[f"{v}%" for v in (0, 20, 40, 60, 80, 100)])
            finish(fig, "How long a store's address stayed without SNAP after its record ended",
                   f"Percent of ended grocery records by length of the gap, {int(g['end_year'].min())}–{int(g['end_year'].max())}, "
                   + ("selected counties" if chosen_counties else "all NC counties"), height=210 + 52 * len(dist), value_axis="x", bottom=96)
            show(fig)
            if (dist["n"] < SMALL_N).any():
                st.caption(f"\\* Fewer than {SMALL_N} ended records. Small sample; interpret with caution.")
            with st.expander("How to read this"):
                st.markdown(
                    f"- **{GAP_NAMES.get(first, first)}** (the lightest): the address was never left without SNAP: another authorization was already in force when the record ended or started that day (a new owner, or a co-tenant), so that end did not uncover the address.\n"
                    "- The **middle colors** are gaps: the address went without SNAP for that many days before another authorization started, under any Record ID.\n"
                    f"- **{GAP_NAMES.get(last, last)}** (gray): no authorization started at the address by {DATA_THROUGH}. This includes addresses that had not yet had time to come back, so recent ends look worse than they will turn out to be.\n"
                    "- A location is a street address, not a building footprint: a plaza address with several tenants stays covered while one of them leaves.\n"
                    "- It counts records that ended, whatever the reason (exits and ownership changes); use *Split by* to separate them.")
            with st.expander("Table view"):
                cfg = {"group": st.column_config.TextColumn("Group"), "n": n_col("Ended records")}
                cfg.update({c: pct_col(GAP_NAMES.get(c, c)) for c in classes})
                table(dist.sort_values("n", ascending=False), cfg, ["group", "n"] + classes)

# --------------------------------------------------------------------------- data quality ---------------------------------
with tab_quality:
    st.markdown("**How the raw USDA records were cleaned, and the days when many authorizations ended at once.** The log lists every cleaning rule with the number of rows before and after it.")
    st.subheader("Cleaning log")
    log = load_cleaning_log()
    script = st.selectbox("Script", ["all"] + sorted(log["script"].unique()))
    view = log if script == "all" else log[log["script"] == script]
    table(view, {"script": st.column_config.TextColumn("Script"), "step": st.column_config.TextColumn("Step"), "rule": st.column_config.TextColumn("Rule", width="large"),
                 "rows_before": n_col("Rows before"), "rows_after": n_col("Rows after"), "rows_affected": n_col("Rows changed")},
          ["script", "step", "rule", "rows_before", "rows_after", "rows_affected"], height=420)
    with st.expander("Why each cleaning rule exists"):
        table(view, {"step": st.column_config.TextColumn("Step"), "why": st.column_config.TextColumn("Why", width="large")}, ["step", "why"], height=420)

    st.subheader("Batch deauthorization days")
    ends = load_end_dates()
    daily = ends.groupby("end_date").agg(ends=("end_date", "size"), batch=("qa_batch_end", "max")).reset_index()
    batch_days = daily[daily["batch"] == True]  # noqa: E712
    threshold = int(batch_days["ends"].min()) if len(batch_days) else None
    c1, c2, c3 = st.columns(3)
    c1.metric("Ended authorizations", f"{len(ends):,}", help=f"All NC SNAP authorizations of any store type that ended through {DATA_THROUGH}.")
    c2.metric("Batch days", f"{len(batch_days):,}", help="Days when many authorizations ended at once (batch deauthorizations).")
    c3.metric("Share on batch days", f"{100 * batch_days['ends'].sum() / len(ends):.0f}%" if len(ends) else "n/a")
    fig = go.Figure()
    other = daily[daily["batch"] != True]  # noqa: E712
    fig.add_trace(go.Bar(x=other["end_date"], y=other["ends"], name="Other days", marker={"color": "#c3c2b7"}, hovertemplate="%{x|%Y-%m-%d}: %{y} authorizations ended<extra></extra>"))
    fig.add_trace(go.Bar(x=batch_days["end_date"], y=batch_days["ends"], name="Batch deauthorization days", marker={"color": INK}, hovertemplate="%{x|%Y-%m-%d}: %{y} authorizations ended<extra></extra>"))
    if threshold:
        fig.add_hline(y=threshold, line={"color": MUTED, "width": 1, "dash": "dot"}, annotation_text=f"{threshold}+ ended on one day = batch day", annotation_position="top left",
                      annotation_font={"size": 11, "color": MUTED})
    fig.update_yaxes(title="Authorizations ending that day")
    fig.update_layout(barmode="overlay", bargap=0)
    finish(fig, "Days when many SNAP authorizations ended at once",
           f"Number of NC SNAP authorizations of any store type that ended on each date, through {DATA_THROUGH}", height=420, value_axis="y")
    show(fig)
    st.caption((f"A day is a batch day when {threshold} or more NC retailers ended on it (flagged from the daily counts through {DATA_THROUGH}); "
                f"such days look like administrative actions by USDA rather than store decisions. \"{ALL_LABEL}\" includes them; \"{STRICT_LABEL}\" leaves them out.")
               if threshold else "No batch days in the data.")
    mix = ends[ends["qa_batch_end"] == True].assign(  # noqa: E712
        grocery=lambda x: x["is_grocery"] == True, convenience=lambda x: x["is_convenience"] == True)  # noqa: E712
    table_ = mix.groupby("end_date").agg(total=("end_date", "size"), grocery=("grocery", "sum"), convenience=("convenience", "sum")).reset_index()
    table_["other"] = table_["total"] - table_["grocery"] - table_["convenience"]
    table_["end_date"] = table_["end_date"].dt.strftime("%Y-%m-%d")
    with st.expander("Batch days and the kinds of stores they hit"):
        table(table_.sort_values("total", ascending=False), {"end_date": st.column_config.TextColumn("Date"), "total": n_col("All authorizations ended"), "grocery": n_col("Grocery stores"),
                                                              "convenience": n_col("Convenience stores"), "other": n_col("Other store types")},
              ["end_date", "total", "grocery", "convenience", "other"])
