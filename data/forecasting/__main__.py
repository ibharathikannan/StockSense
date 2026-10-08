"""Train or run offline experimental stock-return forecasts."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import sys

import joblib
import pandas as pd

from .inputs import build_inputs, RELATIVE_FEATURES
from .models import ForecastBundle, FORMAT_VERSION, evaluate, train_model
from .sources import load_local, load_postgres

DATA = Path(__file__).resolve().parents[1]


def _date(value: str) -> str:
    try:
        date = pd.Timestamp(value)
        if pd.isna(date) or date.tzinfo is not None or date != date.normalize():
            raise ValueError()
        return date.date().isoformat()
    except (ValueError, TypeError):
        raise argparse.ArgumentTypeError("Expected a timezone-naive completed-session date (YYYY-MM-DD)") from None


def _source(args):
    if args.source == "postgres":
        if not args.schema:
            raise ValueError("PostgreSQL requires --schema with a pinned complete snapshot")
        return load_postgres(args.schema, env_file=args.env_file)
    if args.schema:
        raise ValueError("--schema only applies to --source postgres")
    # The audited committed baseline is equivalent to price_only_features; never
    # quietly substitute macro_enriched_features or a mutable SQL 'latest' view.
    feature_path = args.features
    if feature_path is None:
        candidate = DATA / "artifacts" / "market" / "price_only_features.parquet"
        feature_path = candidate if candidate.is_file() else DATA / "processed" / "forecast_features.parquet"
    return load_local(feature_path, args.prices, args.universe)


def _json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _forecasts(bundle: ForecastBundle, frame: pd.DataFrame, run_date: str) -> pd.DataFrame:
    origins = frame.loc[frame.ticker.isin(bundle.metadata["eligible_tickers"])]
    latest = origins.sort_values(["Date", "ticker"]).groupby("ticker", sort=False).tail(1)
    result = bundle.predict(latest)
    result["generated_at_utc"] = run_date
    result["data_age_calendar_days"] = (
        pd.Timestamp(run_date).tz_localize(None).normalize() - result.Date
    ).dt.days
    result["stale_snapshot"] = result.data_age_calendar_days.gt(7)
    result.loc[result.stale_snapshot, "status"] = "historical_stale_snapshot_forecast"
    result["calibration_latest_outcome"] = bundle.calibration["latest_outcome"]
    return result.sort_values("ticker")


def _new_output(path: Path) -> None:
    if path.exists():
        raise ValueError("Output directory already exists; choose a new directory to preserve earlier runs")


def _load_bundle(path: Path) -> ForecastBundle:
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    artifact = path / "model.joblib"
    if manifest.get("format_version") != FORMAT_VERSION:
        raise ValueError("Unsupported model artifact version")
    if hashlib.sha256(artifact.read_bytes()).hexdigest() != manifest.get("model_sha256"):
        raise ValueError("Model artifact hash does not match its manifest")
    # Hash checking catches accidental changes, not malicious pickle payloads.
    # The caller must explicitly identify a trusted local model directory.
    bundle = joblib.load(artifact)
    if not isinstance(bundle, ForecastBundle) or tuple(bundle.feature_names) != tuple(RELATIVE_FEATURES):
        raise ValueError("Model does not match the current forecasting feature contract")
    if bundle.metadata.get("format_version") != FORMAT_VERSION:
        raise ValueError("Unsupported serialized forecasting bundle version")
    return bundle


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("train", "predict"):
        item = sub.add_parser(command)
        item.add_argument("--source", choices=("local", "postgres"), default="local")
        item.add_argument("--schema", help="Pinned ss_<20 hex> schema for read-only SQL")
        item.add_argument("--env-file", type=Path, default=DATA / ".env")
        item.add_argument("--features", type=Path)
        item.add_argument("--prices", type=Path, default=DATA / "raw" / "historical_prices.parquet")
        item.add_argument("--universe", type=Path, default=DATA / "asset_universe.csv")
        item.add_argument("--as-of", type=_date, required=True,
                          help="Inclusive completed-session cutoff; future outcomes are censored")
        item.add_argument("--output-dir", type=Path, required=True,
                          help="New local run directory; use ignored data/artifacts/forecasting/")
        if command == "train":
            item.add_argument("--tuning-start", type=_date, required=True)
            item.add_argument("--calibration-start", type=_date, required=True)
            item.add_argument("--evaluation-start", type=_date, required=True)
            item.add_argument("--coverage", type=float, default=0.9)
            item.add_argument("--model", choices=("auto", "ridge", "xgboost", "mean", "median"), default="xgboost",
                              help="Defaults to requested XGBoost; auto also compares Ridge and constants")
        else:
            item.add_argument("--model-dir", type=Path, required=True,
                              help="Trusted local bundle only; joblib is executable serialization")
    args = parser.parse_args(argv)
    try:
        _new_output(args.output_dir)
        f, p, u, provenance = _source(args)
        frame = build_inputs(f, p, u, as_of=args.as_of)
        run_date = datetime.now(timezone.utc).isoformat()
        if args.command == "train":
            if args.as_of < args.evaluation_start:
                raise ValueError("as-of must be on or after the evaluation boundary")
            bundle = train_model(frame, tuning_start=args.tuning_start,
                                 calibration_start=args.calibration_start,
                                 evaluation_start=args.evaluation_start,
                                 coverage=args.coverage, model=args.model)
            bundle.metadata.update({"source_provenance": provenance, "as_of": args.as_of,
                                    "created_at_utc": run_date,
                                    "versions": {name: importlib.metadata.version(name)
                                                 for name in ("pandas", "numpy", "scikit-learn", "joblib")}})
            if bundle.metadata["selected_model"].startswith("XGBoost"):
                bundle.metadata["versions"]["xgboost"] = importlib.metadata.version("xgboost")
            report = {"metadata": bundle.metadata, "calibration": bundle.calibration,
                      "limitations": ["Fixed current universe; adjusted prices may be revised",
                                      "After-close finalized bars only; no provider refresh performed",
                                      "Retrospective evaluation; no independent performance claim",
                                      "Nominal interval coverage is not guaranteed for dependent market data",
                                      "Width is uncertainty in percentage points, not a probability of accuracy"]}
            later = frame.loc[frame.Date.ge(args.evaluation_start) & frame[TARGET_NAME].notna()
                              & frame.ticker.isin(bundle.metadata["eligible_tickers"])]
            if len(later) >= 2:
                report["evaluation"] = evaluate(bundle, later)
                report["evaluation_by_year"] = {
                    str(year): evaluate(bundle, group) for year, group in later.groupby(later.Date.dt.year)
                    if len(group) >= 2}
            else:
                report["evaluation"] = {"status": "no_later_labeled_rows"}
        else:
            bundle = _load_bundle(args.model_dir)
            report = {"source_provenance": provenance, "as_of": args.as_of,
                      "model_metadata": bundle.metadata, "calibration": bundle.calibration}
        report["generated_at_utc"] = run_date
        forecasts = _forecasts(bundle, frame, run_date)
        # Only create outputs after data/model validation and inference succeeded.
        args.output_dir.mkdir(parents=True, exist_ok=False)
        forecasts.to_csv(args.output_dir / "forecasts.csv", index=False)
        _json(args.output_dir / "report.json", report)
        if args.command == "train":
            model_path = args.output_dir / "model.joblib"
            joblib.dump(bundle, model_path)
            _json(args.output_dir / "manifest.json", {
                "format_version": FORMAT_VERSION,
                "model_sha256": hashlib.sha256(model_path.read_bytes()).hexdigest(),
                "selected_model": bundle.metadata["selected_model"],
                "feature_names": list(bundle.feature_names), "as_of": args.as_of,
                "source_provenance": provenance})
        print(json.dumps({"model": bundle.metadata["selected_model"], "forecasts": len(forecasts),
                          "nominal_coverage": bundle.calibration["coverage"],
                          "stale_snapshot_rows": int(forecasts.stale_snapshot.sum()),
                          "output_dir": str(args.output_dir),
                          "status": "experimental_no_live_serving"}, indent=2))
        return 0
    except (ValueError, OSError, ImportError):
        # Imported provider/driver/library errors can contain source contents or
        # credentials. Detailed deterministic validation is accessible in Python.
        print("Forecasting failed: check source schemas, pinned snapshot permissions, date boundaries, "
              "dependencies, trusted model integrity and a new output directory.", file=sys.stderr)
        return 1


TARGET_NAME = "target_return_10d"

if __name__ == "__main__":
    raise SystemExit(main())
