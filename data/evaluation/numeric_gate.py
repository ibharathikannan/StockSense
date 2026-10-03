#!/usr/bin/env python3
"""Independent, read-only numeric readiness audit; never fits or downloads data.

Run from any directory. Only the JSON evidence output is written. Comparisons
use formulas implemented here, not the preparation/build-feature helpers.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
HORIZON = 10


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def compare(actual, expected) -> dict:
    a, e = np.asarray(actual, dtype=float), np.asarray(expected, dtype=float)
    close = np.isclose(a, e, rtol=1e-10, atol=1e-10, equal_nan=True)
    valid = np.isfinite(a) & np.isfinite(e)
    return {"rows": int(len(a)), "mismatches": int((~close).sum()),
            "maximum_absolute_error": float(np.abs(a[valid] - e[valid]).max()) if valid.any() else None}


def frame_summary(frame: pd.DataFrame, keys: list[str]) -> dict:
    numeric = frame.select_dtypes(include="number")
    return {"rows": len(frame), "schema": {c: str(t) for c, t in frame.dtypes.items()},
            "duplicate_keys": int(frame.duplicated(keys).sum()),
            "missing": {c: int(n) for c, n in frame.isna().sum().items() if n},
            "infinite": {c: int(np.isinf(numeric[c]).sum()) for c in numeric if np.isinf(numeric[c]).any()}}


def expected_ticker(group: pd.DataFrame) -> pd.DataFrame:
    """Causal audit vectors and endpoint labels, independent of builder code."""
    group = group.sort_values("Date").reset_index(drop=True)
    a = group["Adj Close"]
    expected = group[["ticker", "Date"]].copy()
    factor = a / group["Close"]
    for name in ("Open", "High", "Low"):
        expected[f"Adj {name}"] = group[name] * factor
    for lag in (1, 5, 20):
        expected[f"return_{lag}d"] = a / a.shift(lag) - 1
    expected["log_return_1d"] = np.log(a / a.shift(1))
    for window in (5, 20, 50, 200):
        expected[f"sma_{window}"] = a.rolling(window).mean()
    for span in (12, 26):
        expected[f"ema_{span}"] = a.ewm(span=span, adjust=False).mean()
    gain = a.diff().clip(lower=0).rolling(14).mean()
    loss = (-a.diff().clip(upper=0)).rolling(14).mean()
    expected["rsi_14"] = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
    expected["macd"] = expected["ema_12"] - expected["ema_26"]
    expected["macd_signal"] = expected["macd"].ewm(span=9, adjust=False).mean()
    expected["macd_histogram"] = expected["macd"] - expected["macd_signal"]
    tr = pd.concat([expected["Adj High"] - expected["Adj Low"],
                    (expected["Adj High"] - a.shift()).abs(),
                    (expected["Adj Low"] - a.shift()).abs()], axis=1).max(axis=1)
    expected["atr_14"] = tr.rolling(14).mean()
    expected["rolling_volatility_20"] = expected["return_1d"].rolling(20).std() * np.sqrt(252)
    middle, std = a.rolling(20).mean(), a.rolling(20).std()
    expected["bollinger_middle_20"] = middle
    expected["bollinger_upper_20"] = middle + 2 * std
    expected["bollinger_lower_20"] = middle - 2 * std
    expected["bollinger_position_20"] = (a - middle + 2 * std) / (4 * std)
    for lag in (1, 5, 10, 20):
        expected[f"adjusted_close_lag_{lag}"] = a.shift(lag)
    for lag in (1, 5, 10):
        expected[f"return_1d_lag_{lag}"] = expected["return_1d"].shift(lag)
    volume = group["Volume"]
    expected["volume_change_1d"] = volume / volume.shift() - 1
    expected["volume_sma_20"] = volume.rolling(20).mean()
    expected["volume_ratio_20"] = volume / volume.rolling(20).mean().replace(0, np.nan)
    # Explicit array endpoints rather than importing the builder's target code.
    labels = np.full(len(group), np.nan)
    prices = a.to_numpy()
    labels[:-HORIZON] = prices[HORIZON:] / prices[:-HORIZON] - 1
    expected["target_return_10d"] = labels
    expected["label_end"] = group["Date"].shift(-HORIZON)
    return expected


def audit(data_dir: Path) -> dict:
    sources = {"universe": data_dir / "asset_universe.csv",
               "prices": data_dir / "raw/historical_prices.parquet",
               "macro": data_dir / "raw/macro_indicators.parquet",
               "baseline": data_dir / "processed/forecast_features.parquet",
               "price_candidate": data_dir / "artifacts/market/price_only_features.parquet",
               "macro_candidate": data_dir / "artifacts/market/macro_features.parquet"}
    hashes = {k: sha256(p) for k, p in sources.items()}
    frames = {k: pd.read_csv(p) if p.suffix == ".csv" else pd.read_parquet(p) for k, p in sources.items()}
    u, p, m, f, fc, fm = (frames[k] for k in sources)
    for frame in (p, f, fc, fm):
        frame["Date"] = pd.to_datetime(frame["Date"])
    for column in ("observation_date", "available_date"):
        m[column] = pd.to_datetime(m[column])
    result = {"purpose": "Independent gate evidence; local immutable snapshot, no remote/provider verification",
              "source_sha256": hashes,
              "sources": {k: frame_summary(v, ["ticker"] if k == "universe" else
                                         ["series_id", "observation_date"] if k == "macro" else
                                         ["ticker", "Date"]) for k, v in frames.items()}}
    eligible = set(u.loc[u.forecast_eligible.astype(str).str.lower().eq("true"), "ticker"])
    result["eligibility"] = {"universe_rows": len(u), "asset_types": u.asset_type.value_counts().to_dict(),
                             "eligible_count": len(eligible), "missing_eligible": sorted(eligible - set(f.ticker)),
                             "unexpected_features": sorted(set(f.ticker) - eligible),
                             "universe_without_raw": sorted(set(u.ticker) - set(p.ticker))}
    result["candidate_identity"] = {"baseline_equals_price_candidate": f.equals(fc),
                                   "macro_base_columns_equal": f.equals(fm[f.columns]),
                                   "macro_extra_columns": sorted(set(fm.columns) - set(f.columns))}
    spy_dates = set(p.loc[p.ticker.eq("SPY"), "Date"])
    coverage = {}
    for ticker, group in p.groupby("ticker"):
        valid_dates = {d for d in spy_dates if group.Date.min() <= d <= group.Date.max()}
        coverage[ticker] = {"rows": len(group), "first": str(group.Date.min().date()), "last": str(group.Date.max().date()),
                            "missing_spy_sessions": len(valid_dates - set(group.Date)),
                            "extra_spy_sessions": len(set(group.Date) - spy_dates)}
    result["coverage"] = coverage
    bad_range = ((p.High + 1e-8 < p[["Open", "Close", "Low"]].max(axis=1)) |
                 (p.Low - 1e-8 > p[["Open", "Close", "High"]].min(axis=1)))
    result["price_plausibility"] = {"nonpositive_ohlc_or_adjusted": int((p[["Open", "High", "Low", "Close", "Adj Close"]] <= 0).any(axis=1).sum()),
                                   "invalid_ohlc_range": int(bad_range.sum()), "negative_volume": int((p.Volume < 0).sum()),
                                   "zero_volume_by_ticker": p.loc[p.Volume.eq(0)].groupby("ticker").size().to_dict(),
                                   "weekend_rows": int((p.Date.dt.dayofweek > 4).sum())}
    expected = pd.concat([expected_ticker(g) for _, g in p.groupby("ticker")], ignore_index=True)
    joined = f.merge(expected, on=["ticker", "Date"], how="left", suffixes=("", "_expected"), validate="one_to_one")
    columns = [c for c in expected if c not in ("ticker", "Date", "label_end")]
    result["independent_formula_checks"] = {c: compare(joined[c], joined[c + "_expected"]) for c in columns}
    rsi_missing = joined.loc[joined.rsi_14.isna(), ["ticker", "Date"]].copy()
    rsi_causes = []
    for ticker, group in p.groupby("ticker"):
        group = group.sort_values("Date").copy()
        loss = (-group["Adj Close"].diff().clip(upper=0)).rolling(14).mean()
        zero = group.loc[loss.eq(0), ["ticker", "Date"]]
        matches = rsi_missing.merge(zero, on=["ticker", "Date"])
        rsi_causes.extend(matches.assign(Date=matches.Date.astype(str)).to_dict("records"))
    result["rsi_missing_zero_loss_windows"] = rsi_causes
    result["labels"] = {"horizon_sessions": HORIZON, "labeled": int(f.target_return_10d.notna().sum()),
                        "unlabeled": int(f.target_return_10d.isna().sum()),
                        "training_flag_mismatches": int((f.is_training_row != f.target_return_10d.notna()).sum()),
                        "mature_labeled_end_after_snapshot": int((joined.target_return_10d.notna() & (joined.label_end > p.Date.max())).sum()),
                        "last_labeled_origin": str(joined.loc[joined.target_return_10d.notna(), "Date"].max().date()),
                        "unlabeled_per_ticker": f.loc[f.target_return_10d.isna()].groupby("ticker").size().to_dict()}
    spy = p.loc[p.ticker.eq("SPY")].sort_values("Date").set_index("Date")["Adj Close"]
    vix = p.loc[p.ticker.eq("^VIX")].set_index("Date")["Close"]
    contexts = {"spy_adjusted_close": spy, "spy_return_1d": spy / spy.shift(1) - 1,
                "spy_return_5d": spy / spy.shift(5) - 1, "vix_close": vix}
    result["context_checks"] = {c: compare(f[c], f.Date.map(values)) for c, values in contexts.items()}
    returns = p.sort_values(["ticker", "Date"]).copy()
    returns["adjusted_return"] = returns.groupby("ticker")["Adj Close"].pct_change()
    result["corporate_actions"] = {"split_rows": int(p["Stock Splits"].ne(0).sum()),
                                    "dividend_rows": int(p.Dividends.ne(0).sum()),
                                    "split_day_max_abs_adjusted_return": float(returns.loc[returns["Stock Splits"].ne(0), "adjusted_return"].abs().max()),
                                    "adjusted_returns_over_50pct": returns.loc[returns.adjusted_return.abs().gt(.5), ["ticker", "Date", "adjusted_return"]].astype({"Date":str}).to_dict("records"),
                                    "vintage_verified": False}
    # Prefix calculations must agree with the full sample at historical origins.
    prefix_checks = {}
    for ticker in ("AAPL", "SPY", "NVDA"):
        group = p.loc[p.ticker.eq(ticker)].sort_values("Date").reset_index(drop=True)
        complete = expected_ticker(group)
        prefix = expected_ticker(group.iloc[:700])
        prefix_checks[ticker] = sum(compare(complete[c].iloc[:700], prefix[c])["mismatches"]
                                    for c in columns if c != "target_return_10d")
    result["prefix_invariance_predictor_mismatches"] = prefix_checks
    # Match each macro candidate against only observations whose proxy availability
    # is no later than that feature's exchange date. This cannot prove vintage truth.
    macro_checks = {}
    names = {"DFF":"federal_funds_rate", "DGS10":"treasury_yield_10y", "VIXCLS":"fred_vix", "CPIAUCSL":"inflation_cpi_yoy"}
    for sid, name in names.items():
        series = m.loc[m.series_id.eq(sid)].sort_values("observation_date").copy()
        if sid == "CPIAUCSL":
            series["value"] = (series.value / series.value.shift(12) - 1) * 100
        series = series.sort_values("available_date").drop_duplicates("available_date", keep="last")
        # Builder forward-fills every macro context field; audit its semantics explicitly.
        series["value"] = series.value.ffill()
        origins = fm[["Date", name]].sort_values("Date").copy()
        origins.Date = origins.Date.astype("datetime64[ns]")
        series.available_date = series.available_date.astype("datetime64[ns]")
        merged = pd.merge_asof(origins, series[["available_date", "value"]], left_on="Date", right_on="available_date", direction="backward")
        lags = (m.loc[m.series_id.eq(sid),"available_date"] - m.loc[m.series_id.eq(sid),"observation_date"]).dt.days
        macro_checks[sid] = {"rows": len(series), "observation_first": str(series.observation_date.min().date()),
                            "observation_last": str(series.observation_date.max().date()),
                            "available_last": str(series.available_date.max().date()),
                            "availability_lag_days": sorted(int(n) for n in lags.unique()),
                            "available_before_observation": int((lags < 0).sum()),
                            "proxy_join": compare(merged[name], merged.value),
                            "future_proxy_rows_joined": int((merged.available_date > merged.Date).sum())}
    cpi_dates = m.loc[m.series_id.eq("CPIAUCSL"), "observation_date"].sort_values()
    cpi_expected = pd.date_range(cpi_dates.min(), cpi_dates.max(), freq="MS")
    result["macro"] = {"series_checks": macro_checks, "realtime_end_non_null": int(m.realtime_end.notna().sum()),
                       "missing_cpi_months": [str(d.date()) for d in cpi_expected if d not in set(cpi_dates)],
                       "vintage_verified": False}
    # Illustrative untouched holdout and expanding folds. Counts include a purge by
    # realized label end, strictly before the next split's first prediction origin.
    folds = []
    for boundary, end in (("2024-01-01","2024-12-31"), ("2025-01-01","2025-12-31"), ("2026-01-01","2026-09-18")):
        start, stop = pd.Timestamp(boundary), pd.Timestamp(end)
        train = joined.Date.lt(start) & joined.target_return_10d.notna()
        evaluation = joined.Date.ge(start) & joined.Date.le(stop) & joined.target_return_10d.notna()
        mature = train & joined.label_end.lt(start)
        evaluation_mature = evaluation & joined.label_end.le(stop)
        folds.append({"evaluation_start": boundary,"evaluation_end": end,
                      "naive_train_rows": int(train.sum()),"purged_overlap_rows": int((train & ~mature).sum()),
                      "mature_train_rows": int(mature.sum()),"evaluation_rows":int(evaluation_mature.sum()),
                      "naive_evaluation_rows":int(evaluation.sum()),
                      "purged_evaluation_tail_rows":int((evaluation & ~evaluation_mature).sum()),
                      "cross_ticker_common_date_boundaries": True})
    result["split_example"] = folds
    result["status"] = {"price_only_after_close_offline_research": "CONDITIONAL",
                        "historical_macro_enriched_comparison": "BLOCKED",
                        "current_forecast_serving": "BLOCKED",
                        "broad_market_generalization": "BLOCKED"}
    structural = sum(v["duplicate_keys"] for v in result["sources"].values())
    formula_errors = sum(v["mismatches"] for v in result["independent_formula_checks"].values())
    context_errors = sum(v["mismatches"] for v in result["context_checks"].values())
    plausibility_errors = sum(result["price_plausibility"][c] for c in
                              ("nonpositive_ohlc_or_adjusted", "invalid_ohlc_range", "negative_volume", "weekend_rows"))
    result["integrity_pass"] = not (structural or formula_errors or context_errors or plausibility_errors
        or result["sources"]["prices"]["missing"] or result["sources"]["prices"]["infinite"]
        or result["sources"]["baseline"]["infinite"]
        or not result["candidate_identity"]["baseline_equals_price_candidate"]
        or not result["candidate_identity"]["macro_base_columns_equal"]
        or sum(prefix_checks.values())
        or any(coverage[t]["missing_spy_sessions"] for t in eligible)
        or result["eligibility"]["universe_without_raw"]
        or result["eligibility"]["missing_eligible"] or result["eligibility"]["unexpected_features"]
        or result["labels"]["training_flag_mismatches"])
    if not result["integrity_pass"]:
        result["status"]["price_only_after_close_offline_research"] = "BLOCKED"
    result["sources_unchanged"] = hashes == {k: sha256(path) for k, path in sources.items()}
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DATA)
    parser.add_argument("--output", type=Path, default=DATA / "artifacts/evaluation/numeric_gate.json")
    args = parser.parse_args()
    # Demonstrate comparison failure behavior including missing-label disagreement.
    assert compare([1, np.nan], [1, np.nan])["mismatches"] == 0
    assert compare([2, np.nan], [1, 0])["mismatches"] == 2
    try:
        result = audit(args.data_dir)
    except (OSError, ValueError, KeyError) as exc:
        print(f"Numeric gate could not complete ({type(exc).__name__}); no readiness pass issued.")
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps({"integrity_pass": result["integrity_pass"], "status": result["status"],
                      "sources_unchanged": result["sources_unchanged"], "evidence": str(args.output)}, indent=2))
    return 0 if result["integrity_pass"] and result["sources_unchanged"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
