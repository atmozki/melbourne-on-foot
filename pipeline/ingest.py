"""Pull pedestrian sensor data from the City of Melbourne open data API.

Two datasets land in data/raw as Parquet:

  - sensors.parquet: one row per counting sensor, fully refreshed each run
  - counts/counts_YYYY_MM.parquet: hourly pedestrian counts, partitioned by
    month. Only months touched by the refresh window are re-downloaded, and
    each partition is replaced whole so reruns stay idempotent.

The API is Opendatasoft Explore v2.1. The /exports/parquet endpoint streams
an entire filtered dataset in one request, which beats paging through the
records endpoint 100 rows at a time.
"""

from __future__ import annotations

import argparse
import logging
import tempfile
from datetime import date, timedelta
from pathlib import Path

import duckdb
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from pipeline import config

log = logging.getLogger("ingest")


def build_session() -> requests.Session:
    session = requests.Session()
    retries = Retry(
        total=5,
        backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    session.mount("https://", HTTPAdapter(max_retries=retries))
    return session


def export_parquet(session: requests.Session, dataset: str, where: str | None, dest: Path) -> None:
    """Stream a filtered dataset export to dest, writing via a temp file."""
    url = f"{config.API_BASE}/{dataset}/exports/parquet"
    params = {"where": where} if where else {}
    dest.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(dir=dest.parent, suffix=".tmp", delete=False) as tmp:
        tmp_path = Path(tmp.name)
        try:
            with session.get(
                url, params=params, stream=True, timeout=config.REQUEST_TIMEOUT_SECONDS
            ) as response:
                response.raise_for_status()
                for chunk in response.iter_content(chunk_size=1 << 20):
                    tmp.write(chunk)
        except Exception:
            tmp.close()
            tmp_path.unlink(missing_ok=True)
            raise
    tmp_path.replace(dest)


def fetch_sensors(session: requests.Session) -> None:
    log.info("Refreshing sensor locations")
    export_parquet(session, config.SENSORS_DATASET, None, config.SENSORS_PATH)


def dataset_min_date(session: requests.Session) -> date:
    """Ask the API for the earliest sensing_date currently available."""
    url = f"{config.API_BASE}/{config.COUNTS_DATASET}/records"
    response = session.get(
        url,
        params={"select": "min(sensing_date) as min_date"},
        timeout=config.REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return date.fromisoformat(response.json()["results"][0]["min_date"][:10])


def stored_max_date() -> date | None:
    """Latest sensing_date already on disk, or None on a fresh checkout."""
    partitions = sorted(config.COUNTS_DIR.glob("counts_*.parquet"))
    if not partitions:
        return None
    result = duckdb.sql(
        f"select max(sensing_date) from read_parquet('{config.COUNTS_DIR.as_posix()}/counts_*.parquet')"
    ).fetchone()[0]
    if result is None:
        return None
    return result if isinstance(result, date) else result.date()


def month_starts(start: date, end: date) -> list[date]:
    """First-of-month dates for every month between start and end inclusive."""
    months = []
    cursor = start.replace(day=1)
    while cursor <= end:
        months.append(cursor)
        cursor = (cursor + timedelta(days=32)).replace(day=1)
    return months


def fetch_counts(session: requests.Session, full: bool = False) -> None:
    today = date.today()
    latest = None if full else stored_max_date()

    if latest is None:
        window_start = dataset_min_date(session)
        log.info("No local data, backfilling from %s", window_start)
    else:
        window_start = latest - timedelta(days=config.LOOKBACK_DAYS)
        log.info("Local data through %s, refreshing from %s", latest, window_start)

    for month_start in month_starts(window_start, today):
        next_month = (month_start + timedelta(days=32)).replace(day=1)
        where = (
            f"sensing_date>=date'{month_start.isoformat()}'"
            f" and sensing_date<date'{next_month.isoformat()}'"
        )
        dest = config.COUNTS_DIR / f"counts_{month_start:%Y_%m}.parquet"
        log.info("Pulling %s", dest.name)
        export_parquet(session, config.COUNTS_DATASET, where, dest)

    rows = duckdb.sql(
        f"select count(*) from read_parquet('{config.COUNTS_DIR.as_posix()}/counts_*.parquet')"
    ).fetchone()[0]
    log.info("Raw counts on disk: %s rows", f"{rows:,}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest Melbourne pedestrian data")
    parser.add_argument(
        "--full", action="store_true", help="ignore local state and re-download everything"
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    session = build_session()
    fetch_sensors(session)
    fetch_counts(session, full=args.full)


if __name__ == "__main__":
    main()
