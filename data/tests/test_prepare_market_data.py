"""Regression tests for local market candidate preparation."""

import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from build_features import build_feature_dataset
from prepare_market_data import file_hash, prepare


class PrepareMarketDataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        dates = pd.bdate_range("2021-09-01", periods=24)
        rows = []
        for ticker, base in (("AAA", 100), ("SPY", 200), ("^VIX", 20)):
            for index, date in enumerate(dates):
                close = base + index
                rows.append({
                    "Date": date, "ticker": ticker, "Open": close,
                    "High": close + 1, "Low": close - 1, "Close": close,
                    "Adj Close": float(close), "Volume": 1000 + index,
                    "Dividends": 0.0, "Stock Splits": 0.0,
                })
        self.prices = pd.DataFrame(rows)
        self.universe = pd.DataFrame({
            "ticker": ["AAA", "SPY", "^VIX"],
            "forecast_eligible": [True, False, False],
            "asset_type": ["stock", "etf", "index"],
            "category": ["test", "test", "context"],
            "sector": ["test", "test", "context"],
        })
        macro_rows = []
        for series, lag in (("DFF", 1), ("DGS10", 1), ("VIXCLS", 0), ("CPIAUCSL", 50)):
            macro_rows.append({
                "series_id": series, "series_name": series, "frequency": "daily",
                "observation_date": pd.Timestamp("2021-07-01"), "value": 2.0,
                "available_date": pd.Timestamp("2021-07-01") + pd.Timedelta(days=lag),
                "realtime_end": pd.NaT,
            })
        self.macro = pd.DataFrame(macro_rows)
        self.paths = {
            "prices": self.root / "prices.parquet",
            "macro": self.root / "macro.parquet",
            "universe": self.root / "universe.csv",
            "baseline": self.root / "baseline.parquet",
        }
        self.prices.to_parquet(self.paths["prices"], index=False)
        self.macro.to_parquet(self.paths["macro"], index=False)
        self.universe.to_csv(self.paths["universe"], index=False)
        build_feature_dataset(self.prices, self.universe).to_parquet(self.paths["baseline"], index=False)

    def run_prepare(self):
        return prepare(
            self.paths["prices"], self.paths["macro"],
            self.paths["universe"], self.paths["baseline"],
            self.root / "artifacts",
        )

    def test_writes_candidates_and_manifest_without_changing_sources(self):
        before = {key: file_hash(path) for key, path in self.paths.items()}
        manifest = self.run_prepare()
        self.assertEqual({key: file_hash(path) for key, path in self.paths.items()}, before)
        self.assertEqual(manifest["eligibility"]["forecast_tickers"], ["AAA"])
        self.assertEqual(manifest["target_validation"]["labeled_rows"], 14)
        self.assertEqual(manifest["target_validation"]["unlabeled_rows"], 10)
        self.assertTrue(manifest["sources"]["committed_features"]["matches_price_only_candidate"])
        self.assertIn("manual CSV import pattern", manifest["sources"]["macro"]["provenance"]["inference"])
        price = pd.read_parquet(self.root / "artifacts" / "price_only_features.parquet")
        macro = pd.read_parquet(self.root / "artifacts" / "macro_features.parquet")
        self.assertNotIn("federal_funds_rate", price)
        self.assertIn("federal_funds_rate", macro)
        self.assertTrue(np.array_equal(price["target_return_10d"].isna(), macro["target_return_10d"].isna()))
        self.assertTrue((self.root / "artifacts" / "manifest.json").exists())

    def test_rejects_duplicate_source_prices(self):
        duplicate = pd.concat([self.prices, self.prices.iloc[[0]]], ignore_index=True)
        duplicate.to_parquet(self.paths["prices"], index=False)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.run_prepare()


if __name__ == "__main__":
    unittest.main()
