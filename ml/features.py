"""Feature engineering for the footfall forecast.

Every feature is known at forecast time. The model predicts up to 7 days
ahead, so the shortest lag is 7 days and all lags are week-aligned, which
keeps the weekly rhythm of the city in the features themselves. Gaps in
the sensor record become NaN lags; LightGBM handles those natively, so
nothing gets imputed.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import holidays
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WAREHOUSE = PROJECT_ROOT / "data" / "warehouse.duckdb"

LAG_DAYS = (7, 14, 21, 28)
FEATURES = [
    "location_id",
    "hour_of_day",
    "day_of_week",
    "is_weekend",
    "month",
    "is_holiday",
    *[f"lag_{d}d" for d in LAG_DAYS],
    "lag_mean_4w",
]
TARGET = "pedestrian_count"


def load_observations() -> pd.DataFrame:
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    obs = con.sql(
        "select location_id, sensing_date, hour_of_day, pedestrian_count"
        " from fct_hourly_counts"
    ).df()
    con.close()
    obs["sensing_date"] = pd.to_datetime(obs["sensing_date"])
    return obs


def anchor_date(obs: pd.DataFrame) -> pd.Timestamp:
    """Latest day with near-complete sensor coverage, same rule as the dashboard."""
    coverage = obs.groupby("sensing_date").size().sort_index()
    threshold = coverage.tail(28).median() * 0.8
    return coverage[coverage >= threshold].index.max()


def featurize(frame: pd.DataFrame, obs: pd.DataFrame) -> pd.DataFrame:
    """Attach lag and calendar features to rows keyed by location, date and hour."""
    for d in LAG_DAYS:
        lagged = obs.rename(columns={TARGET: f"lag_{d}d"}).copy()
        lagged["sensing_date"] = lagged["sensing_date"] + pd.Timedelta(days=d)
        frame = frame.merge(
            lagged, on=["location_id", "sensing_date", "hour_of_day"], how="left"
        )
    frame["lag_mean_4w"] = frame[[f"lag_{d}d" for d in LAG_DAYS]].mean(axis=1)

    dates = frame["sensing_date"]
    vic_holidays = holidays.country_holidays(
        "AU", subdiv="VIC", years=range(dates.min().year, dates.max().year + 1)
    )
    frame["day_of_week"] = dates.dt.dayofweek.astype("int8")
    frame["is_weekend"] = (frame["day_of_week"] >= 5).astype("int8")
    frame["month"] = dates.dt.month.astype("int8")
    frame["is_holiday"] = dates.dt.date.isin(set(vic_holidays.keys())).astype("int8")
    frame["location_id"] = pd.Categorical(
        frame["location_id"], categories=sorted(obs["location_id"].unique())
    )
    return frame


def future_frame(obs: pd.DataFrame, anchor: pd.Timestamp, horizon_days: int) -> pd.DataFrame:
    """One row per active location, future date and hour of day.

    Active means the sensor reported within the two weeks before the anchor;
    dead sensors get no forecast rather than a confident guess.
    """
    recent = obs[obs["sensing_date"] > anchor - pd.Timedelta(days=14)]
    dates = pd.date_range(anchor + pd.Timedelta(days=1), periods=horizon_days, freq="D")
    frame = pd.MultiIndex.from_product(
        [sorted(recent["location_id"].unique()), dates, range(24)],
        names=["location_id", "sensing_date", "hour_of_day"],
    ).to_frame(index=False)
    return featurize(frame, obs)
