import importlib.util
from pathlib import Path
import tempfile
import unittest

import pandas as pd


MODULE_PATH = Path(__file__).resolve().parents[1] / "import_manual_macro_data.py"
SPEC = importlib.util.spec_from_file_location("import_manual_macro_data", MODULE_PATH)
manual_macro = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(manual_macro)


class ImportManualMacroDataTests(unittest.TestCase):
    def test_load_series_applies_conservative_availability_lag(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "CPIAUCSL.csv"
            pd.DataFrame(
                {
                    "observation_date": ["2025-09-01", "2025-10-01"],
                    "CPIAUCSL": [325.0, None],
                }
            ).to_csv(path, index=False)

            result = manual_macro.load_series(Path(directory), "CPIAUCSL")

        self.assertEqual(result["available_date"].dt.strftime("%Y-%m-%d").tolist(), [
            "2025-10-21",
            "2025-11-20",
        ])
        self.assertEqual(int(result["value"].isna().sum()), 1)

    def test_daily_market_holiday_blanks_are_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "DGS10.csv"
            pd.DataFrame(
                {
                    "observation_date": ["2025-07-03", "2025-07-04"],
                    "DGS10": [4.3, None],
                }
            ).to_csv(path, index=False)

            result = manual_macro.load_series(Path(directory), "DGS10")

        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["available_date"].strftime("%Y-%m-%d"), "2025-07-04")


if __name__ == "__main__":
    unittest.main()
