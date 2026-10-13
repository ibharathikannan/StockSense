"""Manual retraining contracts without network calls or production writes."""
import sys
from types import SimpleNamespace

import pandas as pd
import pytest

from data.forecasting import local_retrain as module


@pytest.mark.parametrize("value", ["NaT", "2021-01-01T12:00", "2021-01-01T00:00Z", "2020-09-01", "2099-01-01"])
def test_invalid_completed_dates(value):
    with pytest.raises(ValueError):
        module.completed_date(value)


def test_yahoo_scope_dates_and_failure_are_explicit(monkeypatch):
    calls = []
    dates = pd.DatetimeIndex(["2024-12-30", "2024-12-31"], tz="America/New_York", name="Date")
    raw = pd.DataFrame({"Open": 10, "High": 11, "Low": 9, "Close": 10,
        "Adj Close": 10, "Volume": 100}, index=dates)
    class Ticker:
        def __init__(self, ticker): self.ticker = ticker
        def history(self, **kwargs):
            calls.append((self.ticker, kwargs))
            return raw.copy()
    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(Ticker=Ticker))
    universe = pd.DataFrame({"ticker": ["AAPL", "SPY", "BAD"], "forecast_eligible": [True, True, False]})
    actual = module.download_prices(universe, "2024-12-31")
    assert set(actual.ticker) == {"AAPL", "SPY", "^VIX"}
    assert actual.Date.dt.tz is None
    assert all(options == {"start": "2020-09-01", "end": "2025-01-01", "interval": "1d", "auto_adjust": False, "actions": True} for _, options in calls)
    raw.drop(raw.index, inplace=True)
    with pytest.raises(ValueError, match="AAPL"):
        module.download_prices(universe, "2024-12-31")


def test_no_output_for_invalid_destination_or_source(tmp_path):
    kwargs = dict(as_of="2024-12-31", output_dir=tmp_path / "outside", tuning_start="2023-01-01",
        calibration_start="2023-07-01", evaluation_start="2024-01-01")
    with pytest.raises(ValueError, match="ignored"):
        module.run(**kwargs, download_yahoo=True)
    kwargs["output_dir"] = module.DATA / "artifacts/forecasting/test-absent-output"
    with pytest.raises(ValueError, match="exactly one"):
        module.run(**kwargs)
    assert not kwargs["output_dir"].exists()


def test_local_flow_uses_bounded_refit_and_package_without_sql(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(module, "DATA", data)
    universe = tmp_path / "universe.csv"
    universe.write_text("ticker,forecast_eligible\nAAPL,true\n")
    prices = tmp_path / "prices.parquet"
    pd.DataFrame({"Date": pd.to_datetime(["2024-12-30", "2024-12-31", "2025-01-02"]),
                  "ticker": ["AAPL"] * 3}).to_parquet(prices)
    frame = pd.DataFrame({"Date": pd.to_datetime(["2024-12-30", "2024-12-31"]), "ticker": ["AAPL"] * 2})
    calls = {}
    def build(raw, universe, macro_data):
        assert macro_data is None
        assert raw.Date.max() == pd.Timestamp("2024-12-31")
        return raw
    monkeypatch.setattr(module, "build_feature_dataset", build)
    monkeypatch.setattr(module, "build_inputs", lambda *args, **kwargs: frame)
    bundle = SimpleNamespace(metadata={"eligible_tickers": ["AAPL"]})
    def train(actual, **kwargs):
        assert actual is frame
        calls.update(kwargs)
        return bundle
    monkeypatch.setattr(module, "train_model", train)
    def export(actual, selected, output, provenance, *, evaluation):
        assert actual is bundle and selected is frame and evaluation is None
        assert len(provenance["prices_sha256"]) == 64
        assert provenance["provider"] == "local_parquet"
        assert not output.exists()
        return {"exported": True}
    monkeypatch.setitem(sys.modules, "data.forecasting.package", SimpleNamespace(export_package=export))
    result = module.run(as_of="2024-12-31", output_dir=data / "artifacts/forecasting/new-run",
        tuning_start="2023-01-01", calibration_start="2023-07-01", evaluation_start="2024-01-01",
        prices=prices, universe_path=universe)
    assert result == {"exported": True}
    assert calls["model"] == "xgboost" and calls["refit_selected"] is True
    assert calls["xgboost_grid"] == module.GRID
