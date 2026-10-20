"""Offline forecast result tests: invoke directly, without DB integration fixtures."""
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.repositories.forecasts import ForecastRepository, ForecastReadError
from app.services.errors import BadRequest
from app.services.forecasts import ForecastService, ForecastUnavailable


class ForecastTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.row = {"Date": "2026-09-18", "ticker": "AAPL", "model": "Ridge alpha=100",
                    "predicted_return_10d": "0.01", "lower_return": "-0.05", "upper_return": "0.07",
                    "uncertainty_width_pp": "12", "nominal_coverage": "0.9",
                    "forecast_horizon_sessions": "10", "stale_snapshot": "False",
                    "generated_at_utc": "2026-10-08T00:00:00+00:00",
                    "calibration_latest_outcome": "2025-12-31"}
        self.report = {"metadata": {"selected_model": "Ridge alpha=100", "as_of": "2026-09-18"},
                       "calibration": {"coverage": 0.9, "latest_outcome": "2025-12-31"},
                       "evaluation": {"interval_coverage": 0.89, "MAE_pp": 4.6}}
        self.write()
        self.service = ForecastService(ForecastRepository(self.directory),
                                       now=lambda: datetime(2026, 10, 8, 1, tzinfo=timezone.utc))

    def write(self, rows=None):
        with (self.directory / "forecasts.csv").open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(self.row))
            writer.writeheader()
            writer.writerows(rows or [self.row])
        (self.directory / "report.json").write_text(json.dumps(self.report))

    def test_only_selected_tickers_and_missing_availability(self):
        extra = dict(self.row, ticker="MSFT")
        self.write([self.row, extra])
        snapshot = self.service.get_snapshot(["CEG", "AAPL"])
        self.assertEqual([item.ticker for item in snapshot.forecasts], ["AAPL"])
        self.assertEqual(snapshot.unavailable_tickers, ["CEG"])
        self.assertEqual(snapshot.selected_tickers, ["CEG", "AAPL"])
        self.assertTrue(snapshot.forecasts[0].stale_snapshot)
        self.assertEqual(snapshot.forecasts[0].data_age_calendar_days, 20)
        self.assertEqual(snapshot.status, "experimental_offline_snapshot")
        self.assertEqual(snapshot.empirical_coverage, 0.89)
        self.assertNotIn(str(self.directory), snapshot.model_dump_json())

    def test_unavailable_selected_can_have_empty_forecasts(self):
        snapshot = self.service.get_snapshot(["CEG"])
        self.assertEqual(snapshot.forecasts, [])
        self.assertEqual(snapshot.unavailable_tickers, ["CEG"])

    def test_invalid_selections(self):
        for selection in ([], ["AAPL", "AAPL"], ["aapl"], ["AAPL;DROP"], [None]):
            with self.assertRaises(BadRequest):
                self.service.get_snapshot(selection)

    def test_bad_artifacts_fail_closed_without_paths(self):
        for key, value in (("uncertainty_width_pp", "8"), ("predicted_return_10d", "nan"),
                           ("model", "Wrong"), ("nominal_coverage", "0.8"),
                           ("Date", "2030-01-01"), ("lower_return", "0.1"),
                           ("ticker", "invalid ticker"), ("forecast_horizon_sessions", "1")):
            with self.subTest(key=key):
                rows = [dict(self.row, **{key: value})]
                self.write(rows)
                with self.assertRaises(ForecastUnavailable) as error:
                    self.service.get_snapshot(["AAPL"])
                self.assertNotIn(str(self.directory), str(error.exception))

    def test_unselected_invalid_data_still_rejected(self):
        self.write([self.row, dict(self.row, ticker="MSFT", uncertainty_width_pp="bad")])
        with self.assertRaises(ForecastUnavailable):
            self.service.get_snapshot(["AAPL"])

    def test_duplicate_results_and_missing_config(self):
        self.write([self.row, self.row])
        with self.assertRaises(ForecastUnavailable):
            self.service.get_snapshot(["AAPL"])
        with self.assertRaises(ForecastUnavailable):
            ForecastService(ForecastRepository(None)).get_snapshot(["AAPL"])

    def test_prediction_report_without_evaluation(self):
        self.report["model_metadata"] = self.report.pop("metadata")
        self.report.pop("evaluation")
        self.write()
        self.assertIsNone(self.service.get_snapshot(["AAPL"]).empirical_coverage)

    def test_run_timestamp_mismatch(self):
        self.report["generated_at_utc"] = "2026-10-07T00:00:00+00:00"
        self.write()
        with self.assertRaises(ForecastUnavailable):
            self.service.get_snapshot(["AAPL"])

    def test_changed_or_oversize_files_rejected(self):
        repository = ForecastRepository(self.directory)
        with patch.object(repository, "_stamp", side_effect=range(8)):
            with self.assertRaises(ForecastReadError):
                repository.read()
        (self.directory / "forecasts.csv").write_bytes(b"x" * 2_000_001)
        with self.assertRaises(ForecastReadError):
            repository.read()


if __name__ == "__main__":
    unittest.main()
