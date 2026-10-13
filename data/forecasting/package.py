"""Export a versioned model-and-feature deployment package without training."""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import shutil
import tempfile

import joblib
import numpy as np
import pandas as pd

from .inputs import RELATIVE_FEATURES
from .models import FORMAT_VERSION


def export_package(bundle, frame, output_dir, provenance, *, evaluation=None):
    output = Path(output_dir)
    if output.exists():
        raise ValueError('Output directory exists; preserve previous deployment versions')
    latest = frame.loc[frame.ticker.isin(bundle.metadata['eligible_tickers'])].sort_values(
        ['Date','ticker']).groupby('ticker').tail(1).sort_values('ticker')
    if latest.empty or latest.duplicated('ticker').any():
        raise ValueError('Nonempty unique latest inputs required')
    features = latest[['Date','ticker',*RELATIVE_FEATURES]].copy()
    features['Date'] = pd.to_datetime(features.Date)
    now = datetime.now(timezone.utc)
    if features.Date.isna().any() or (features.Date.dt.date > now.date()).any():
        raise ValueError('Invalid completed-session dates')
    strict = [n for n in RELATIVE_FEATURES if n not in ('rsi_14','volume_change_1d')]
    if np.isinf(features[list(RELATIVE_FEATURES)].to_numpy(dtype=float)).any() or not np.isfinite(features[strict].to_numpy(dtype=float)).all():
        raise ValueError('Invalid predictor values')
    # No fitting: audit that the saved model accepts this feature snapshot.
    forecasts = bundle.predict(features)
    timestamp = now.isoformat()
    as_of = str(features.Date.max().date())
    versions={n:importlib.metadata.version(n) for n in
              ('numpy','pandas','scikit-learn','joblib','xgboost')}
    if bundle.metadata.get('versions',versions) != versions:
        raise ValueError('Package environment must match saved-model training versions')
    bundle.metadata.setdefault('as_of',as_of)
    bundle.metadata.setdefault('created_at_utc',timestamp)
    bundle.metadata.setdefault('source_provenance',provenance)
    bundle.metadata['versions']=versions
    forecasts['generated_at_utc'] = timestamp
    forecasts['calibration_latest_outcome'] = bundle.calibration['latest_outcome']
    forecasts['data_age_calendar_days'] = (pd.Timestamp(now.date())-pd.to_datetime(forecasts.Date)).dt.days
    forecasts['stale_snapshot'] = forecasts.data_age_calendar_days.gt(7)
    report = {'metadata':bundle.metadata,'calibration':bundle.calibration,
              'generated_at_utc':timestamp,'as_of':as_of,'feature_provenance':provenance,'evaluation':evaluation or {},
              'limitations':['Forecast origins are uploaded snapshot dates, not request dates',
                             'Manual refresh/retraining only; no provider access in production',
                             'Intervals are empirical, not guarantees or confidence scores',
                             'Historical model comparisons do not establish reliable directional skill']}
    output.parent.mkdir(parents=True,exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.forecast-package-',dir=output.parent))
    try:
        features.to_csv(staging/'inference_features.csv',index=False)
        forecasts.to_csv(staging/'forecasts.csv',index=False)
        joblib.dump(bundle,staging/'model.joblib')
        (staging/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
        digest = lambda name:hashlib.sha256((staging/name).read_bytes()).hexdigest()
        manifest = {'format_version':FORMAT_VERSION,'selected_model':bundle.metadata['selected_model'],
                    'model_sha256':digest('model.joblib'),'report_sha256':digest('report.json'),
                    'inference_features_sha256':digest('inference_features.csv'),
                    'inference_feature_names':list(RELATIVE_FEATURES),
                    'feature_names':list(RELATIVE_FEATURES),'feature_as_of':as_of,
                    'as_of':as_of,'generated_at_utc':timestamp,'source_provenance':provenance}
        (staging/'manifest.json').write_text(json.dumps(manifest,indent=2,allow_nan=False)+'\n')
        staging.rename(output)
        return manifest
    finally:
        if staging.exists():shutil.rmtree(staging)
