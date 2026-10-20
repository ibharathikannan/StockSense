"""Small shared IO utilities for the offline collectors; never log secrets."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import ssl
import tempfile
from typing import Any, Iterable
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class CollectionError(RuntimeError):
    """Sanitized request failure; deliberately excludes URLs and response bodies."""

    def __init__(self, message: str, status: int | None = None,
                 retry_after: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


def load_environment(path: str | Path | None = None) -> None:
    """Read local KEY=value settings without shell expansion or overriding exports."""
    env_path = Path(path) if path else Path(__file__).parent / ".env"
    if not env_path.exists():
        return
    for number, original in enumerate(env_path.read_text(encoding="utf-8").splitlines(), 1):
        line = original.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, separator, raw = line.partition("=")
        key = key.strip()
        if not separator or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise ValueError(f"Invalid environment entry at line {number}")
        if key not in {
            "APCA_API_KEY_ID", "APCA_API_SECRET_KEY", "ALPACA_API_KEY",
            "ALPACA_SECRET_KEY", "ALPHA_VANTAGE_API_KEY", "ALPHAVANTAGE_API_KEY",
            "MARKETAUX_SECRET_KEY", "MARKETAUX_API_KEY", "MARKETAUX_API_TOKEN",
            "SEC_USER_AGENT", "FRED_API_KEY", "HF_HOME", "HF_TOKEN",
            "PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGPASSWORD",
            "PGSSLMODE", "PGSSLROOTCERT", "PGCONNECT_TIMEOUT", "PGPASSFILE",
        }:
            continue
        raw = raw.strip()
        if raw.startswith(("'", '"')):
            try:
                tokens = shlex.split(raw, comments=True, posix=True)
            except ValueError:
                raise ValueError(f"Invalid quoted environment value at line {number}") from None
            if len(tokens) != 1:
                raise ValueError(f"Invalid quoted environment value at line {number}")
            value = tokens[0]
        else:
            value = raw.split(" #", 1)[0].strip()
        if value:
            os.environ.setdefault(key, value)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def stable_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _atomic_write(path: str | Path, text: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent,
                                         prefix=f".{target.name}.", delete=False) as stream:
            temporary = stream.name
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def atomic_write_json(path: str | Path, value: Any) -> None:
    _atomic_write(path, json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def write_jsonl(path: str | Path, records: Iterable[dict[str, Any]]) -> None:
    _atomic_write(path, "".join(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n"
                                for row in records))


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    source = Path(path)
    if not source.exists():
        return []
    result = []
    for number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"JSONL line {number} must be an object")
            result.append(value)
    return result


def fetch_text(url: str, headers: dict[str, str] | None = None, timeout: int = 30) -> str:
    try:
        import certifi
        context = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        context = ssl.create_default_context()
    try:
        with urlopen(Request(url, headers=headers or {}), timeout=timeout, context=context) as response:
            raw = response.read(40 * 1024 * 1024 + 1)
            if len(raw) > 40 * 1024 * 1024:
                raise CollectionError("Response exceeds the 40 MiB collection limit")
            return raw.decode(response.headers.get_content_charset() or "utf-8", errors="replace")
    except HTTPError as error:
        raise CollectionError(f"Provider returned HTTP {error.code}", status=error.code,
                              retry_after=error.headers.get("Retry-After")) from None
    except (URLError, TimeoutError, OSError):
        raise CollectionError("Provider connection failed or timed out") from None


def fetch_json(url: str, headers: dict[str, str] | None = None, timeout: int = 30) -> Any:
    try:
        return json.loads(fetch_text(url, headers=headers, timeout=timeout))
    except json.JSONDecodeError:
        raise CollectionError("Provider returned invalid JSON") from None
