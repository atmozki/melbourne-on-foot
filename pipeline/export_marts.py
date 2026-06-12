"""Export dbt mart tables from the DuckDB warehouse to Parquet.

The dashboard reads these files instead of the warehouse itself, so the
deployed app only ships a few small aggregates rather than the full
hourly history.
"""

from __future__ import annotations

import logging

import duckdb

from pipeline import config

log = logging.getLogger("export_marts")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    config.MARTS_DIR.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(str(config.WAREHOUSE_PATH), read_only=True)
    try:
        for table in config.MART_TABLES:
            dest = config.MARTS_DIR / f"{table}.parquet"
            con.execute(
                f"copy (select * from {table}) to '{dest.as_posix()}' (format parquet, compression zstd)"
            )
            rows = con.execute(f"select count(*) from {table}").fetchone()[0]
            log.info("Exported %s (%s rows)", dest.name, f"{rows:,}")
    finally:
        con.close()


if __name__ == "__main__":
    main()
