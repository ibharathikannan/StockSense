"""Read bounded precomputed CSV/JSON results; never load executable model artifacts."""
import csv
import io
import json
from pathlib import Path


class ForecastReadError(ValueError):
    pass


class ForecastRepository:
    def __init__(self, directory: Path | None):
        self._directory = directory

    @staticmethod
    def _stamp(path: Path):
        info = path.stat()
        return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)

    @staticmethod
    def _read(path: Path, limit: int) -> bytes:
        if not path.is_file() or path.stat().st_size > limit:
            raise ForecastReadError("Forecast results unavailable")
        with path.open("rb") as stream:
            data = stream.read(limit + 1)
        if len(data) > limit:
            raise ForecastReadError("Forecast results unavailable")
        return data

    def read(self) -> tuple[list[dict[str, str]], dict]:
        if self._directory is None:
            raise ForecastReadError("Forecast results unavailable")
        try:
            paths = (self._directory / "forecasts.csv", self._directory / "report.json")
            for _ in range(2):
                before = tuple(self._stamp(path) for path in paths)
                csv_bytes = self._read(paths[0], 2_000_000)
                json_bytes = self._read(paths[1], 5_000_000)
                if before != tuple(self._stamp(path) for path in paths):
                    continue
                reader = csv.DictReader(io.StringIO(csv_bytes.decode("utf-8")))
                if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)):
                    raise ForecastReadError("Forecast results unavailable")
                rows = list(reader)
                if not 1 <= len(rows) <= 500 or any(None in row or None in row.values() for row in rows):
                    raise ForecastReadError("Forecast results unavailable")
                report = json.loads(json_bytes)
                if not isinstance(report, dict):
                    raise ForecastReadError("Forecast results unavailable")
                return rows, report
        except (OSError, UnicodeError, ValueError, csv.Error):
            raise ForecastReadError("Forecast results unavailable") from None
        raise ForecastReadError("Forecast results unavailable")
