#!/usr/bin/env python3
"""Build one profile per asset for the recommender: metadata plus risk features.

Reads asset_universe.csv and raw/historical_prices.parquet and writes
processed/asset_profiles.json, which backend/scripts/import_assets.py loads into
the MongoDB `assets` collection. Index rows (^VIX) are context only and skipped.

Risk features use the latest 252 trading days (about one year):
  volatility_1y     annualised standard deviation of daily returns
  beta              sensitivity to SPY (1.0 = moves with the market)
  max_drawdown_1y   worst peak-to-trough fall, as a negative fraction
  dividend_yield    dividends paid over the window / latest close
  volatility_rank   0-1 rank of volatility across all assets (0 = calmest)
Assets with fewer than MIN_HISTORY return observations get null risk features
rather than misleading numbers.
"""

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR = Path(__file__).resolve().parent
UNIVERSE_PATH = DATA_DIR / "asset_universe.csv"
PRICE_PATH = DATA_DIR / "raw" / "historical_prices.parquet"
OUTPUT_PATH = DATA_DIR / "processed" / "asset_profiles.json"

WINDOW = 252
MIN_HISTORY = 60
TRADING_DAYS_PER_YEAR = 252


def clean(value, digits=6):
    """JSON-safe number: NaN/inf become None."""
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return None
    return round(float(value), digits)


def risk_features(ticker: str, returns: pd.DataFrame, adj_close: pd.DataFrame, prices: pd.DataFrame) -> dict:
    empty = {"volatility_1y": None, "beta": None, "max_drawdown_1y": None, "dividend_yield": None}
    # Renamed columns so SPY can be paired with itself (beta 1.0) without duplicate labels.
    pair = pd.concat([returns[ticker].rename("asset"), returns["SPY"].rename("spy")], axis=1).dropna().tail(WINDOW)
    history_days = len(pair)
    if history_days < MIN_HISTORY:
        return {**empty, "history_days": history_days}

    asset_returns, spy_returns = pair["asset"], pair["spy"]
    volatility = asset_returns.std() * np.sqrt(TRADING_DAYS_PER_YEAR)
    beta = asset_returns.cov(spy_returns) / spy_returns.var()

    window_prices = adj_close[ticker].dropna().tail(history_days + 1)
    max_drawdown = (window_prices / window_prices.cummax() - 1).min()

    own = prices.loc[prices["ticker"].eq(ticker)].sort_values("Date").tail(WINDOW)
    last_close = own["Close"].iloc[-1]
    dividend_yield = own["Dividends"].sum() / last_close if last_close else np.nan

    return {
        "volatility_1y": clean(volatility),
        "beta": clean(beta),
        "max_drawdown_1y": clean(max_drawdown),
        "dividend_yield": clean(dividend_yield),
        "history_days": history_days,
    }


def main() -> None:
    universe = pd.read_csv(UNIVERSE_PATH, keep_default_na=False)
    universe = universe.loc[universe["asset_type"].ne("index")].copy()

    prices = pd.read_parquet(PRICE_PATH)
    prices["Date"] = pd.to_datetime(prices["Date"])
    prices = prices.sort_values(["ticker", "Date"])

    adj_close = prices.pivot(index="Date", columns="ticker", values="Adj Close")
    returns = adj_close.pct_change(fill_method=None)
    latest_date = prices.groupby("ticker")["Date"].max()

    profiles = []
    for row in universe.itertuples(index=False):
        if row.ticker not in adj_close.columns:
            print(f"Warning: no price data for {row.ticker}; skipped")
            continue
        profiles.append(
            {
                "ticker": row.ticker,
                "name": row.name,
                "asset_type": row.asset_type,
                "category": row.category,
                "sector": row.sector,
                "themes": [t for t in row.themes.split("|") if t],
                "recommendation_eligible": str(row.recommendation_eligible).lower() == "true",
                "forecast_eligible": str(row.forecast_eligible).lower() == "true",
                "history_note": row.history_note or None,
                "as_of": latest_date[row.ticker].strftime("%Y-%m-%d"),
                "risk": risk_features(row.ticker, returns, adj_close, prices),
            }
        )

    volatility = pd.Series({p["ticker"]: p["risk"]["volatility_1y"] for p in profiles}, dtype="float64")
    rank = volatility.rank(pct=True)
    for p in profiles:
        p["risk"]["volatility_rank"] = clean(rank.get(p["ticker"]), 4)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(profiles, indent=2, allow_nan=False), encoding="utf-8")

    no_risk = [p["ticker"] for p in profiles if p["risk"]["volatility_1y"] is None]
    print(f"Wrote {len(profiles)} asset profiles to {OUTPUT_PATH}")
    print(f"Prices as of {max(p['as_of'] for p in profiles)}")
    if no_risk:
        print(f"Too little history for risk features: {', '.join(no_risk)}")


if __name__ == "__main__":
    main()
