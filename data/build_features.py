#!/usr/bin/env python3
"""Build forecasting features from the downloaded price and macro datasets."""

from pathlib import Path

import numpy as np
import pandas as pd


# --------------------------------------------------
# 1. Configuration
# --------------------------------------------------

DATA_DIR = Path(__file__).resolve().parent
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"

PRICE_PATH = RAW_DIR / "historical_prices.parquet"
MACRO_PATH = RAW_DIR / "macro_indicators.parquet"
UNIVERSE_PATH = DATA_DIR / "asset_universe.csv"

MODEL_START_DATE = "2021-09-01"
FORECAST_HORIZON = 10
TRADING_DAYS_PER_YEAR = 252


def calculate_rsi(prices: pd.Series, window: int = 14) -> pd.Series:
    price_change = prices.diff()
    average_gain = price_change.clip(lower=0).rolling(window).mean()
    average_loss = -price_change.clip(upper=0).rolling(window).mean()
    relative_strength = average_gain / average_loss.replace(0, np.nan)
    return 100 - (100 / (1 + relative_strength))


def add_ticker_features(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate indicators independently for one ticker."""
    df = df.sort_values("Date").copy()

    # yfinance supplies adjusted close only. Apply its adjustment ratio to the
    # other prices so split dates do not distort ATR or intraday ranges.
    adjustment_factor = df["Adj Close"] / df["Close"].replace(0, np.nan)
    df["Adj Open"] = df["Open"] * adjustment_factor
    df["Adj High"] = df["High"] * adjustment_factor
    df["Adj Low"] = df["Low"] * adjustment_factor

    # Returns
    df["return_1d"] = df["Adj Close"].pct_change(1)
    df["return_5d"] = df["Adj Close"].pct_change(5)
    df["return_20d"] = df["Adj Close"].pct_change(20)
    df["log_return_1d"] = np.log(df["Adj Close"] / df["Adj Close"].shift(1))

    # Moving averages
    for window in [5, 20, 50, 200]:
        df[f"sma_{window}"] = df["Adj Close"].rolling(window).mean()

    df["ema_12"] = df["Adj Close"].ewm(span=12, adjust=False).mean()
    df["ema_26"] = df["Adj Close"].ewm(span=26, adjust=False).mean()

    # RSI and MACD
    df["rsi_14"] = calculate_rsi(df["Adj Close"], window=14)
    df["macd"] = df["ema_12"] - df["ema_26"]
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["macd_histogram"] = df["macd"] - df["macd_signal"]

    # Average True Range
    previous_close = df["Adj Close"].shift(1)
    true_range = pd.concat(
        [
            df["Adj High"] - df["Adj Low"],
            (df["Adj High"] - previous_close).abs(),
            (df["Adj Low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    df["atr_14"] = true_range.rolling(14).mean()

    # Volatility and Bollinger Bands
    df["rolling_volatility_20"] = (
        df["return_1d"].rolling(20).std() * np.sqrt(TRADING_DAYS_PER_YEAR)
    )
    rolling_std_20 = df["Adj Close"].rolling(20).std()
    df["bollinger_middle_20"] = df["sma_20"]
    df["bollinger_upper_20"] = df["sma_20"] + (2 * rolling_std_20)
    df["bollinger_lower_20"] = df["sma_20"] - (2 * rolling_std_20)
    df["bollinger_position_20"] = (
        (df["Adj Close"] - df["bollinger_lower_20"])
        / (df["bollinger_upper_20"] - df["bollinger_lower_20"])
    )

    # Lag and volume features
    for lag in [1, 5, 10, 20]:
        df[f"adjusted_close_lag_{lag}"] = df["Adj Close"].shift(lag)

    for lag in [1, 5, 10]:
        df[f"return_1d_lag_{lag}"] = df["return_1d"].shift(lag)

    df["volume_change_1d"] = df["Volume"].pct_change(1)
    df["volume_sma_20"] = df["Volume"].rolling(20).mean()
    df["volume_ratio_20"] = df["Volume"] / df["volume_sma_20"].replace(0, np.nan)

    # shift(-10) uses the next 10 trading days only as the model label.
    df["target_return_10d"] = (
        df["Adj Close"].shift(-FORECAST_HORIZON) / df["Adj Close"] - 1
    )

    return df


def build_market_context(all_prices: pd.DataFrame) -> pd.DataFrame:
    """Create broad-market and volatility columns to join to every asset."""
    spy = all_prices.loc[
        all_prices["ticker"].eq("SPY"), ["Date", "Adj Close"]
    ].copy()
    spy = spy.rename(columns={"Adj Close": "spy_adjusted_close"})
    spy["spy_return_1d"] = spy["spy_adjusted_close"].pct_change(1)
    spy["spy_return_5d"] = spy["spy_adjusted_close"].pct_change(5)

    vix = all_prices.loc[
        all_prices["ticker"].eq("^VIX"), ["Date", "Close"]
    ].copy()
    vix = vix.rename(columns={"Close": "vix_close"})

    return spy.merge(vix, on="Date", how="outer").sort_values("Date")


def build_macro_context(macro_data: pd.DataFrame) -> pd.DataFrame:
    """Create point-in-time macro features using each value's availability date."""
    macro_data = macro_data.copy()
    macro_data["observation_date"] = pd.to_datetime(
        macro_data["observation_date"], format="mixed"
    )
    macro_data["available_date"] = pd.to_datetime(
        macro_data["available_date"], format="mixed"
    )

    feature_names = {
        "DFF": "federal_funds_rate",
        "DGS10": "treasury_yield_10y",
        "VIXCLS": "fred_vix",
    }
    series_frames = []

    for series_id, feature_name in feature_names.items():
        series = macro_data.loc[
            macro_data["series_id"].eq(series_id), ["available_date", "value"]
        ].copy()
        series = series.rename(columns={"available_date": "Date", "value": feature_name})
        series = series.drop_duplicates("Date", keep="last")
        series_frames.append(series)

    cpi = macro_data.loc[
        macro_data["series_id"].eq("CPIAUCSL"),
        ["observation_date", "available_date", "value"],
    ].sort_values("observation_date")
    cpi["inflation_cpi_yoy"] = cpi["value"].pct_change(12) * 100
    cpi = cpi[["available_date", "inflation_cpi_yoy"]].rename(
        columns={"available_date": "Date"}
    )
    cpi = cpi.drop_duplicates("Date", keep="last")
    series_frames.append(cpi)

    context = series_frames[0]
    for frame in series_frames[1:]:
        context = context.merge(frame, on="Date", how="outer")

    return context.sort_values("Date").ffill()


def main() -> None:
    if not PRICE_PATH.exists():
        raise FileNotFoundError(
            f"Missing {PRICE_PATH}. Run download_historical_prices.py first."
        )

    prices = pd.read_parquet(PRICE_PATH)
    prices["Date"] = pd.to_datetime(prices["Date"])
    prices = prices.sort_values(["ticker", "Date"]).reset_index(drop=True)

    feature_frames = []
    for _, ticker_prices in prices.groupby("ticker", sort=False):
        feature_frames.append(add_ticker_features(ticker_prices))
    featured = pd.concat(feature_frames, ignore_index=True)

    market_context = build_market_context(prices)
    featured = featured.merge(market_context, on="Date", how="left")

    if MACRO_PATH.exists():
        macro_data = pd.read_parquet(MACRO_PATH)
        macro_context = build_macro_context(macro_data)
        featured = pd.merge_asof(
            featured.sort_values("Date"),
            macro_context.sort_values("Date"),
            on="Date",
            direction="backward",
        )
    else:
        print(
            f"Warning: {MACRO_PATH} was not found. Building features without FRED data."
        )

    universe = pd.read_csv(UNIVERSE_PATH)
    eligible_metadata = universe.loc[
        universe["forecast_eligible"].astype(str).str.lower().eq("true"),
        ["ticker", "asset_type", "category", "sector"],
    ]
    featured = featured.loc[
        featured["ticker"].isin(eligible_metadata["ticker"])
        & featured["Date"].ge(pd.Timestamp(MODEL_START_DATE))
    ].copy()
    featured = featured.merge(eligible_metadata, on="ticker", how="left")
    featured["is_training_row"] = featured["target_return_10d"].notna()
    featured = featured.sort_values(["ticker", "Date"]).reset_index(drop=True)

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = PROCESSED_DIR / "forecast_features.csv"
    parquet_path = PROCESSED_DIR / "forecast_features.parquet"

    featured.to_csv(csv_path, index=False, date_format="%Y-%m-%d")
    featured.to_parquet(parquet_path, engine="pyarrow", index=False)

    print(f"Feature CSV saved: {csv_path}")
    print(f"Feature Parquet saved: {parquet_path}")
    print(f"Rows: {len(featured):,}")
    print(f"Forecast-eligible assets: {featured['ticker'].nunique()}")
    print(f"Training rows with a 10-day target: {featured['is_training_row'].sum():,}")


if __name__ == "__main__":
    main()
