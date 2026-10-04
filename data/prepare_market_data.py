#!/usr/bin/env python3
"""Audit committed inputs and build local market-feature candidates."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

if __package__:
    from .build_features import FORECAST_HORIZON, build_feature_dataset
else:
    from build_features import FORECAST_HORIZON, build_feature_dataset


DATA_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT = DATA_DIR / "artifacts" / "market"

# These are candidate predictors, not a fitted preprocessing specification.
# Keep identifiers, the target, and the training-row flag out of model inputs.
PRICE_FEATURES = [
    "return_1d", "return_5d", "return_20d", "log_return_1d",
    "sma_5", "sma_20", "sma_50", "sma_200", "ema_12", "ema_26",
    "rsi_14", "macd", "macd_signal", "macd_histogram", "atr_14",
    "rolling_volatility_20", "bollinger_middle_20", "bollinger_upper_20",
    "bollinger_lower_20", "bollinger_position_20", "adjusted_close_lag_1",
    "adjusted_close_lag_5", "adjusted_close_lag_10", "adjusted_close_lag_20",
    "return_1d_lag_1", "return_1d_lag_5", "return_1d_lag_10",
    "volume_change_1d", "volume_sma_20", "volume_ratio_20",
    "spy_adjusted_close", "spy_return_1d", "spy_return_5d", "vix_close",
]
MACRO_FEATURES = [
    "federal_funds_rate", "treasury_yield_10y", "fred_vix", "inflation_cpi_yoy",
]


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def date_range(frame: pd.DataFrame, column: str) -> dict[str, str | None]:
    values = pd.to_datetime(frame[column]).dropna()
    return {
        "first": values.min().date().isoformat() if len(values) else None,
        "last": values.max().date().isoformat() if len(values) else None,
    }


def validate_unique(frame: pd.DataFrame, keys: list[str], source: str) -> int:
    duplicates = int(frame.duplicated(keys).sum())
    if duplicates:
        raise ValueError(f"{source} has {duplicates} duplicate {keys} rows")
    return duplicates


def validate_target(features: pd.DataFrame, prices: pd.DataFrame) -> dict[str, int | float]:
    expected = prices.sort_values(["ticker", "Date"]).copy()
    expected["expected_target"] = (
        expected.groupby("ticker")["Adj Close"].shift(-FORECAST_HORIZON)
        / expected["Adj Close"] - 1
    )
    joined = features[["ticker", "Date", "target_return_10d", "is_training_row"]].merge(
        expected[["ticker", "Date", "expected_target"]],
        on=["ticker", "Date"],
        validate="one_to_one",
    )
    if len(joined) != len(features):
        raise ValueError("Some feature rows do not match source price rows")
    observed = joined["target_return_10d"].to_numpy(dtype=float)
    calculated = joined["expected_target"].to_numpy(dtype=float)
    if not np.allclose(observed, calculated, rtol=1e-12, atol=1e-12, equal_nan=True):
        raise ValueError("10-day target does not match future adjusted-close return")
    if not joined["is_training_row"].eq(joined["expected_target"].notna()).all():
        raise ValueError("is_training_row does not match target availability")
    absolute_errors = np.abs(observed - calculated)
    finite_errors = absolute_errors[np.isfinite(absolute_errors)]
    if not len(finite_errors):
        raise ValueError("No labeled rows are available for target validation")
    return {
        "horizon_trading_days": FORECAST_HORIZON,
        "checked_rows": len(joined),
        "labeled_rows": int(joined["is_training_row"].sum()),
        "unlabeled_rows": int((~joined["is_training_row"]).sum()),
        "maximum_absolute_error": float(finite_errors.max()),
    }


def macro_provenance(macro: pd.DataFrame) -> dict:
    expected_lags = {"DFF": 1, "CPIAUCSL": 50, "DGS10": 1, "VIXCLS": 0}
    lag_days = (
        pd.to_datetime(macro["available_date"])
        - pd.to_datetime(macro["observation_date"])
    ).dt.days
    observed_lags = {
        series: sorted(lag_days.loc[macro["series_id"].eq(series)].dropna().unique().astype(int).tolist())
        for series in sorted(macro["series_id"].unique())
    }
    manual_pattern = (
        macro["realtime_end"].isna().all()
        and set(observed_lags) == set(expected_lags)
        and all(observed_lags[key] == [lag] for key, lag in expected_lags.items())
    )
    return {
        "inference": (
            "manual CSV import pattern; values may be revised and availability dates are proxy lags"
            if manual_pattern else "unknown; inspect source records and collection method"
        ),
        "evidence": {
            "realtime_end_non_null": int(macro["realtime_end"].notna().sum()),
            "observed_availability_lag_days": observed_lags,
        },
        "historical_point_in_time_values_verified": False,
    }


def feature_audit(features: pd.DataFrame, allowlist: list[str]) -> dict:
    missing_columns = sorted(set(allowlist) - set(features.columns))
    if missing_columns:
        raise ValueError(f"Missing candidate feature columns: {missing_columns}")
    validate_unique(features, ["ticker", "Date"], "candidate features")
    numeric = features[allowlist]
    nonfinite = {name: int((~np.isfinite(numeric[name].to_numpy(dtype=float))).sum()) for name in allowlist}
    return {
        "rows": len(features),
        "tickers": int(features["ticker"].nunique()),
        "dates": date_range(features, "Date"),
        "duplicate_ticker_dates": 0,
        "missing_by_column": {name: int(count) for name, count in features.isna().sum().items() if count},
        "nonfinite_allowlisted_by_column": {name: count for name, count in nonfinite.items() if count},
        "allowlist": allowlist,
    }


def prepare(
    price_path: Path,
    macro_path: Path,
    universe_path: Path,
    baseline_path: Path,
    output_dir: Path,
) -> dict:
    for path in (price_path, macro_path, universe_path, baseline_path):
        if not path.is_file():
            raise FileNotFoundError(path)
    source_hashes = {
        name: file_hash(path)
        for name, path in {
            "prices": price_path, "macro": macro_path,
            "universe": universe_path, "committed_features": baseline_path,
        }.items()
    }
    prices = pd.read_parquet(price_path)
    prices["Date"] = pd.to_datetime(prices["Date"])
    macro = pd.read_parquet(macro_path)
    universe = pd.read_csv(universe_path)
    baseline = pd.read_parquet(baseline_path)
    validate_unique(prices, ["ticker", "Date"], "prices")
    validate_unique(macro, ["series_id", "observation_date"], "macro")
    validate_unique(universe, ["ticker"], "universe")
    validate_unique(baseline, ["ticker", "Date"], "committed features")

    eligible = sorted(universe.loc[
        universe["forecast_eligible"].astype(str).str.lower().eq("true"), "ticker"
    ].tolist())
    missing_prices = sorted(set(eligible) - set(prices["ticker"]))
    if missing_prices:
        raise ValueError(f"Forecast-eligible tickers missing prices: {missing_prices}")

    price_only = build_feature_dataset(prices, universe)
    with_macro = build_feature_dataset(prices, universe, macro)
    if not price_only[["ticker", "Date", "target_return_10d"]].equals(
        with_macro[["ticker", "Date", "target_return_10d"]]
    ):
        raise ValueError("Macro enrichment changed asset rows or targets")
    target_audit = validate_target(price_only, prices)
    validate_target(with_macro, prices)
    price_audit = feature_audit(price_only, PRICE_FEATURES)
    macro_audit = feature_audit(with_macro, PRICE_FEATURES + MACRO_FEATURES)
    if sorted(price_only["ticker"].unique()) != eligible:
        raise ValueError("Candidate asset set differs from forecast eligibility")

    output_dir.mkdir(parents=True, exist_ok=True)
    output_paths = {
        "price_only": output_dir / "price_only_features.parquet",
        "with_macro": output_dir / "macro_features.parquet",
    }
    price_only.to_parquet(output_paths["price_only"], index=False)
    with_macro.to_parquet(output_paths["with_macro"], index=False)
    manifest = {
        "purpose": "Descriptive audit and candidate features; no model training or readiness decision",
        "sources": {
            "sha256": source_hashes,
            "prices": {"rows": len(prices), "tickers": int(prices["ticker"].nunique()), "dates": date_range(prices, "Date"), "duplicate_ticker_dates": 0, "missing_by_column": {name: int(count) for name, count in prices.isna().sum().items() if count}},
            "macro": {"rows": len(macro), "series": macro["series_id"].value_counts().sort_index().astype(int).to_dict(), "availability_dates": date_range(macro, "available_date"), "duplicate_series_observation_dates": 0, "missing_by_column": {name: int(count) for name, count in macro.isna().sum().items() if count}, "provenance": macro_provenance(macro)},
            "committed_features": {"rows": len(baseline), "columns": baseline.columns.tolist(), "dates": date_range(baseline, "Date"), "duplicate_ticker_dates": 0, "matches_price_only_candidate": bool(baseline.equals(price_only))},
        },
        "eligibility": {"forecast_tickers": eligible, "count": len(eligible)},
        "target_validation": target_audit,
        "candidates": {
            "price_only": {**price_audit, "path": str(output_paths["price_only"]), "sha256": file_hash(output_paths["price_only"])},
            "with_macro": {**macro_audit, "path": str(output_paths["with_macro"]), "sha256": file_hash(output_paths["with_macro"])},
        },
        "notes": [
            "Candidate predictors assume an after-close prediction cutoff; source release times are not verified.",
            "Adjusted prices and a fixed current asset universe may contain historical revisions or survivorship bias.",
            "Any learned preprocessing must be fit separately within later training folds.",
            "The committed feature baseline is audited as an input and is not rewritten.",
        ],
    }
    if not set(MACRO_FEATURES).issubset(baseline.columns):
        manifest["notes"].append("Committed feature baseline lacks one or more FRED macro columns.")
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if {name: file_hash(path) for name, path in {
        "prices": price_path, "macro": macro_path,
        "universe": universe_path, "committed_features": baseline_path,
    }.items()} != source_hashes:
        raise RuntimeError("A source dataset changed during preparation")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--price-path", type=Path, default=DATA_DIR / "raw" / "historical_prices.parquet")
    parser.add_argument("--macro-path", type=Path, default=DATA_DIR / "raw" / "macro_indicators.parquet")
    parser.add_argument("--universe-path", type=Path, default=DATA_DIR / "asset_universe.csv")
    parser.add_argument("--baseline-path", type=Path, default=DATA_DIR / "processed" / "forecast_features.parquet")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    manifest = prepare(args.price_path, args.macro_path, args.universe_path, args.baseline_path, args.output_dir)
    print(f"Prepared {manifest['candidates']['price_only']['rows']:,} price-only and macro candidate rows in {args.output_dir}")
    print(f"Forecast-eligible tickers: {manifest['eligibility']['count']}")
    print(f"Manifest: {args.output_dir / 'manifest.json'}")


if __name__ == "__main__":
    main()
