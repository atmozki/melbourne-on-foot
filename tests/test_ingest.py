"""Regression checks for scalar reads from DuckDB relations."""

import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import duckdb

from pipeline import ingest


class IngestTests(unittest.TestCase):
    def test_incremental_refresh_reads_existing_partitions(self):
        with tempfile.TemporaryDirectory() as tmp:
            counts_dir = Path(tmp)
            latest = date.today()
            partition = counts_dir / f"counts_{latest:%Y_%m}.parquet"
            duckdb.sql(f"select date '{latest.isoformat()}' as sensing_date").write_parquet(
                str(partition)
            )
            with patch.object(ingest.config, "COUNTS_DIR", counts_dir):
                self.assertEqual(ingest.stored_max_date(), latest)
                with (
                    patch.object(ingest, "export_parquet") as export,
                    patch.object(ingest, "dataset_min_date") as minimum,
                ):
                    ingest.fetch_counts(None)
                    minimum.assert_not_called()
                    expected_months = ingest.month_starts(
                        latest - timedelta(days=ingest.config.LOOKBACK_DAYS), latest
                    )
                    self.assertEqual(export.call_count, len(expected_months))
                    self.assertEqual(export.call_args_list[-1].args[3], partition)

    def test_empty_checkout_has_no_stored_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(ingest.config, "COUNTS_DIR", Path(tmp)):
                self.assertIsNone(ingest.stored_max_date())


if __name__ == "__main__":
    unittest.main()
