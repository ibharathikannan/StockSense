"""Loss-aware streaming conversion of local datasets to PostgreSQL COPY rows."""
from __future__ import annotations

from collections.abc import Iterator
import csv
from dataclasses import dataclass
import json
import math
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from .core import JSON_SCHEMA, SharedDataError, query_record


@dataclass(frozen=True)
class Column:
    name: str
    sql_type: str


def _error(path: Path, detail: str, row: int | None = None) -> SharedDataError:
    location = f" at row {row}" if row is not None else ""
    return SharedDataError(f"Dataset {path.name!r}{location}: {detail}")


def _check_names(path: Path, names: list[str]) -> None:
    if not names or any(not name or "\x00" in name or len(name.encode("utf-8")) > 63 for name in names):
        raise _error(path, "column names must be nonempty PostgreSQL identifiers of at most 63 bytes")
    if len(set(names)) != len(names):
        raise _error(path, "duplicate column names")
    if "_source_row" in names:
        raise _error(path, "reserved column name _source_row")


def _sql_type(path: Path, dtype: pa.DataType) -> str:
    if pa.types.is_boolean(dtype):
        return "boolean"
    if pa.types.is_float64(dtype):
        return "double precision"
    if pa.types.is_float32(dtype):
        return "real"
    if pa.types.is_integer(dtype):
        bits = dtype.bit_width + int(pa.types.is_unsigned_integer(dtype))
        return "smallint" if bits <= 16 else "integer" if bits <= 32 else "bigint"
    if pa.types.is_string(dtype) or pa.types.is_large_string(dtype):
        return "text"
    if pa.types.is_date(dtype):
        return "date"
    if pa.types.is_timestamp(dtype):
        return "timestamptz" if dtype.tz else "timestamp"
    raise _error(path, f"unsupported Arrow type {dtype}")


def _csv_header(path: Path, reader: csv.DictReader) -> list[str]:
    names = reader.fieldnames or []
    _check_names(path, names)
    return names


def columns_for(path: Path) -> list[Column]:
    path = Path(path)
    try:
        if path.suffix == ".parquet":
            schema = pq.ParquetFile(path).schema_arrow
            _check_names(path, schema.names)
            return [Column(field.name, _sql_type(path, field.type)) for field in schema]
        if path.suffix == ".jsonl":
            return [Column(field.name if field.name != "payload_json" else "payload",
                           "jsonb" if field.name == "payload_json" else
                           "text[]" if field.name == "tickers" else
                           "timestamptz" if pa.types.is_timestamp(field.type) else "text")
                    for field in JSON_SCHEMA]
        if path.suffix == ".csv" and path.name == "asset_universe.csv":
            with path.open(encoding="utf-8-sig", newline="") as stream:
                names = _csv_header(path, csv.DictReader(stream, strict=True))
            return [Column(name, "text") for name in names]
        raise _error(path, "unsupported queryable dataset format")
    except SharedDataError:
        raise
    except Exception:
        raise _error(path, "could not read dataset schema") from None


def _parquet_rows(path: Path):
    row_number = 0
    parquet = pq.ParquetFile(path)
    for batch in parquet.iter_batches(batch_size=4096):
        arrays = []
        for field, values in zip(batch.schema, batch.columns):
            dtype = field.type
            if pa.types.is_timestamp(dtype) and dtype.unit == "ns":
                raw = values.cast(pa.int64()).to_pylist()
                for offset, value in enumerate(raw, 1):
                    if value is not None and value % 1000:
                        raise _error(path, "timestamp has submicrosecond precision", row_number + offset)
                values = values.cast(pa.timestamp("us", tz=dtype.tz), safe=True)
            if pa.types.is_date64(dtype):
                for offset, value in enumerate(values.cast(pa.int64()).to_pylist(), 1):
                    if value is not None and value % 86_400_000:
                        raise _error(path, "date contains a non-midnight time", row_number + offset)
            if pa.types.is_integer(dtype):
                for offset, value in enumerate(values.to_pylist(), 1):
                    if value is not None and not -(2**63) <= value < 2**63:
                        raise _error(path, "integer exceeds PostgreSQL bigint range", row_number + offset)
            arrays.append(values.to_pylist())
        for values in zip(*arrays):
            row_number += 1
            if any(isinstance(value, str) and "\x00" in value for value in values):
                raise _error(path, "text contains a NUL character", row_number)
            yield tuple(values)


def _contains_nul(value) -> bool:
    if isinstance(value, str):
        return "\x00" in value
    if isinstance(value, dict):
        return any(_contains_nul(key) or _contains_nul(item) for key, item in value.items())
    if isinstance(value, list):
        return any(_contains_nul(item) for item in value)
    return False


def _json_rows(path: Path):
    try:
        from psycopg.types.json import Jsonb
    except ImportError:
        raise _error(path, "install the optional PostgreSQL driver psycopg") from None
    with path.open(encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                if not isinstance(record, dict):
                    raise ValueError()
                if "_source_row" in record:
                    raise _error(path, "reserved field name _source_row", number)
                row = query_record(record)
                # PostgreSQL JSONB cannot represent NUL, including nested payload strings.
                if _contains_nul(record):
                    raise ValueError()
                yield tuple(Jsonb(record) if field.name == "payload_json" else row[field.name]
                            for field in JSON_SCHEMA)
            except SharedDataError as exc:
                if "reserved field" in str(exc):
                    raise
                raise _error(path, "invalid JSON object or query fields", number) from None
            except Exception:
                raise _error(path, "invalid JSON object or query fields", number) from None


def rows_for(path: Path) -> Iterator[tuple]:
    """Yield COPY-ready rows while rejecting conversions that discard source values."""
    path = Path(path)
    columns_for(path)
    try:
        if path.suffix == ".parquet":
            yield from _parquet_rows(path)
        elif path.suffix == ".jsonl":
            yield from _json_rows(path)
        else:
            with path.open(encoding="utf-8-sig", newline="") as stream:
                reader = csv.DictReader(stream, strict=True)
                names = _csv_header(path, reader)
                for number, row in enumerate(reader, 2):
                    if None in row or any(row[name] is None for name in names):
                        raise _error(path, "CSV row length does not match header", number)
                    if any("\x00" in row[name] for name in names):
                        raise _error(path, "text contains a NUL character", number)
                    yield tuple(row[name] for name in names)
    except SharedDataError:
        raise
    except Exception:
        raise _error(path, "could not decode dataset rows") from None


def comparable(value):
    """Normalize source adapters and PostgreSQL values for representative checks."""
    if hasattr(value, "obj"):
        value = value.obj
    if isinstance(value, float) and math.isnan(value):
        return ("float", "nan")
    if isinstance(value, dict):
        return {key: comparable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return tuple(comparable(item) for item in value)
    return value
