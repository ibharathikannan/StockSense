"""Hash-bound snapshot adapter tests without database or provider access."""
import asyncio
import csv
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from app.repositories.forecast_feature_snapshot import SnapshotFeatureRepository
from app.repositories.forecasts import ForecastReadError
from data.forecasting.inputs import RELATIVE_FEATURES


class FeatureSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.repo = SnapshotFeatureRepository(self.directory)
        self.names = ["Date", "ticker", *RELATIVE_FEATURES]
        self.row = {"Date": "2026-09-18", "ticker": "AAPL", **dict.fromkeys(RELATIVE_FEATURES, ".1")}
        self.manifest = {"inference_feature_names": list(RELATIVE_FEATURES), "feature_as_of": "2026-09-18",
                         "model_sha256": "a" * 64}
        self.write()

    def write(self, rows=None):
        stream = io.StringIO()
        writer = csv.DictWriter(stream, fieldnames=self.names)
        writer.writeheader(); writer.writerows(rows if rows is not None else [self.row])
        payload = stream.getvalue().encode()
        (self.directory / "inference_features.csv").write_bytes(payload)
        self.manifest["inference_features_sha256"] = hashlib.sha256(payload).hexdigest()
        (self.directory / "manifest.json").write_text(json.dumps(self.manifest))

    def read(self, tickers=None):
        return asyncio.run(self.repo.read(tickers or ["AAPL"]))

    def test_selection_order_numeric_conversion_and_unknown(self):
        self.write([self.row, dict(self.row, ticker="MSFT", Date="2026-09-17")])
        result = self.read(["MSFT", "CEG", "AAPL"])
        self.assertEqual([row["ticker"] for row in result["prepared"]], ["MSFT", "AAPL"])
        self.assertEqual(result["snapshot_as_of"], "2026-09-18")
        self.assertEqual(result["model_sha256"], "a" * 64)
        self.assertEqual(result["prepared"][0]["return_1d"], .1)
        self.assertEqual(self.read(["CEG"])["prepared"], [])

    def test_hash_mismatch_and_missing_file(self):
        path = self.directory / "inference_features.csv"
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaises(ForecastReadError): self.read()
        path.unlink()
        with self.assertRaises(ForecastReadError) as error: self.read()
        self.assertNotIn(str(self.directory), str(error.exception))

    def test_duplicate_ticker_even_on_different_dates(self):
        for origin in ("2026-09-18", "2026-09-17"):
            self.write([self.row, dict(self.row, Date=origin)])
            with self.assertRaises(ForecastReadError): self.read()

    def test_nonfinite_or_missing_strict_feature_rejected(self):
        for value in ("inf", "-inf", "nan", "", "not-a-number"):
            self.write([dict(self.row, return_1d=value)])
            with self.assertRaises(ForecastReadError): self.read()
        self.write([dict(self.row, rsi_14="", volume_change_1d="nan")])
        result = self.read()
        self.assertNotEqual(result["prepared"][0]["rsi_14"], result["prepared"][0]["rsi_14"])

    def test_unselected_bad_rows_rejected(self):
        self.write([self.row, dict(self.row, ticker="MSFT", return_1d="inf")])
        with self.assertRaises(ForecastReadError): self.read()

    def test_contract_and_snapshot_date_mismatch(self):
        self.manifest["inference_feature_names"] = list(reversed(RELATIVE_FEATURES))
        self.write()
        with self.assertRaises(ForecastReadError): self.read()
        self.manifest["inference_feature_names"] = list(RELATIVE_FEATURES)
        self.manifest["feature_as_of"] = "2026-09-19"
        self.write()
        with self.assertRaises(ForecastReadError): self.read()

    def test_invalid_model_hash_rejected(self):
        for value in (None, "", "A" * 64, "short", "g" * 64):
            self.manifest["model_sha256"] = value
            self.write()
            with self.assertRaises(ForecastReadError): self.read()

    def test_extra_target_column_empty_file_or_changing_files_rejected(self):
        self.names.append("target_return_10d")
        self.write()
        with self.assertRaises(ForecastReadError): self.read()
        self.names.pop(); self.write([])
        with self.assertRaises(ForecastReadError): self.read()
        self.write()
        with patch("app.repositories.forecast_feature_snapshot.ForecastRepository._stamp", side_effect=range(8)):
            with self.assertRaises(ForecastReadError): self.read()


if __name__ == "__main__": unittest.main()
