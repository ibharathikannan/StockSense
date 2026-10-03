"""Configuration and transport checks that avoid exposing provider credentials."""

import os
from urllib.error import HTTPError, URLError

import pytest

from data import collection_common as common


def test_env_is_literal_and_exported_values_win(tmp_path, monkeypatch):
    monkeypatch.setenv("APCA_API_KEY_ID", "exported")
    monkeypatch.delenv("APCA_API_SECRET_KEY", raising=False)
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    path = tmp_path / ".env"
    path.write_text('APCA_API_KEY_ID=file\nAPCA_API_SECRET_KEY="$(echo forbidden)#literal"\nSEC_USER_AGENT="StockSense contact@example.org"\nPATH=/wrong\n')
    old_path = os.environ["PATH"]
    common.load_environment(path)
    assert os.environ["APCA_API_KEY_ID"] == "exported"
    assert os.environ["APCA_API_SECRET_KEY"] == "$(echo forbidden)#literal"
    assert os.environ["SEC_USER_AGENT"] == "StockSense contact@example.org"
    assert os.environ["PATH"] == old_path


def test_transport_error_does_not_include_secret_url(monkeypatch):
    secret_url = "https://example.org/?apikey=do-not-print"
    def fail(*args, **kwargs):
        raise HTTPError(secret_url, 429, "do-not-print", {"Retry-After": "3"}, None)
    monkeypatch.setattr(common, "urlopen", fail)
    with pytest.raises(common.CollectionError) as caught:
        common.fetch_json(secret_url)
    assert "do-not-print" not in str(caught.value)
    assert caught.value.status == 429
    assert caught.value.retry_after == "3"


def test_postgres_environment_is_literal_and_exports_win(tmp_path, monkeypatch):
    monkeypatch.setenv("PGHOST", "exported.example")
    monkeypatch.delenv("PGPASSWORD", raising=False)
    monkeypatch.delenv("PGDATABASE", raising=False)
    path = tmp_path / ".env"
    path.write_text('PGHOST=file.example\nPGDATABASE=stocksense_data\n'
                    'PGPASSWORD="$(echo forbidden)#literal"\n')
    common.load_environment(path)
    assert os.environ["PGHOST"] == "exported.example"
    assert os.environ["PGDATABASE"] == "stocksense_data"
    assert os.environ["PGPASSWORD"] == "$(echo forbidden)#literal"


def test_jsonl_roundtrip_and_reject_nonobjects(tmp_path):
    path = tmp_path / "nested" / "rows.jsonl"
    common.write_jsonl(path, [{"title": "A & B"}])
    assert common.read_jsonl(path) == [{"title": "A & B"}]
    path.write_text('[1,2]\n')
    with pytest.raises(ValueError, match="must be an object"):
        common.read_jsonl(path)
