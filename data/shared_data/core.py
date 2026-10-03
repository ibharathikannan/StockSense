"""Inventory and query schemas for offline StockSense datasets."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath

import pyarrow as pa
import pyarrow.parquet as pq


class SharedDataError(ValueError):
    """Actionable validation error safe to display without service credentials."""


FORMATS = {".parquet", ".jsonl", ".json", ".csv", ".html", ".htm", ".txt", ".xml", ".pdf"}
TABLE_NAMES = {
    "raw/historical_prices.parquet": "historical_prices",
    "raw/macro_indicators.parquet": "macro_indicators",
    "artifacts/sec/documents.jsonl": "sec_documents",
    "artifacts/news/documents.jsonl": "news_documents",
    "artifacts/prepared/documents.jsonl": "prepared_documents",
    "artifacts/prepared/chunks.jsonl": "prepared_chunks",
    "artifacts/prepared/sentiment.jsonl": "prepared_sentiment",
    "artifacts/prepared/sentiment_aggregates.jsonl": "prepared_sentiment_aggregates",
    "artifacts/market/price_only_features.parquet": "price_only_features",
    "artifacts/market/macro_features.parquet": "macro_features",
    "processed/forecast_features.parquet": "forecast_features",
}
DATE_FIELDS = ("published_at", "available_at", "fetched_at", "updated_at", "accepted_at", "as_of")
TEXT_FIELDS = ("document_id", "chunk_id", "source_type", "provider", "provider_id", "ticker",
               "source_url", "title", "text", "content_hash", "section", "form", "accession", "status")
JSON_SCHEMA = pa.schema(
    [pa.field(name, pa.string()) for name in TEXT_FIELDS]
    + [pa.field("tickers", pa.list_(pa.string()))]
    + [pa.field(name, pa.timestamp("us", tz="UTC")) for name in DATE_FIELDS]
    + [pa.field("payload_json", pa.large_string())]
)


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_path(value: str) -> str:
    path = PurePosixPath(value)
    if (not value or "\\" in value or path.is_absolute() or ":" in value
            or any(part in {"", ".", ".."} for part in value.split("/"))):
        raise SharedDataError("Unsafe dataset path")
    return value


def json_records(path: Path):
    with path.open(encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            record = json.loads(line)
            if not isinstance(record, dict):
                raise SharedDataError(f"JSONL line {number} must be an object")
            yield record


def query_record(record: dict) -> dict:
    row = {}
    for name in TEXT_FIELDS:
        value = record.get(name)
        if value is not None and not isinstance(value, (str, int)):
            raise SharedDataError(f"Invalid query field: {name}")
        row[name] = str(value) if value is not None else None
    tickers = record.get("tickers")
    if tickers is not None and (not isinstance(tickers, list) or any(not isinstance(t, str) for t in tickers)):
        raise SharedDataError("tickers must be a list of strings")
    row["tickers"] = tickers
    for name in DATE_FIELDS:
        value = record.get(name)
        if value is None:
            row[name] = None
        else:
            if not isinstance(value, str):
                raise SharedDataError(f"Invalid timestamp: {name}")
            stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                raise SharedDataError(f"Timestamp must include a timezone: {name}")
            row[name] = stamp.astimezone(timezone.utc)
    row["payload_json"] = json.dumps(record, ensure_ascii=False, allow_nan=False)
    return row


@dataclass(frozen=True)
class FileEntry:
    path: str
    local_path: Path
    category: str
    sha256: str
    size: int

    def manifest(self):
        return {"path": self.path, "category": self.category, "sha256": self.sha256,
                "size": self.size}


@dataclass(frozen=True)
class TableSpec:
    name: str
    file_path: str
    rows: int
    schema: str


@dataclass
class Inventory:
    files: list[FileEntry]
    tables: list[TableSpec]

    def manifest(self):
        return {"format_version": 1, "files": [item.manifest() for item in self.files],
                "tables": [asdict(table) for table in self.tables]}


def inventory(source_root: Path, extra_raw_root: Path | None = None) -> Inventory:
    source_root = Path(source_root)
    if not source_root.is_dir():
        raise SharedDataError("Source root must be an existing data directory")
    entries: dict[str, FileEntry] = {}

    def add_tree(base: Path, prefix: str, category: str):
        if not base.exists():
            return
        for directory, dirs, filenames in os.walk(base, followlinks=False):
            dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d != "__pycache__"
                             and not (Path(directory) / d).is_symlink())
            for filename in sorted(filenames):
                local = Path(directory) / filename
                if filename.startswith(".") or local.is_symlink() or local.suffix.lower() not in FORMATS:
                    continue
                # Only dataset formats within the selected data roots are eligible.
                relative = safe_path(f"{prefix}/{local.relative_to(base).as_posix()}")
                add_file(local, relative, category)

    def add_file(local: Path, relative: str, category: str):
        entry = FileEntry(relative, local, category, file_hash(local), local.stat().st_size)
        if relative in entries and entries[relative].sha256 != entry.sha256:
            raise SharedDataError(f"Conflicting source copies: {relative}")
        entries.setdefault(relative, entry)

    add_tree(source_root / "raw", "raw", "source")
    # CSV copies of canonical Parquets are local conveniences, not separate sources.
    for relative in list(entries):
        if relative.endswith(".csv") and relative[:-4] + ".parquet" in entries:
            del entries[relative]
    add_tree(source_root / "artifacts", "artifacts", "derived")
    for relative, entry in list(entries.items()):
        if relative.startswith(("artifacts/sec/", "artifacts/news/")):
            entries[relative] = FileEntry(entry.path, entry.local_path, "source", entry.sha256, entry.size)
    add_tree(source_root / "processed", "processed", "derived")
    for relative in list(entries):
        if relative.endswith(".csv") and relative[:-4] + ".parquet" in entries:
            del entries[relative]
    universe = source_root / "asset_universe.csv"
    if universe.is_file() and not universe.is_symlink():
        add_file(universe, "asset_universe.csv", "source")
    if extra_raw_root is not None:
        extra_raw_root = Path(extra_raw_root)
        if not extra_raw_root.is_dir():
            raise SharedDataError("Extra raw root must be an existing directory")
        add_tree(extra_raw_root, "raw", "source")
        for relative in list(entries):
            if relative.endswith(".csv") and relative[:-4] + ".parquet" in entries:
                del entries[relative]
    tables = []
    for relative, name in TABLE_NAMES.items():
        if relative not in entries:
            continue
        path = entries[relative].local_path
        if path.suffix == ".parquet":
            parquet = pq.ParquetFile(path)
            rows, schema = parquet.metadata.num_rows, parquet.schema_arrow
        else:
            rows = sum(1 for record in json_records(path) if query_record(record) is not None)
            schema = JSON_SCHEMA
        tables.append(TableSpec(name, relative, rows, str(schema)))
    files = sorted(entries.values(), key=lambda item: item.path)
    if not files:
        raise SharedDataError("No datasets found")
    return Inventory(files, tables)
