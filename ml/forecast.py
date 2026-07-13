"""Train the footfall forecaster, backtest it, and export forecast marts.

    python -m ml.forecast [--folds N] [--horizon-days N]

One LightGBM model per quantile (p10, p50, p90), trained on log counts so
the busy corners don't drown out the quiet ones. The backtest replays the
last N weekly releases: train on everything before the cutoff, forecast
the following week, score the median against a seasonal-naive baseline
(same hour, one week earlier). Outputs two marts:

    data/marts/mart_forecast.parquet ........ next week, hourly, per location
    data/marts/mart_forecast_metrics.parquet  backtest scores, model vs baseline
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone

import lightgbm as lgb
import numpy as np
import pandas as pd

from ml import features
from ml.features import FEATURES, TARGET

MARTS_DIR = features.PROJECT_ROOT / "data" / "marts"
QUANTILES = {"p10": 0.10, "p50": 0.50, "p90": 0.90}


def fit_quantile(train: pd.DataFrame, alpha: float) -> lgb.LGBMRegressor:
    model = lgb.LGBMRegressor(
        objective="quantile",
        alpha=alpha,
        n_estimators=400,
        learning_rate=0.06,
        num_leaves=63,
        min_child_samples=40,
        subsample=0.9,
        subsample_freq=1,
        colsample_bytree=0.9,
        random_state=42,
        n_jobs=-1,
        verbose=-1,
    )
    model.fit(train[FEATURES], np.log1p(train[TARGET]))
    return model


def fit_all(train: pd.DataFrame) -> dict[str, lgb.LGBMRegressor]:
    return {name: fit_quantile(train, alpha) for name, alpha in QUANTILES.items()}


def predict(models: dict[str, lgb.LGBMRegressor], frame: pd.DataFrame) -> pd.DataFrame:
    preds = {
        name: np.expm1(model.predict(frame[FEATURES])).clip(min=0)
        for name, model in models.items()
    }
    # log1p is monotone, so the quantiles survive the round trip; sorting
    # row-wise just guards against the independently trained models crossing.
    ordered = np.sort(np.column_stack([preds["p10"], preds["p50"], preds["p90"]]), axis=1)
    return pd.DataFrame(ordered, columns=["p10", "p50", "p90"], index=frame.index)


def trainable(feat: pd.DataFrame) -> pd.DataFrame:
    return feat[feat["lag_mean_4w"].notna() & feat[TARGET].notna()]


def backtest(feat: pd.DataFrame, anchor: pd.Timestamp, folds: int) -> pd.DataFrame:
    """Rolling-origin evaluation over the last `folds` weeks."""
    rows = []
    for k in range(1, folds + 1):
        cutoff = anchor - pd.Timedelta(days=7 * k)
        train = trainable(feat[feat["sensing_date"] <= cutoff])
        # Score only rows where the baseline exists too, so the comparison
        # is on identical ground. That drops well under 1% of test rows.
        test = feat[
            (feat["sensing_date"] > cutoff)
            & (feat["sensing_date"] <= cutoff + pd.Timedelta(days=7))
            & feat[TARGET].notna()
            & feat["lag_7d"].notna()
        ]
        preds = predict(fit_all(train), test)
        actual = test[TARGET].to_numpy(dtype=float)
        naive = test["lag_7d"].to_numpy(dtype=float)

        for method, point in (("model", preds["p50"].to_numpy()), ("seasonal_naive", naive)):
            rows.append(
                {
                    "scope": "fold",
                    "fold_cutoff": cutoff,
                    "method": method,
                    "n_rows": len(test),
                    "sum_abs_err": float(np.abs(actual - point).sum()),
                    "sum_actual": float(actual.sum()),
                    "band_coverage": float(
                        ((actual >= preds["p10"]) & (actual <= preds["p90"])).mean()
                    )
                    if method == "model"
                    else None,
                }
            )
        print(f"  fold {cutoff:%Y-%m-%d}: {len(test):,} rows scored", flush=True)

    metrics = pd.DataFrame(rows)
    overall = (
        metrics.groupby("method", as_index=False)
        .agg(
            n_rows=("n_rows", "sum"),
            sum_abs_err=("sum_abs_err", "sum"),
            sum_actual=("sum_actual", "sum"),
            band_coverage=("band_coverage", "mean"),
        )
        .assign(scope="overall", fold_cutoff=pd.NaT)
    )
    metrics = pd.concat([metrics, overall], ignore_index=True)
    metrics["mae"] = metrics["sum_abs_err"] / metrics["n_rows"]
    metrics["wape"] = metrics["sum_abs_err"] / metrics["sum_actual"]
    return metrics[
        ["scope", "fold_cutoff", "method", "n_rows", "mae", "wape", "band_coverage"]
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folds", type=int, default=4)
    parser.add_argument("--horizon-days", type=int, default=7)
    args = parser.parse_args()

    obs = features.load_observations()
    anchor = features.anchor_date(obs)
    print(f"Anchor date {anchor:%Y-%m-%d}, {len(obs):,} observations", flush=True)

    feat = features.featurize(obs.copy(), obs)

    print(f"Backtesting over the last {args.folds} weeks...", flush=True)
    metrics = backtest(feat, anchor, args.folds)
    overall = metrics[metrics["scope"] == "overall"].set_index("method")
    model_wape = overall.loc["model", "wape"]
    naive_wape = overall.loc["seasonal_naive", "wape"]
    print(
        f"  WAPE {model_wape:.1%} vs seasonal-naive {naive_wape:.1%}"
        f" ({1 - model_wape / naive_wape:+.1%} better),"
        f" 80% band covers {overall.loc['model', 'band_coverage']:.1%}",
        flush=True,
    )

    print("Training final models on history through the anchor...", flush=True)
    final_train = trainable(feat[feat["sensing_date"] <= anchor])
    future = features.future_frame(obs, anchor, args.horizon_days)
    future = future[future["lag_mean_4w"].notna()]
    forecast = pd.concat(
        [future[["location_id", "sensing_date", "hour_of_day"]], predict(fit_all(final_train), future)],
        axis=1,
    )
    forecast["location_id"] = forecast["location_id"].astype("int32")
    forecast["anchor_date"] = anchor
    forecast["generated_at"] = datetime.now(timezone.utc)

    forecast.to_parquet(MARTS_DIR / "mart_forecast.parquet", index=False)
    metrics.to_parquet(MARTS_DIR / "mart_forecast_metrics.parquet", index=False)
    print(
        f"Wrote {len(forecast):,} forecast rows for"
        f" {forecast['location_id'].nunique()} locations through"
        f" {forecast['sensing_date'].max():%Y-%m-%d}.",
        flush=True,
    )


if __name__ == "__main__":
    main()
