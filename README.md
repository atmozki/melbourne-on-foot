# Melbourne on Foot

**Live dashboard: [melbourne-on-foot-atmozki.streamlit.app](https://melbourne-on-foot-atmozki.streamlit.app)**

Melbourne has been counting footsteps since 2009. Sensors above street corners across the CBD log how many people walk past every hour, and the city publishes the feed as open data. This project takes that feed end to end: a Python ingestion pipeline, a DuckDB warehouse modelled with dbt, a LightGBM model that forecasts the week ahead for every sensor, and a Streamlit dashboard on top, retrained and refreshed weekly by GitHub Actions.

![Dashboard](docs/dashboard.png)

## Architecture

```
City of Melbourne Open Data API (Opendatasoft Explore v2.1)
   |
   |  pipeline/ingest.py
   |  incremental pull, one Parquet partition per month
   v
data/raw/ ............ raw layer, rebuilt from the API, never committed
   |
   |  dbt build (transform/)
   |  staging views, tested marts
   v
data/warehouse.duckdb . DuckDB warehouse, local only
   |
   |  pipeline/export_marts.py
   |  ml/forecast.py
   |  backtest, retrain, predict 7 days ahead
   v
data/marts/ .......... five small Parquet files, committed to the repo
   |
   |  app/streamlit_app.py
   v
Streamlit dashboard ... reads only the marts, deploys anywhere
```

`python run_pipeline.py` runs the three stages in order.

## Design decisions

**Bulk exports over paged records.** The Opendatasoft records API caps out at 100 rows per call. The exports endpoint streams a whole filtered dataset in one request, so a month of data is one HTTP call instead of a thousand.

**Monthly partitions, replaced whole.** Each refresh re-downloads every month touched by the last 7 days (sensor readings can arrive late) and swaps the partition file atomically. Reruns are idempotent and there is no dedupe bookkeeping in the ingestion layer. Staging still enforces one row per observation id as a safety net.

**The warehouse is disposable.** Raw data and the DuckDB file are gitignored. Only the dbt marts get committed, about 700KB of Parquet covering two years of data from 136 sensors (1.6M hourly readings). The deployed dashboard needs nothing but those three files, so it runs on Streamlit Community Cloud's free tier with no database to host.

**Trust the data, not the calendar.** The newest day in the feed is usually still filling in. The dashboard anchors on the latest day with near-complete sensor coverage instead of blindly using yesterday, which avoids a misleading 99 percent drop in the headline numbers.

**Tests live in dbt.** Uniqueness on observation ids, accepted ranges on hours and counts, referential integrity from facts to the sensor dimension. `dbt build` runs models and tests together, and the scheduled refresh fails loudly if the source data goes weird.

**Forecasts are precomputed, not served.** The weekly pipeline trains three LightGBM quantile models (10th, 50th and 90th percentile) on the full two year history and writes next week's hourly predictions to a Parquet mart. The dashboard just reads the file: no model artifact to host, no inference at request time, and the free tier stays free.

**Only features the future can know.** The model predicts up to 7 days out, so every lag is at least a week old and week-aligned: the same hour 7, 14, 21 and 28 days back, plus calendar features and Victorian public holidays. Counts are trained on a log scale so the busy corners don't drown out the quiet ones, and quantiles survive the transform because log is monotone.

**The baseline keeps the model honest.** Before publishing, a rolling-origin backtest replays the last four weekly releases, training only on data before each cutoff, and scores the median forecast against a seasonal-naive baseline (same hour, one week earlier). The scores ship with the forecast and the dashboard displays them, including how often the 80% band actually contains the truth.

## Data models

| Model | Grain | Purpose |
|---|---|---|
| `stg_counts` | one row per sensor hour | typed, deduplicated source data |
| `stg_sensors` | one row per location | typed sensor reference |
| `fct_hourly_counts` | one row per sensor hour | calendar enrichment, base for marts |
| `dim_sensors` | one row per location | coordinates, status, activity bounds |
| `mart_daily_location` | one row per location day | trends, rankings, the map |
| `mart_hourly_profile` | location x weekday x hour | heatmap and hourly profiles, trailing 90 days |
| `mart_forecast` | location x future date x hour | next 7 days, p10/p50/p90, from `ml/forecast.py` |
| `mart_forecast_metrics` | one row per backtest fold x method | model vs baseline MAE, WAPE, band coverage |

## Running it yourself

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt -r pipeline/requirements.txt
python run_pipeline.py
streamlit run app/streamlit_app.py
```

The first run backfills the full two year window, around 25 API calls and a couple of minutes, then trains and backtests the forecaster, which takes a few minutes more. After that, runs only touch the trailing week. The dashboard works straight away even without running the pipeline, since the marts are committed.

## Refresh schedule

A GitHub Actions workflow runs the pipeline every Monday at 3:30am Melbourne time, picking up the full week behind it: fresh data in, dbt tests, model retrained, forecasts and backtest scores rewritten. If the marts changed, it commits them, which triggers a redeploy of the dashboard. The cron line in `.github/workflows/refresh-data.yml` is the only thing to change for a different cadence.

## Data source

[Pedestrian Counting System, City of Melbourne](https://data.melbourne.vic.gov.au/explore/dataset/pedestrian-counting-system-monthly-counts-per-hour/information/), licensed CC BY 4.0. The API serves a rolling two year window of hourly counts. Counts are sensor readings, not exact footfall.
