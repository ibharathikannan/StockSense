"""Saved-model inference only. No fitting, provider downloads or data writes."""
from __future__ import annotations
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import io
import json
from pathlib import Path
import re

from app.schemas.forecast import ForecastItem, ForecastSnapshot
from app.services.errors import BadRequest
from app.services.forecasts import ForecastUnavailable


@lru_cache(maxsize=2)
def load_saved_model(directory: str):
    """Trusted administrator-configured artifacts only; restart to replace a model."""
    import importlib.metadata
    import joblib
    from data.forecasting.models import ForecastBundle, FORMAT_VERSION
    from data.forecasting.inputs import RELATIVE_FEATURES

    root = Path(directory)
    manifest = json.loads((root/'manifest.json').read_text())
    if manifest.get('format_version') != FORMAT_VERSION:
        raise ValueError('Unsupported saved-model format')
    path = root/'model.joblib'
    if path.stat().st_size > 512_000_000:
        raise ValueError('Saved model exceeds size limit')
    payload = path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != manifest.get('model_sha256'):
        raise ValueError('Saved-model hash mismatch')
    # Deserialize the exact verified bytes, not a second mutable file read.
    # Hashes detect accidents; only a trusted artifact producer prevents malicious pickle.
    bundle = joblib.load(io.BytesIO(payload))
    if not isinstance(bundle, ForecastBundle) or tuple(bundle.feature_names) != RELATIVE_FEATURES:
        raise ValueError('Saved-model predictor contract mismatch')
    if not bundle.metadata['selected_model'].startswith('XGBoost'):
        raise ValueError('Configured artifact must be the selected XGBoost model')
    versions = bundle.metadata.get('versions', {})
    for name in ('numpy', 'pandas', 'scikit-learn', 'xgboost', 'joblib'):
        if versions.get(name) != importlib.metadata.version(name):
            raise ValueError('Runtime versions differ from the saved-model environment')
    report_bytes = (root/'report.json').read_bytes()
    if manifest.get('report_sha256') and hashlib.sha256(report_bytes).hexdigest() != manifest['report_sha256']:
        raise ValueError('Report hash mismatch')
    report = json.loads(report_bytes)
    bundle._loaded_model_sha256 = manifest['model_sha256']
    if report.get('metadata', {}).get('selected_model') != bundle.metadata['selected_model']:
        raise ValueError('Report does not match configured model')
    return bundle, report.get('evaluation', {})


class ForecastInferenceService:
    def __init__(self, inputs, directory: Path, *, loader=load_saved_model):
        self.inputs, self.directory, self.loader = inputs, directory, loader

    async def get_snapshot(self, tickers: list[str]) -> ForecastSnapshot:
        if (not 1 <= len(tickers) <= 90 or len(set(tickers)) != len(tickers)
            or any(not isinstance(t,str) or not re.fullmatch(r'[A-Z0-9][A-Z0-9.\-^=]{0,15}',t) for t in tickers)):
            raise BadRequest('Provide 1 to 90 distinct valid selected tickers')
        from starlette.concurrency import run_in_threadpool
        try:
            # Native deserialization / dataframe work runs outside the event loop.
            bundle, evaluation = await run_in_threadpool(self.loader, str(self.directory.resolve()))
            records = await self.inputs.read(tickers)
            return await run_in_threadpool(self._predict, bundle, evaluation, records, tickers)
        except BadRequest:
            raise
        except Exception:
            # Driver errors can include credentials. Fail closed without CSV fallback.
            raise ForecastUnavailable() from None

    @staticmethod
    def _predict(bundle,evaluation,records,tickers):
        import pandas as pd
        from data.forecasting.inputs import RELATIVE_FEATURES
        if getattr(bundle,'_loaded_model_sha256',None) != records['model_sha256']:
            raise ValueError('Model and predictor snapshot belong to different versions')
        now=datetime.now(timezone.utc)
        items=[]
        frame=pd.DataFrame(records['prepared'])
        available=[]
        if not frame.empty:
            frame['Date']=pd.to_datetime(frame.Date)
            if frame.Date.isna().any() or (frame.Date.dt.date>now.date()).any():
                raise ValueError('Invalid predictor origin dates')
            frame=frame.loc[frame.ticker.isin(bundle.metadata['eligible_tickers'])]
            if not frame.empty:
                predicted=bundle.predict(frame[['Date','ticker',*RELATIVE_FEATURES]])
                for row in predicted.itertuples(index=False):
                    age=(now.date()-row.Date.date()).days
                    items.append(ForecastItem(ticker=row.ticker,date=row.Date.date(),
                        predicted_return_10d=row.predicted_return_10d,lower_return=row.lower_return,
                        upper_return=row.upper_return,uncertainty_width_pp=row.uncertainty_width_pp,
                        nominal_coverage=row.nominal_coverage,stale_snapshot=age>7,
                        data_age_calendar_days=age,calibration_latest_outcome=bundle.calibration['latest_outcome']))
                    available.append(row.ticker)
        return ForecastSnapshot(model=bundle.metadata['selected_model'],
            as_of=pd.Timestamp(records['snapshot_as_of']).date(),generated_at=now,
            nominal_coverage=bundle.calibration['coverage'],forecasts=items,
            selected_tickers=tickers,unavailable_tickers=[t for t in tickers if t not in available],
            source_mode='saved_model_inference',status='experimental_saved_model_inference',
            model_as_of=bundle.metadata.get('as_of'),empirical_coverage=evaluation.get('interval_coverage'),
            evaluation_mae_pp=evaluation.get('MAE_pp'),direction_accuracy_pct=evaluation.get('direction_accuracy_pct'),
            always_up_accuracy_pct=evaluation.get('always_up_accuracy_pct'))
