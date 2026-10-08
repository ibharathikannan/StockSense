import numpy as np
import pandas as pd
import pytest

from data.build_features import build_feature_dataset
from data.forecasting.inputs import RELATIVE_FEATURES, build_inputs


@pytest.fixture
def sources():
    dates = pd.bdate_range("2020-09-01", periods=310)
    frames = []
    for ticker in ("AAPL", "SPY", "^VIX"):
        close = np.arange(310, dtype=float) + 100
        volume = np.full(310, 100.)
        volume[270] = 0
        frames.append(pd.DataFrame({"Date": dates, "ticker": ticker,
            "Open": close, "High": close + 1, "Low": close - 1,
            "Close": close, "Adj Close": close, "Volume": volume}))
    prices = pd.concat(frames, ignore_index=True)
    universe = pd.DataFrame({"ticker": ["AAPL", "SPY", "^VIX"],
        "forecast_eligible": [True, True, False], "asset_type": "stock",
        "category": "test", "sector": "test"})
    features = build_feature_dataset(prices, universe)
    return features, prices, universe


def test_relative_inputs_correct_rsi_volume_and_keep_latest(sources):
    f, p, u = sources
    result = build_inputs(f, p, u)
    assert len(RELATIVE_FEATURES) == 27
    assert result["rsi_14"].eq(100).all()
    assert result["volume_change_1d"].isna().sum() == 2
    assert result["target_return_10d"].isna().sum() == 20
    assert set(result["ticker"]) == {"AAPL", "SPY"}
    assert f["rsi_14"].isna().all()  # source frames are not mutated


def test_as_of_censors_outcomes_not_known_yet(sources):
    f, p, u = sources
    cutoff = p["Date"].sort_values().unique()[-20]
    result = build_inputs(f, p, u, as_of=str(pd.Timestamp(cutoff).date()))
    assert result["Date"].max() == cutoff
    assert result["label_end_date"].dropna().le(cutoff).all()
    assert result["target_return_10d"].isna().sum() == 20
    assert result["is_training_row"].eq(result["target_return_10d"].notna()).all()


@pytest.mark.parametrize("kind", ["target", "flag", "price", "duplicate", "session"])
def test_corrupt_sources_fail(sources, kind):
    f, p, u = sources
    f, p = f.copy(), p.copy()
    if kind == "target":
        f.loc[0, "target_return_10d"] += 0.1
    elif kind == "flag":
        f.loc[0, "is_training_row"] = False
    elif kind == "price":
        f.loc[0, "Adj Close"] += 1
    elif kind == "duplicate":
        f = pd.concat([f, f.iloc[[0]]])
    else:
        p = p.drop(p.loc[p["ticker"].eq("AAPL")].index[260])
    with pytest.raises(ValueError):
        build_inputs(f, p, u)


def test_eligibility_and_flat_rsi(sources):
    f, p, u = sources
    u = u.copy()
    u.loc[u["ticker"].eq("SPY"), "forecast_eligible"] = False
    aapl = p.loc[p["ticker"].eq("AAPL")].index
    p = p.copy()
    # Fourteen flat deltas produce neutral RSI while the 20-day band is nonzero.
    for column in ("Open", "High", "Low", "Close", "Adj Close"):
        offset = 1 if column == "High" else -1 if column == "Low" else 0
        p.loc[aapl[260:275], column] = 359 + offset
    f = build_feature_dataset(p, u)
    result = build_inputs(f, p, u)
    assert set(result["ticker"]) == {"AAPL"}
    assert (result["rsi_14"] == 50).any()


def test_future_stored_labels_verified_before_censoring(sources):
    f, p, u = sources
    f = f.copy()
    labeled = f.index[f["target_return_10d"].notna()]
    f.loc[labeled[-1], "target_return_10d"] += 0.2
    with pytest.raises(ValueError, match="Stored target"):
        build_inputs(f, p, u, as_of="2021-09-10")


def test_invalid_market_context_is_not_silently_imputed(sources):
    f, p, u = sources
    f = f.copy()
    f.loc[0, "spy_return_1d"] = np.nan
    with pytest.raises(ValueError, match="missing/invalid"):
        build_inputs(f, p, u)


def test_as_of_nat_rejected(sources):
    with pytest.raises(ValueError, match="as_of"):
        build_inputs(*sources, as_of="NaT")
