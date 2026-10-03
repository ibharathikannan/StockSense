"""Migration CLI errors must never expose passwords or failed document contents."""
import pytest

from data.shared_data import __main__ as cli


def test_missing_connection_settings_do_not_connect(tmp_path, monkeypatch, capsys):
    pytest.importorskip("psycopg")
    for key in ("PGHOST", "PGDATABASE", "PGUSER"):
        monkeypatch.delenv(key, raising=False)
    assert cli.main(["postgres-import", "--env-file", str(tmp_path / "absent.env")]) == 1
    assert "Configure PGHOST, PGDATABASE, PGUSER" in capsys.readouterr().err


def test_driver_error_is_sanitized(tmp_path, monkeypatch, capsys):
    psycopg = pytest.importorskip("psycopg")
    monkeypatch.setenv("PGHOST", "test.example")
    monkeypatch.setenv("PGUSER", "test")
    monkeypatch.setenv("PGDATABASE", "test")
    monkeypatch.setattr(cli, "inventory", lambda *args: object())
    def fail(**kwargs):
        raise psycopg.OperationalError("password=private-password; failed row private-document")
    monkeypatch.setattr(psycopg, "connect", fail)
    assert cli.main(["postgres-import", "--env-file", str(tmp_path / "absent.env")]) == 1
    output = capsys.readouterr()
    assert "PostgreSQL operation failed" in output.err
    assert "private-password" not in output.err + output.out
    assert "private-document" not in output.err + output.out
