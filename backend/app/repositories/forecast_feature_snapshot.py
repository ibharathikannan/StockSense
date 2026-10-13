"""Read a bounded, hash-bound deployment feature snapshot without numerical SQL."""
from __future__ import annotations

import csv
from datetime import date
import hashlib
import io
import json
import math
from pathlib import Path
import re

from starlette.concurrency import run_in_threadpool

from app.repositories.forecasts import ForecastReadError, ForecastRepository


class SnapshotFeatureRepository:
    def __init__(self, directory: Path):
        self._directory = directory

    async def read(self, tickers: list[str]) -> dict:
        return await run_in_threadpool(self._read, tickers)

    def _read(self, tickers: list[str]) -> dict:
        try:
            # Share the offline feature contract, without importing training or
            # connecting to a numerical database. The deployment includes data/.
            from data.forecasting.inputs import RELATIVE_FEATURES

            names = list(RELATIVE_FEATURES)
            paths = (self._directory / "inference_features.csv", self._directory / "manifest.json")
            for _ in range(2):
                before = tuple(ForecastRepository._stamp(path) for path in paths)
                csv_bytes = ForecastRepository._read(paths[0], 2_000_000)
                manifest_bytes = ForecastRepository._read(paths[1], 5_000_000)
                if before != tuple(ForecastRepository._stamp(path) for path in paths):
                    continue
                manifest = json.loads(manifest_bytes)
                if not isinstance(manifest, dict) or manifest.get("inference_feature_names") != names:
                    raise ValueError("Invalid feature contract")
                model_hash = manifest.get("model_sha256")
                if not isinstance(model_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", model_hash):
                    raise ValueError("Invalid model identity")
                expected_hash = manifest.get("inference_features_sha256")
                if (not isinstance(expected_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_hash)
                    or hashlib.sha256(csv_bytes).hexdigest() != expected_hash):
                    raise ValueError("Feature hash mismatch")
                as_of = date.fromisoformat(manifest["feature_as_of"])
                if as_of.isoformat() != manifest["feature_as_of"]:
                    raise ValueError("Invalid feature snapshot date")
                reader = csv.DictReader(io.StringIO(csv_bytes.decode("utf-8")))
                if reader.fieldnames != ["Date", "ticker", *names]:
                    raise ValueError("Invalid feature columns")
                prepared, seen, dates = [], set(), []
                selected = set(tickers)
                for row in reader:
                    if None in row or None in row.values() or len(seen) >= 500:
                        raise ValueError("Malformed or oversized feature snapshot")
                    ticker = row["ticker"]
                    if not re.fullmatch(r"[A-Z0-9][A-Z0-9.\-^=]{0,15}", ticker) or ticker in seen:
                        raise ValueError("Invalid or duplicate feature ticker")
                    seen.add(ticker)
                    origin = date.fromisoformat(row["Date"])
                    if origin.isoformat() != row["Date"]:
                        raise ValueError("Invalid feature origin")
                    dates.append(origin)
                    item = {"Date": origin.isoformat(), "ticker": ticker}
                    for name in names:
                        value = row[name]
                        if value.strip().lower() in {"", "nan"} and name in {"rsi_14", "volume_change_1d"}:
                            number = float("nan")
                        else:
                            number = float(value)
                            if not math.isfinite(number):
                                raise ValueError("Nonfinite snapshot predictor")
                        item[name] = number
                    if ticker in selected:
                        prepared.append(item)
                if not dates or max(dates) != as_of:
                    raise ValueError("Snapshot date does not match origins")
                # Latest per asset may be older than the maximum snapshot date;
                # inference service enforces forecast-time validity and staleness.
                by_ticker = {row["ticker"]: row for row in prepared}
                return {"prepared": [by_ticker[ticker] for ticker in tickers if ticker in by_ticker],
                        "snapshot_as_of": as_of.isoformat(), "model_sha256": model_hash}
        except (OSError, UnicodeError, ValueError, TypeError, KeyError, ImportError, csv.Error):
            raise ForecastReadError("Forecast feature snapshot unavailable") from None
        raise ForecastReadError("Forecast feature snapshot unavailable")
