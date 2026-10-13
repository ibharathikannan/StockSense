"""Explicit local Yahoo/file retraining and deployment-package export; no SQL."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from data.build_features import build_feature_dataset
from .inputs import build_inputs
from .models import TARGET, evaluate, train_model
from .walkforward import GRID

DATA = Path(__file__).resolve().parents[1]
START = "2020-09-01"


def completed_date(value: str) -> pd.Timestamp:
    """Reject ambiguous intraday dates; same-day exchange bars are excluded."""
    stamp = pd.Timestamp(value)
    today = pd.Timestamp(datetime.now(ZoneInfo("America/New_York")).date())
    if pd.isna(stamp) or stamp.tzinfo is not None or stamp != stamp.normalize() or not pd.Timestamp(START) < stamp < today:
        raise ValueError("as_of must be an explicit past completed-session date after 2020-09-01")
    return stamp


def download_prices(universe: pd.DataFrame, as_of: str) -> pd.DataFrame:
    cutoff = completed_date(as_of)
    import yfinance as yf  # provider dependency is needed only for explicit downloads

    eligible = universe.loc[universe.forecast_eligible.astype(str).str.lower().eq("true"), "ticker"]
    tickers = list(dict.fromkeys([*eligible, "SPY", "^VIX"]))
    frames = []
    for ticker in tickers:
        try:
            raw = yf.Ticker(ticker).history(start=START, end=(cutoff + pd.Timedelta(days=1)).date().isoformat(),
                interval="1d", auto_adjust=False, actions=True)
            if raw.empty:
                raise ValueError("Empty daily-price response")
            raw = raw.reset_index().rename(columns={"Datetime": "Date"})
            raw["Date"] = pd.to_datetime(raw["Date"]).dt.tz_localize(None).dt.normalize()
            if not raw.Date.between(START, cutoff).all():
                raise ValueError("Provider returned rows outside requested completed dates")
            raw["ticker"] = ticker
            for name in ("Dividends", "Stock Splits"):
                if name not in raw:
                    raw[name] = 0.
            frames.append(raw[["Date", "ticker", "Open", "High", "Low", "Close", "Adj Close", "Volume", "Dividends", "Stock Splits"]])
        except Exception:
            # Provider exceptions may contain request details; disclose only ticker.
            raise ValueError(f"Yahoo daily-price collection failed for {ticker}; no package exported") from None
    return pd.concat(frames, ignore_index=True).sort_values(["ticker", "Date"]).reset_index(drop=True)


def run(*, as_of: str, output_dir: Path, tuning_start: str, calibration_start: str,
        evaluation_start: str, prices: Path | None = None, download_yahoo: bool = False,
        universe_path: Path = DATA / "asset_universe.csv", diagnostics: bool = False):
    cutoff = completed_date(as_of)
    output = Path(output_dir).resolve()
    permitted = (DATA / "artifacts" / "forecasting").resolve()
    if permitted not in output.parents or output.exists():
        raise ValueError("Choose a new ignored run directory under data/artifacts/forecasting")
    if (prices is None) == (not download_yahoo):
        raise ValueError("Choose exactly one of --prices or --download-yahoo")
    bounds = [pd.Timestamp(value) for value in (tuning_start, calibration_start, evaluation_start)]
    if any(pd.isna(value) or value.tzinfo is not None or value != value.normalize() for value in bounds) or not bounds[0] < bounds[1] < bounds[2] <= cutoff:
        raise ValueError("Require ordered tuning < calibration < evaluation <= as_of date boundaries")
    universe = pd.read_csv(universe_path)
    provenance = {"source": "manual_local_retraining", "provider": "yahoo" if download_yahoo else "local_parquet",
        "requested_as_of": cutoff.date().isoformat(), "start": START,
        "universe_sha256": hashlib.sha256(Path(universe_path).read_bytes()).hexdigest(),
        "collected_at_utc": datetime.now(timezone.utc).isoformat(),
        "auto_adjust": False, "historical_revisions_possible": True}
    if download_yahoo:
        raw = download_prices(universe, as_of)
    else:
        path = Path(prices)
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        raw = pd.read_parquet(path)
        if hashlib.sha256(path.read_bytes()).hexdigest() != before:
            raise ValueError("Local prices changed while reading")
        provenance["source_file_sha256"] = before
    raw = raw.copy()
    raw["Date"] = pd.to_datetime(raw["Date"], errors="raise")
    raw = raw.loc[raw.Date.between(START, cutoff)].sort_values(["ticker", "Date"]).reset_index(drop=True)
    if raw.empty:
        raise ValueError("No raw prices through requested as_of")
    provenance["prices_sha256"] = hashlib.sha256(raw.to_csv(index=False, date_format="%Y-%m-%d", float_format="%.17g").encode()).hexdigest()
    provenance["price_rows"] = len(raw)
    features = build_feature_dataset(raw, universe, macro_data=None)
    frame = build_inputs(features, raw, universe, as_of=as_of)
    bundle = train_model(frame, tuning_start=tuning_start, calibration_start=calibration_start,
        evaluation_start=evaluation_start, model="xgboost", xgboost_grid=GRID, refit_selected=True)
    report = None
    if diagnostics:
        period = frame.loc[frame.Date.ge(evaluation_start) & frame[TARGET].notna()
            & frame.ticker.isin(bundle.metadata["eligible_tickers"])].copy()
        if period.empty:
            raise ValueError("No labeled evaluation rows for requested diagnostics")
        report = evaluate(bundle, period)
    bundle.metadata.update(as_of=str(frame.Date.max().date()), source_provenance=provenance)
    from .package import export_package
    return export_package(bundle, frame, output, provenance, evaluation=report)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", required=True, help="Explicit past completed exchange session date")
    parser.add_argument("--output-dir", type=Path, required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--prices", type=Path)
    source.add_argument("--download-yahoo", action="store_true")
    parser.add_argument("--universe-path", type=Path, default=DATA / "asset_universe.csv")
    for name in ("tuning-start", "calibration-start", "evaluation-start"):
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--diagnostics", action="store_true", help="Retrospective evaluation; never selects a model")
    args = parser.parse_args(argv)
    try:
        run(**vars(args))
    except (ValueError, FileNotFoundError, ImportError):
        parser.exit(1, "Retraining failed: verify inputs, dependencies, date boundaries and a new ignored output directory. No automatic promotion performed.\n")
    print("Local forecasting package exported. Deployment/promotion is a separate manual step.")


if __name__ == "__main__":
    main()
