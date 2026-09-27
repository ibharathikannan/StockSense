import importlib.util
from io import BytesIO
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.error import HTTPError


MODULE_PATH = Path(__file__).resolve().parents[1] / "download_macro_data.py"
SPEC = importlib.util.spec_from_file_location("download_macro_data", MODULE_PATH)
macro = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(macro)


class FakeResponse:
    def __init__(self, payload: bytes):
        self.payload = BytesIO(payload)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, *args):
        return self.payload.read(*args)


class DownloadMacroDataTests(unittest.TestCase):
    def test_rate_limit_retry_honors_retry_after(self):
        rate_limit_error = HTTPError(
            url="https://api.stlouisfed.org/fred/series/observations",
            code=429,
            msg="Too Many Requests",
            hdrs={"Retry-After": "17"},
            fp=None,
        )
        success = FakeResponse(b'{"observations": [{"date": "2024-01-01"}]}')

        with (
            patch.object(macro, "urlopen", side_effect=[rate_limit_error, success]),
            patch.object(macro.time, "sleep") as sleep,
        ):
            observations = macro.download_series_chunk(
                "CPIAUCSL", "test-key", "2024-01-01", "2024-12-31"
            )

        self.assertEqual(observations, [{"date": "2024-01-01"}])
        sleep.assert_called_once_with(17.0)

    def test_date_ranges_use_small_quarterly_vintage_queries(self):
        ranges = macro.date_ranges("2020-09-01", "2026-09-22", "daily")

        self.assertEqual(len(ranges), 25)
        self.assertEqual(ranges[:2], [
            ("2020-09-01", "2020-09-30"),
            ("2020-10-01", "2020-12-31"),
        ])
        self.assertEqual(ranges[-1], ("2026-07-01", "2026-09-21"))

    def test_monthly_series_uses_the_same_reliable_query_size(self):
        self.assertEqual(
            macro.date_ranges("2020-09-01", "2026-09-22", "monthly"),
            macro.date_ranges("2020-09-01", "2026-09-22", "daily"),
        )


if __name__ == "__main__":
    unittest.main()
