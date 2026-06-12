"""Shared paths and API settings for the ingestion pipeline."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
COUNTS_DIR = RAW_DIR / "counts"
SENSORS_PATH = RAW_DIR / "sensors.parquet"
MARTS_DIR = DATA_DIR / "marts"
WAREHOUSE_PATH = DATA_DIR / "warehouse.duckdb"
TRANSFORM_DIR = PROJECT_ROOT / "transform"

API_BASE = "https://data.melbourne.vic.gov.au/api/explore/v2.1/catalog/datasets"
COUNTS_DATASET = "pedestrian-counting-system-monthly-counts-per-hour"
SENSORS_DATASET = "pedestrian-counting-system-sensor-locations"

# Re-pull this many days back from the latest stored date on every run,
# so late-arriving sensor readings get picked up.
LOOKBACK_DAYS = 7

REQUEST_TIMEOUT_SECONDS = 300

MART_TABLES = [
    "dim_sensors",
    "mart_daily_location",
    "mart_hourly_profile",
]
