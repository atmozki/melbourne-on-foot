"""Melbourne on Foot: pedestrian traffic across the Melbourne CBD.

Reads the Parquet marts produced by the dbt project in transform/.
Run from the repo root with: streamlit run app/streamlit_app.py
"""

from datetime import timedelta
from html import escape
from pathlib import Path

import duckdb
import pandas as pd
import plotly.graph_objects as go
import pydeck as pdk
import streamlit as st

MARTS_DIR = Path(__file__).resolve().parents[1] / "data" / "marts"

GOLD = "#DFB960"
GOLD_SOFT = "rgba(223, 185, 96, 0.18)"
INK = "#0C0F14"
PANEL = "#161B24"
TEXT = "#E6E8EC"
MUTED = "#8B93A1"
DAY_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

st.set_page_config(
    page_title="Melbourne on Foot",
    page_icon="\U0001f6b6",
    layout="wide",
)

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600&family=Inter:wght@400;500;600&display=swap');

    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
    h1, h2, h3 { font-family: 'Fraunces', serif !important; letter-spacing: 0.01em; }
    h1 { font-weight: 600 !important; }

    .hero-sub { color: #8B93A1; font-size: 1.02rem; margin-top: -0.4rem; }
    .data-badge {
        display: inline-block; padding: 0.25rem 0.7rem; border-radius: 999px;
        border: 1px solid rgba(223, 185, 96, 0.45); color: #DFB960;
        font-size: 0.8rem; margin-top: 0.4rem;
    }
    div[data-testid="stMetric"] {
        background: #161B24; border: 1px solid rgba(255,255,255,0.06);
        border-radius: 12px; padding: 1rem 1.2rem;
        height: 150px; overflow: hidden;
    }
    div[data-testid="stMetricLabel"] { color: #8B93A1; }
    div[data-testid="stMetric"] div[data-testid="stMarkdownContainer"],
    div[data-testid="stMetric"] p { white-space: normal !important; overflow: visible !important; text-overflow: clip !important; }
    .kpi-card {
        background: #161B24; border: 1px solid rgba(255,255,255,0.06);
        border-radius: 12px; padding: 1rem 1.2rem;
        height: 150px; overflow: hidden;
    }
    .kpi-label { color: #8B93A1; font-size: 0.875rem; margin: 0 0 0.45rem 0; }
    .kpi-name {
        color: #E6E8EC; font-size: 1.25rem; font-weight: 500; line-height: 1.25; margin: 0;
        display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden;
    }
    div[data-testid="stMetricValue"] { white-space: normal; line-height: 1.15; font-size: 1.7rem !important; }
    div[data-testid="stMetricValue"] div[data-testid="stMarkdownContainer"],
    div[data-testid="stMetricValue"] p {
        white-space: normal !important;
        display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
        overflow: hidden !important;
    }
    .section-note { color: #8B93A1; font-size: 0.88rem; margin-top: -0.6rem; }
    footer { visibility: hidden; }
    #MainMenu { visibility: hidden; }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data(ttl=3600, show_spinner=False)
def load_forecast() -> tuple[pd.DataFrame, pd.DataFrame] | None:
    fc_path = MARTS_DIR / "mart_forecast.parquet"
    metrics_path = MARTS_DIR / "mart_forecast_metrics.parquet"
    if not fc_path.exists() or not metrics_path.exists():
        return None
    fc = pd.read_parquet(fc_path)
    fc["sensing_date"] = pd.to_datetime(fc["sensing_date"])
    fc["ts"] = fc["sensing_date"] + pd.to_timedelta(fc["hour_of_day"], unit="h")
    return fc, pd.read_parquet(metrics_path)


@st.cache_data(ttl=3600, show_spinner=False)
def load_marts() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    con = duckdb.connect()
    daily = con.sql(
        f"select * from read_parquet('{(MARTS_DIR / 'mart_daily_location.parquet').as_posix()}')"
    ).df()
    sensors = con.sql(
        f"select * from read_parquet('{(MARTS_DIR / 'dim_sensors.parquet').as_posix()}')"
    ).df()
    profile = con.sql(
        f"select * from read_parquet('{(MARTS_DIR / 'mart_hourly_profile.parquet').as_posix()}')"
    ).df()
    con.close()
    daily["sensing_date"] = pd.to_datetime(daily["sensing_date"])
    return daily, sensors, profile


def base_layout(fig: go.Figure, height: int = 380) -> go.Figure:
    fig.update_layout(
        height=height,
        margin=dict(l=10, r=10, t=30, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter", color=TEXT, size=13),
        hoverlabel=dict(bgcolor=PANEL, font_color=TEXT, bordercolor=GOLD),
        xaxis=dict(gridcolor="rgba(255,255,255,0.06)", zeroline=False),
        yaxis=dict(gridcolor="rgba(255,255,255,0.06)", zeroline=False),
        showlegend=False,
    )
    return fig


def fmt(n: float) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}K"
    return f"{n:.0f}"


daily, sensors, profile = load_marts()

# The newest day in the feed is usually still filling in, so anchor the
# dashboard to the latest day with near-complete sensor coverage and drop
# anything after it.
coverage = daily.groupby("sensing_date")["hours_reported"].sum().sort_index()
threshold = coverage.tail(28).median() * 0.8
latest_date = coverage[coverage >= threshold].index.max()
daily = daily[daily["sensing_date"] <= latest_date]

# ---------------------------------------------------------------- header
st.title("Melbourne on Foot")
st.markdown(
    '<p class="hero-sub">Hourly pedestrian traffic from the City of Melbourne sensor '
    "network, refreshed weekly. Ingestion in Python, models in dbt on DuckDB, a "
    "LightGBM forecast of the week ahead, served with Streamlit.</p>",
    unsafe_allow_html=True,
)
st.markdown(
    f'<span class="data-badge">Data through {latest_date:%d %b %Y}</span>',
    unsafe_allow_html=True,
)
st.write("")

# ---------------------------------------------------------------- KPIs
yesterday = daily[daily["sensing_date"] == latest_date]
same_day_last_week = daily[daily["sensing_date"] == latest_date - timedelta(days=7)]

last7_start = latest_date - timedelta(days=6)
last7 = daily[daily["sensing_date"] >= last7_start]
prior7 = daily[
    (daily["sensing_date"] >= last7_start - timedelta(days=7))
    & (daily["sensing_date"] < last7_start)
]

yesterday_total = yesterday["daily_count"].sum()
lastweek_total = same_day_last_week["daily_count"].sum()
last7_total = last7["daily_count"].sum()
prior7_total = prior7["daily_count"].sum()

busiest = last7.groupby("location_name")["daily_count"].sum().sort_values(ascending=False)
busiest_name = escape(str(busiest.index[0])) if len(busiest) else "n/a"

c1, c2, c3, c4 = st.columns(4)
c1.metric(
    f"Pedestrians on {latest_date:%a %d %b}",
    fmt(yesterday_total),
    delta=f"{(yesterday_total / lastweek_total - 1) * 100:+.1f}% vs last {latest_date:%a}"
    if lastweek_total
    else None,
)
c2.metric(
    "Last 7 days",
    fmt(last7_total),
    delta=f"{(last7_total / prior7_total - 1) * 100:+.1f}% vs prior week" if prior7_total else None,
)
c3.markdown(
    '<div class="kpi-card"><p class="kpi-label">Busiest spot this week</p>'
    f'<p class="kpi-name">{busiest_name}</p></div>',
    unsafe_allow_html=True,
)
c4.metric("Sensors reporting", f"{yesterday['location_id'].nunique()}")

st.write("")

# ---------------------------------------------------------------- map + top locations
map_col, rank_col = st.columns([1.15, 1])

last28 = daily[daily["sensing_date"] > latest_date - timedelta(days=28)]
per_location = (
    last28.groupby(["location_id", "location_name"], as_index=False)
    .agg(avg_daily=("daily_count", "mean"), latitude=("latitude", "first"), longitude=("longitude", "first"))
    .dropna(subset=["latitude", "longitude"])
)
per_location["radius"] = (per_location["avg_daily"] ** 0.5) * 0.55
per_location["avg_label"] = per_location["avg_daily"].map(lambda v: f"{v:,.0f}")

with map_col:
    st.subheader("Where the city walks")
    st.markdown(
        '<p class="section-note">Average pedestrians per day over the last 28 days. '
        "Bigger circles mean busier footpaths.</p>",
        unsafe_allow_html=True,
    )
    layer = pdk.Layer(
        "ScatterplotLayer",
        per_location,
        get_position=["longitude", "latitude"],
        get_radius="radius",
        radius_min_pixels=3,
        radius_max_pixels=26,
        get_fill_color=[223, 185, 96, 165],
        get_line_color=[12, 15, 20, 200],
        line_width_min_pixels=1,
        stroked=True,
        pickable=True,
    )
    st.pydeck_chart(
        pdk.Deck(
            layers=[layer],
            initial_view_state=pdk.ViewState(latitude=-37.8142, longitude=144.9632, zoom=13.4, pitch=30, bearing=0),
            map_provider="carto",
            map_style="dark",
            tooltip={"html": "<b>{location_name}</b><br/>{avg_label} pedestrians per day"},
        ),
        height=430,
    )

with rank_col:
    st.subheader("Busiest locations")
    st.markdown(
        '<p class="section-note">Total pedestrians over the last 28 days.</p>',
        unsafe_allow_html=True,
    )
    top10 = (
        last28.groupby("location_name")["daily_count"].sum().sort_values(ascending=True).tail(10)
    )
    fig = go.Figure(
        go.Bar(
            x=top10.values,
            y=top10.index,
            orientation="h",
            marker=dict(color=GOLD, line=dict(width=0)),
            hovertemplate="%{y}<br>%{x:,.0f} pedestrians<extra></extra>",
        )
    )
    fig = base_layout(fig, height=430)
    fig.update_xaxes(tickformat="~s")
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

# ---------------------------------------------------------------- citywide trend
st.subheader("The citywide pulse")
window = st.radio(
    "Range",
    ["90 days", "6 months", "1 year", "All"],
    horizontal=True,
    label_visibility="collapsed",
)
days = {"90 days": 90, "6 months": 182, "1 year": 365, "All": 10_000}[window]

citywide = daily.groupby("sensing_date", as_index=False)["daily_count"].sum()
citywide = citywide[citywide["sensing_date"] > latest_date - timedelta(days=days)]
citywide["rolling7"] = citywide["daily_count"].rolling(7, min_periods=1).mean()

fig = go.Figure()
fig.add_trace(
    go.Scatter(
        x=citywide["sensing_date"],
        y=citywide["daily_count"],
        mode="lines",
        line=dict(color="rgba(223,185,96,0.30)", width=1),
        hovertemplate="%{x|%a %d %b %Y}<br>%{y:,.0f} pedestrians<extra></extra>",
    )
)
fig.add_trace(
    go.Scatter(
        x=citywide["sensing_date"],
        y=citywide["rolling7"],
        mode="lines",
        line=dict(color=GOLD, width=2.4),
        fill="tozeroy",
        fillcolor="rgba(223,185,96,0.06)",
        hovertemplate="%{x|%a %d %b %Y}<br>7 day average: %{y:,.0f}<extra></extra>",
    )
)
fig = base_layout(fig, height=360)
fig.update_yaxes(tickformat="~s")
st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

# ---------------------------------------------------------------- forecast
loaded_forecast = load_forecast()
forecast, fc_metrics = loaded_forecast if loaded_forecast else (None, None)
today = pd.Timestamp.now(tz="Australia/Melbourne").normalize().tz_localize(None)
forecast_had_rows = forecast is not None and len(forecast) > 0
forecast_end = forecast["sensing_date"].max() if forecast_had_rows else None
if forecast_had_rows:
    forecast = forecast[
        (forecast["sensing_date"] > latest_date)
        & (forecast["sensing_date"] >= today)
    ]

if forecast_had_rows and not len(forecast):
    st.info(
        f"The latest forecast ended on {forecast_end:%d %b %Y} or has been overtaken "
        "by newer actual data. It will return after the next weekly refresh."
    )

if forecast is not None and len(forecast):
    st.subheader("The week ahead")
    st.markdown(
        f'<p class="section-note">Gradient-boosted hourly forecast through '
        f'{forecast["sensing_date"].max():%d %b %Y}, retrained on the sensor history every weekly '
        "refresh and scored against the last four weeks before publishing.</p>",
        unsafe_allow_html=True,
    )

    hist = daily.groupby("sensing_date", as_index=False)["daily_count"].sum()
    hist = hist[hist["sensing_date"] > latest_date - timedelta(days=42)]
    daily_fc = forecast.groupby("sensing_date", as_index=False)["p50"].sum()
    # Start the forecast trace from the last actual point so the line connects.
    bridge = pd.DataFrame(
        {"sensing_date": [latest_date], "p50": [hist["daily_count"].iloc[-1]]}
    )
    daily_fc = pd.concat([bridge, daily_fc], ignore_index=True)

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=hist["sensing_date"],
            y=hist["daily_count"],
            mode="lines",
            line=dict(color=GOLD, width=2.2),
            hovertemplate="%{x|%a %d %b %Y}<br>%{y:,.0f} pedestrians<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=daily_fc["sensing_date"],
            y=daily_fc["p50"],
            mode="lines+markers",
            line=dict(color=GOLD, width=2.2, dash="dot"),
            marker=dict(size=6, symbol="diamond", color=GOLD),
            hovertemplate="%{x|%a %d %b %Y}<br>forecast: %{y:,.0f} pedestrians<extra></extra>",
        )
    )
    fig.add_vline(x=latest_date, line=dict(color="rgba(255,255,255,0.18)", dash="dash"))
    fig = base_layout(fig, height=340)
    fig.update_yaxes(tickformat="~s")
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

    overall = fc_metrics[fc_metrics["scope"] == "overall"].set_index("method")
    model_wape = overall.loc["model", "wape"]
    naive_wape = overall.loc["seasonal_naive", "wape"]
    coverage = overall.loc["model", "band_coverage"]
    active_locations = daily.loc[
        daily["sensing_date"] > latest_date - timedelta(days=14), "location_id"
    ].nunique()
    forecast_locations = forecast["location_id"].nunique()
    forecast_start = max(today, latest_date + pd.Timedelta(days=1))
    forecast_days = (forecast["sensing_date"].max() - forecast_start).days + 1
    expected_rows = active_locations * forecast_days * 24
    row_coverage = len(forecast) / expected_rows if expected_rows else 0

    m1, m2, m3 = st.columns(3)
    m1.metric(
        "Backtest error, WAPE",
        f"{model_wape:.1%}",
        delta=f"{(1 - model_wape / naive_wape) * 100:+.0f}% vs seasonal-naive baseline",
    )
    m2.metric("80% band coverage", f"{coverage:.0%}")
    m3.metric(
        "Forecast coverage",
        f"{row_coverage:.1%}",
        delta=f"{forecast_locations} of {active_locations} active locations",
        delta_color="off",
    )
    st.markdown(
        '<p class="section-note">WAPE is total absolute error over total pedestrians, '
        "hourly grain. The baseline repeats the same hour from one week earlier. "
        "Scores come from rolling-origin backtests on the four weeks the model never "
        "saw during training.</p>",
        unsafe_allow_html=True,
    )

# ---------------------------------------------------------------- rhythm heatmap
st.subheader("The rhythm of the week")
st.markdown(
    '<p class="section-note">Average pedestrians counted across all sensors, by hour and '
    "day of week, over the last 90 days. Lunch rush, Friday nights and quiet Sunday "
    "mornings all show up.</p>",
    unsafe_allow_html=True,
)

rhythm = (
    profile.groupby(["day_name", "hour_of_day"], as_index=False)["avg_count"]
    .sum()
    .pivot(index="day_name", columns="hour_of_day", values="avg_count")
    .reindex(DAY_ORDER)
)
fig = go.Figure(
    go.Heatmap(
        z=rhythm.values,
        x=[f"{h:02d}" for h in rhythm.columns],
        y=rhythm.index,
        colorscale=[[0, "#10141C"], [0.4, "#5C4D28"], [1, GOLD]],
        hovertemplate="%{y} %{x}:00<br>%{z:,.0f} pedestrians per hour<extra></extra>",
        showscale=False,
    )
)
fig = base_layout(fig, height=340)
st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

# ---------------------------------------------------------------- location explorer
st.subheader("Explore a location")
names = sorted(daily["location_name"].dropna().unique())
default_ix = names.index(busiest.index[0]) if len(busiest) and busiest.index[0] in names else 0
chosen = st.selectbox("Location", names, index=default_ix, label_visibility="collapsed")

loc_col1, loc_col2 = st.columns(2)

loc_daily = daily[daily["location_name"] == chosen].sort_values("sensing_date")
loc_daily = loc_daily[loc_daily["sensing_date"] > latest_date - timedelta(days=365)]
loc_daily["rolling7"] = loc_daily["daily_count"].rolling(7, min_periods=1).mean()

with loc_col1:
    st.markdown(f"**Daily traffic, last 12 months**")
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=loc_daily["sensing_date"],
            y=loc_daily["daily_count"],
            mode="lines",
            line=dict(color="rgba(223,185,96,0.25)", width=1),
            hovertemplate="%{x|%a %d %b %Y}<br>%{y:,.0f}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=loc_daily["sensing_date"],
            y=loc_daily["rolling7"],
            mode="lines",
            line=dict(color=GOLD, width=2.2),
            hovertemplate="%{x|%a %d %b %Y}<br>7 day average: %{y:,.0f}<extra></extra>",
        )
    )
    fig = base_layout(fig, height=320)
    fig.update_yaxes(tickformat="~s")
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

loc_profile = profile[profile["location_name"] == chosen].copy()
loc_profile["weight"] = loc_profile["avg_count"] * loc_profile["n_observations"]
by_type = (
    loc_profile.groupby(["is_weekend", "hour_of_day"])
    .apply(lambda g: g["weight"].sum() / g["n_observations"].sum(), include_groups=False)
    .rename("avg_count")
    .reset_index()
)

with loc_col2:
    st.markdown("**Hourly profile, last 90 days**")
    fig = go.Figure()
    for is_weekend, label, color in [
        (False, "Weekdays", GOLD),
        (True, "Weekends", "#7BA7BC"),
    ]:
        subset = by_type[by_type["is_weekend"] == is_weekend]
        fig.add_trace(
            go.Scatter(
                x=subset["hour_of_day"],
                y=subset["avg_count"],
                mode="lines",
                name=label,
                line=dict(color=color, width=2.2),
                hovertemplate=label + " %{x}:00<br>%{y:,.0f} pedestrians per hour<extra></extra>",
            )
        )
    fig = base_layout(fig, height=320)
    fig.update_layout(showlegend=True, legend=dict(orientation="h", y=1.1))
    fig.update_xaxes(tickvals=list(range(0, 24, 3)), ticktext=[f"{h:02d}:00" for h in range(0, 24, 3)])
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

if forecast is not None and len(loc_daily):
    loc_fc = forecast[forecast["location_id"] == loc_daily["location_id"].iloc[0]]
    loc_fc = loc_fc.sort_values("ts")
    if len(loc_fc):
        st.markdown("**The week ahead, hour by hour**")
        st.markdown(
            '<p class="section-note">Median forecast with the model\'s 10th to 90th '
            "percentile range.</p>",
            unsafe_allow_html=True,
        )
        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=loc_fc["ts"], y=loc_fc["p90"], mode="lines",
                line=dict(width=0), hoverinfo="skip",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=loc_fc["ts"], y=loc_fc["p10"], mode="lines",
                line=dict(width=0), fill="tonexty", fillcolor=GOLD_SOFT,
                hoverinfo="skip",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=loc_fc["ts"],
                y=loc_fc["p50"],
                mode="lines",
                line=dict(color=GOLD, width=2.2),
                customdata=loc_fc[["p10", "p90"]],
                hovertemplate="%{x|%a %d %b, %H:00}<br>%{y:,.0f} pedestrians "
                "(%{customdata[0]:,.0f}–%{customdata[1]:,.0f})<extra></extra>",
            )
        )
        fig = base_layout(fig, height=300)
        fig.update_yaxes(tickformat="~s")
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

# ---------------------------------------------------------------- footer
st.divider()
st.markdown(
    f'<p style="color:{MUTED}; font-size:0.85rem;">Data: '
    '<a href="https://data.melbourne.vic.gov.au/explore/dataset/pedestrian-counting-system-monthly-counts-per-hour/information/" '
    f'style="color:{GOLD};">City of Melbourne Pedestrian Counting System</a> (CC BY 4.0). '
    "Counts are sensor readings, not exact footfall. "
    f'Built by Dennis Jojo Kuriakose · <a href="https://github.com/atmozki" style="color:{GOLD};">GitHub</a></p>',
    unsafe_allow_html=True,
)
