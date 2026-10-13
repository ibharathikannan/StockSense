"""Bounded retrospective yearly XGBoost selection and interval evaluation.

Run sequentially; no provider downloads, database writes or application changes.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from .__main__ import DATA, _forecasts, _json
from .inputs import build_inputs
from .models import FORMAT_VERSION, TARGET, evaluate, train_model
from .sources import load_local

# Predeclared bounded grid. Outer-year scores never choose a candidate.
GRID = tuple(
    dict(n_estimators=rounds, max_depth=depth, learning_rate=rate,
         min_child_weight=100, reg_lambda=20, subsample=1, colsample_bytree=1)
    for depth, rate in ((1, .03), (2, .03), (3, .03), (2, .1))
    for rounds in (10, 50, 150)
)


def paired_intervals(bundle, frame, *, repeats=1000, seed=42):
    """Resample contiguous origin-date blocks, retaining cross-ticker dependence."""
    predictions = bundle.predict(frame)
    y = frame[TARGET].to_numpy()
    p = predictions.predicted_return_10d.to_numpy()
    baseline = bundle.metadata['training_median']
    losses = pd.DataFrame({'Date': frame.Date.to_numpy(),
                          'gain': (np.abs(y-baseline)-np.abs(y-p))*100})
    daily = losses.groupby('Date').gain.agg(['sum', 'count'])
    rng = np.random.default_rng(seed)
    records = []
    for length in (10, 20, 40):
        if len(daily) < length:
            continue
        samples = []
        for _ in range(repeats):
            starts = rng.integers(0, len(daily)-length+1,
                                  size=int(np.ceil(len(daily)/length)))
            indices = np.concatenate([np.arange(s, s+length) for s in starts])[:len(daily)]
            selected = daily.iloc[indices]
            samples.append(selected['sum'].sum()/selected['count'].sum())
        lower, upper = np.quantile(samples, [.025, .975])
        records.append({'block_sessions': length,
                        'mae_gain_vs_median_pp': float(losses.gain.mean()),
                        'lower_95_pp': float(lower), 'upper_95_pp': float(upper),
                        'exploratory_no_multiple_testing_correction': True})
    return records


def run(output: Path, *, as_of='2026-09-18'):
    if output.exists():
        raise ValueError('Choose a new output directory; existing runs are preserved')
    candidate = DATA/'artifacts/market/price_only_features.parquet'
    features = candidate if candidate.is_file() else DATA/'processed/forecast_features.parquet'
    f, p, u, provenance = load_local(features, DATA/'raw/historical_prices.parquet',
                                      DATA/'asset_universe.csv')
    frame = build_inputs(f, p, u, as_of=as_of)
    reports = []
    final = None
    # All years have previously been inspected: retrospective, not untouched tests.
    for year in (2024, 2025, 2026):
        prior = year-1
        development = frame.loc[frame.Date.lt(f'{year+1}-01-01')].copy()
        bundle = train_model(development, tuning_start=f'{prior}-07-01',
                             calibration_start=f'{prior}-10-01',
                             evaluation_start=f'{year}-01-01', model='xgboost',
                             xgboost_grid=GRID, refit_selected=True)
        evaluation = development.loc[
            development.Date.ge(f'{year}-01-01') & development[TARGET].notna()
            & development.label_end_date.lt(f'{year+1}-01-01')
            & development.ticker.isin(bundle.metadata['eligible_tickers'])].copy()
        metrics = evaluate(bundle, evaluation)
        intervals = paired_intervals(bundle, evaluation)
        ridge = train_model(development, tuning_start=f'{prior}-07-01',
                            calibration_start=f'{prior}-10-01',
                            evaluation_start=f'{year}-01-01', model='ridge',
                            refit_selected=True)
        baselines = {}
        for name in ('mean', 'median'):
            constant = train_model(development, tuning_start=f'{prior}-07-01',
                                   calibration_start=f'{prior}-10-01',
                                   evaluation_start=f'{year}-01-01', model=name,
                                   refit_selected=True)
            baselines[name] = evaluate(constant, evaluation)
        reports.append({'year': year, 'metadata': bundle.metadata,
                        'calibration': bundle.calibration, 'xgboost': metrics,
                        'ridge': evaluate(ridge, evaluation), 'baselines': baselines,
                        'paired_mae_intervals': intervals})
        print(f'{year}: XGBoost MAE={metrics["MAE_pp"]:.4f} pp; '
              f'accuracy={metrics["direction_accuracy_pct"]:.2f}%; '
              f'coverage={metrics["interval_coverage"]:.2%}', flush=True)
        final = bundle
    timestamp = datetime.now(timezone.utc).isoformat()
    final.metadata.update(source_provenance=provenance, as_of=as_of,
                          created_at_utc=timestamp,
                          versions={n: importlib.metadata.version(n) for n in
                                    ('numpy','pandas','scikit-learn','xgboost','joblib')})
    forecasts = _forecasts(final, frame, timestamp)
    report = {'metadata': final.metadata, 'calibration': final.calibration,
              'generated_at_utc': timestamp, 'evaluation': reports[-1]['xgboost'],
              'walk_forward': reports, 'grid': list(GRID),
              'limitations': ['All scores are retrospective; no fresh untouched test',
                              'Fixed current universe and revised adjusted prices',
                              'Intervals are empirical; nominal coverage is not guaranteed',
                              'Hyperparameters selected on inner MAE, not direction accuracy',
                              'No claim of superiority; compare baselines and block intervals']}
    output.mkdir(parents=True, exist_ok=False)
    forecasts.to_csv(output/'forecasts.csv', index=False)
    _json(output/'report.json', report)
    joblib.dump(final, output/'model.joblib')
    _json(output/'manifest.json', {'format_version': FORMAT_VERSION,
          'model_sha256': hashlib.sha256((output/'model.joblib').read_bytes()).hexdigest(),
          'selected_model': final.metadata['selected_model'],
          'feature_names': list(final.feature_names), 'as_of': as_of,
          'source_provenance': provenance})
    print(f'Saved experimental run: {output}', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    run(args.output_dir)
