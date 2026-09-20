#!/usr/bin/env python3
"""Download daily historical prices from Yahoo Finance."""

from datetime import date
from pathlib import Path
import time

import pandas as pd
import yfinance as yf


# --------------------------------------------------
# 1. Configuration
# --------------------------------------------------

DATA_DIR = Path(__file__).resolve().parent
UNIVERSE_PATH = DATA_DIR / "asset_universe.csv"
OUTPUT_DIR = DATA_DIR / "raw"

# The extra year is used to warm up long indicators such as SMA-200.
# build_features.py keeps model rows from MODEL_START_DATE onward.
START_DATE = "2020-09-01"
END_DATE = date.today().isoformat()

MAX_ATTEMPTS = 3
DELAY_BETWEEN_TICKERS_SECONDS = 0.25

WANTED_COLUMNS = [
    "Date",
    "ticker",
    "Open",
    "High",
    "Low",
    "Close",
    "Adj Close",
    "Volume",
    "Dividends",
    "Stock Splits",
]


def load_tickers() -> list[str]:
    """Load the shared 80-stock, 10-ETF and VIX universe."""
    universe = pd.read_csv(UNIVERSE_PATH)
    tickers = universe["ticker"].dropna().astype(str).str.strip().tolist()

    if not tickers:
        raise ValueError(f"No tickers were found in {UNIVERSE_PATH}")

    return tickers


def download_one_ticker(ticker: str) -> pd.DataFrame:
    """Download and standardise one ticker, retrying temporary failures."""
    last_error: Exception | None = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            df = yf.Ticker(ticker).history(
                start=START_DATE,
                end=END_DATE,
                interval="1d",
                auto_adjust=False,
                actions=True,
            )

            if df.empty:
                raise ValueError("no data returned")

            df = df.reset_index()

            # yfinance may call this Date or Datetime.
            if "Datetime" in df.columns:
                df = df.rename(columns={"Datetime": "Date"})

            if "Date" not in df.columns:
                raise ValueError("the response has no Date column")

            # Daily bars represent exchange dates. Remove timezone information
            # without converting the date to UTC first.
            df["Date"] = (
                pd.to_datetime(df["Date"])
                .dt.tz_localize(None)
                .dt.normalize()
            )

            df["ticker"] = ticker

            # These columns can be absent when no actions occurred.
            for column in ["Dividends", "Stock Splits"]:
                if column not in df.columns:
                    df[column] = 0.0

            missing_columns = [
                column for column in WANTED_COLUMNS if column not in df.columns
            ]
            if missing_columns:
                raise ValueError(f"missing columns: {missing_columns}")

            return df[WANTED_COLUMNS]

        except Exception as error:
            last_error = error
            print(f"  Attempt {attempt}/{MAX_ATTEMPTS} failed: {error}")
            if attempt < MAX_ATTEMPTS:
                time.sleep(2 ** (attempt - 1))

    raise RuntimeError(last_error)


def main() -> None:
    # --------------------------------------------------
    # 2. Download daily historical data
    # --------------------------------------------------

    tickers = load_tickers()
    all_prices = []
    failed_tickers = []

    print(f"Downloading {len(tickers)} symbols from {START_DATE} to {END_DATE}...")

    for position, ticker in enumerate(tickers, start=1):
        print(f"[{position}/{len(tickers)}] Downloading {ticker}...")

        try:
            df = download_one_ticker(ticker)
            all_prices.append(df)
            print(f"  Downloaded {len(df):,} daily rows.")
        except Exception as error:
            failed_tickers.append(ticker)
            print(f"  Failed for {ticker}: {error}")

        time.sleep(DELAY_BETWEEN_TICKERS_SECONDS)

    # --------------------------------------------------
    # 3. Combine all tickers
    # --------------------------------------------------

    if not all_prices:
        raise ValueError(
            "No price data was downloaded. Check your internet connection and tickers."
        )

    prices = pd.concat(all_prices, ignore_index=True)
    prices = (
        prices.drop_duplicates(subset=["ticker", "Date"], keep="last")
        .sort_values(by=["ticker", "Date"])
        .reset_index(drop=True)
    )

    # --------------------------------------------------
    # 4. Save CSV and Parquet
    # --------------------------------------------------

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    csv_path = OUTPUT_DIR / "historical_prices.csv"
    parquet_path = OUTPUT_DIR / "historical_prices.parquet"

    prices.to_csv(csv_path, index=False, date_format="%Y-%m-%d")
    print(f"\nCSV saved: {csv_path}")

    try:
        prices.to_parquet(parquet_path, engine="pyarrow", index=False)
        print(f"Parquet saved: {parquet_path}")
    except Exception as error:
        print("Parquet export failed, but the CSV was saved successfully.")
        print(f"Parquet error: {error}")

    # --------------------------------------------------
    # 5. Check the dataset
    # --------------------------------------------------

    print(f"Total rows saved: {len(prices):,}")
    print(f"Symbols downloaded: {prices['ticker'].nunique()}/{len(tickers)}")

    if failed_tickers:
        print(f"Failed tickers ({len(failed_tickers)}): {', '.join(failed_tickers)}")
    else:
        print("All requested tickers downloaded successfully.")

    print("\nDataset preview:")
    print(prices.head())

    print("\nRows per ticker:")
    print(prices["ticker"].value_counts().sort_index())


if __name__ == "__main__":
    main()
