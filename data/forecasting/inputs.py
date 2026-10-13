"""Validated, past-only relative forecasting inputs; source frames are never mutated."""
from __future__ import annotations

import numpy as np
import pandas as pd

RETAINED_FEATURES = (
    "return_1d", "return_5d", "return_20d", "log_return_1d", "rsi_14",
    "rolling_volatility_20", "bollinger_position_20", "return_1d_lag_1",
    "return_1d_lag_5", "return_1d_lag_10", "volume_change_1d",
    "volume_ratio_20", "spy_return_1d", "spy_return_5d", "vix_close",
)
RELATIVE_FEATURES = RETAINED_FEATURES + tuple(
    f"price_vs_{name}" for name in ("sma_5", "sma_20", "sma_50", "sma_200", "ema_12", "ema_26")
) + ("macd_relative", "macd_signal_relative", "macd_histogram_relative",
     "atr_14_relative", "bollinger_width_relative", "return_10d")


def _dated(frame: pd.DataFrame, name: str) -> pd.DataFrame:
    frame = frame.copy()
    if not {"Date", "ticker"}.issubset(frame.columns):
        raise ValueError(f"{name} requires Date and ticker")
    try:
        frame["Date"] = pd.to_datetime(frame["Date"], errors="raise").astype("datetime64[ns]")
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{name} contains invalid or timezone-aware dates") from exc
    if frame[["Date", "ticker"]].isna().any().any():
        raise ValueError(f"{name} contains missing identifiers")
    if frame.duplicated(["ticker", "Date"]).any():
        raise ValueError(f"{name} contains duplicate ticker/date rows")
    return frame.sort_values(["ticker", "Date"]).reset_index(drop=True)


def build_inputs(features: pd.DataFrame, prices: pd.DataFrame, universe: pd.DataFrame,
                 *, as_of: str | None = None) -> pd.DataFrame:
    """Validate source labels, derive relative predictors, and censor unknown outcomes.

    Features are assumed to be available after the session's close. ``as_of`` is
    an inclusive completed-session date, not an intraday availability timestamp.
    """
    if not {"ticker", "forecast_eligible"}.issubset(universe.columns):
        raise ValueError("universe requires ticker and forecast_eligible")
    if universe["ticker"].duplicated().any():
        raise ValueError("universe contains duplicate tickers")
    eligible = universe.loc[universe["forecast_eligible"].astype(str).str.lower().eq("true"), "ticker"]
    f = _dated(features, "features")
    p = _dated(prices, "prices")
    f = f.loc[f["ticker"].isin(eligible)].copy()
    if f.empty:
        raise ValueError("No forecast-eligible feature rows")
    needed = set(RETAINED_FEATURES) | {"Adj Close", "target_return_10d", "is_training_row", "macd", "macd_signal", "macd_histogram", "atr_14", "bollinger_upper_20", "bollinger_lower_20"} | {"sma_5", "sma_20", "sma_50", "sma_200", "ema_12", "ema_26"}
    if needed - set(f.columns):
        raise ValueError(f"features missing required columns: {sorted(needed - set(f.columns))}")
    raw_needed = {"Adj Close", "Open", "High", "Low", "Close", "Volume"}
    if raw_needed - set(p.columns):
        raise ValueError(f"prices missing required columns: {sorted(raw_needed - set(p.columns))}")
    relevant = p.loc[p["ticker"].isin(set(f["ticker"]) | {"SPY"})].copy()
    raw_values = relevant[list(raw_needed)].to_numpy(dtype=float)
    if not np.isfinite(raw_values).all() or (relevant[["Adj Close", "Open", "High", "Low", "Close"]] <= 0).any().any() or (relevant["Volume"] < 0).any():
        raise ValueError("Raw prices require finite positive OHLC/adjusted prices and nonnegative volume")
    if (relevant["Low"] > relevant[["Open", "Close"]].min(axis=1)).any() or (relevant["High"] < relevant[["Open", "Close"]].max(axis=1)).any():
        raise ValueError("Raw OHLC bounds are inconsistent")
    calendar = relevant.loc[relevant["ticker"].eq("SPY"), "Date"]
    if calendar.empty:
        raise ValueError("SPY prices required to validate trading-session coverage")
    derived = []
    for ticker in f["ticker"].unique():
        raw = relevant.loc[relevant["ticker"].eq(ticker)].copy()
        if raw.empty:
            raise ValueError(f"Missing raw prices for {ticker}")
        expected = calendar.loc[calendar.between(raw["Date"].min(), raw["Date"].max())]
        if not pd.Index(expected).isin(raw["Date"]).all() or not raw["Date"].isin(calendar).all():
            raise ValueError(f"Missing or unexpected trading sessions for {ticker}")
        close = raw["Adj Close"]
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rsi = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
        rsi = rsi.mask(loss.eq(0) & gain.gt(0), 100).mask(loss.eq(0) & gain.eq(0), 50)
        previous_volume = raw["Volume"].shift(1).replace(0, np.nan)
        derived.append(pd.DataFrame({"ticker": ticker, "Date": raw["Date"],
            "source_price": close, "expected_target": close.shift(-10) / close - 1,
            "label_end_date": raw["Date"].shift(-10), "corrected_rsi": rsi,
            "safe_volume_change": raw["Volume"] / previous_volume - 1,
            "return_10d": close / close.shift(10) - 1}))
    f = f.merge(pd.concat(derived), on=["ticker", "Date"], how="left", validate="one_to_one")
    if not np.isclose(f["Adj Close"], f["source_price"], rtol=1e-9, atol=1e-10, equal_nan=False).all():
        raise ValueError("Feature adjusted prices do not match raw prices")
    if not np.isclose(f["target_return_10d"], f["expected_target"], rtol=1e-8, atol=1e-10, equal_nan=True).all():
        raise ValueError("Stored target_return_10d does not match raw 10-session returns")
    if not f["is_training_row"].isin([True, False]).all() or not f["is_training_row"].eq(f["expected_target"].notna()).all():
        raise ValueError("is_training_row does not match target availability")
    if as_of is not None:
        cutoff = pd.Timestamp(as_of)
        if pd.isna(cutoff) or cutoff.tzinfo is not None or cutoff != cutoff.normalize():
            raise ValueError("as_of must be a timezone-naive session date")
        f = f.loc[f["Date"].le(cutoff)].copy()
        unknown = f["label_end_date"].gt(cutoff)
        f.loc[unknown, ["target_return_10d", "label_end_date"]] = [np.nan, pd.NaT]
        f["is_training_row"] = f["target_return_10d"].notna()
    f["rsi_14"] = f["corrected_rsi"]
    f["volume_change_1d"] = f["safe_volume_change"]
    for name in ("sma_5", "sma_20", "sma_50", "sma_200", "ema_12", "ema_26"):
        f[f"price_vs_{name}"] = f["Adj Close"] / f[name] - 1
    for name in ("macd", "macd_signal", "macd_histogram", "atr_14"):
        f[f"{name}_relative"] = f[name] / f["Adj Close"]
    f["bollinger_width_relative"] = (f["bollinger_upper_20"] - f["bollinger_lower_20"]) / f["Adj Close"]
    values = f[list(RELATIVE_FEATURES)].to_numpy(dtype=float)
    if np.isinf(values).any():
        raise ValueError("Forecasting predictors contain infinite values")
    strict = [c for c in RELATIVE_FEATURES if c not in {"rsi_14", "volume_change_1d"}]
    if not np.isfinite(f[strict].to_numpy(dtype=float)).all():
        raise ValueError("Forecasting predictors contain missing/invalid values beyond RSI or volume change; check warmup and market context")
    return f[["Date", "ticker", *RELATIVE_FEATURES, "target_return_10d", "label_end_date", "is_training_row"]].sort_values(["Date", "ticker"]).reset_index(drop=True)
