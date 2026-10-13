"""Inference uses current input rows, never stored predictions or future labels."""
import asyncio
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from app.services.forecast_inference import ForecastInferenceService, load_saved_model
from app.services.forecasts import ForecastUnavailable
from data.forecasting.inputs import RELATIVE_FEATURES


class Bundle:
    metadata = {'selected_model':'XGBoost test','eligible_tickers':['AAPL'], 'as_of':'2023-01-01'}
    calibration = {'latest_outcome':'2022-12-30','coverage':.9}

    def predict(self, frame):
        # A predictor-only fake exposes changed inputs without fitting anything.
        p=frame.return_1d.to_numpy()
        return pd.DataFrame({'Date':frame.Date.to_numpy(),'ticker':frame.ticker.to_numpy(),'predicted_return_10d':p,'lower_return':p-.05,
                             'upper_return':p+.05,'uncertainty_width_pp':10.,'nominal_coverage':.9})


def records():
    feature={name:.01 for name in RELATIVE_FEATURES}
    feature.update(ticker='AAPL',Date='2024-11-01',rolling_volatility_20=.2)
    return {'prepared':[feature],'snapshot_as_of':'2024-11-01','model_sha256':'a'*64}


def test_new_snapshot_features_change_prediction_without_labels_or_fit():
    data=records()
    bundle=Bundle()
    bundle._loaded_model_sha256='a'*64
    first=ForecastInferenceService._predict(bundle,{},data,['AAPL','GEV'])
    data['prepared'][0]['return_1d']=.03
    second=ForecastInferenceService._predict(bundle,{},data,['AAPL'])
    assert first.forecasts[0].predicted_return_10d==.01
    assert second.forecasts[0].predicted_return_10d==.03
    assert first.unavailable_tickers==['GEV']
    assert first.source_mode=='saved_model_inference'
    assert first.forecasts[0].stale_snapshot
    assert 'target_return_10d' not in data['prepared'][0]


def test_snapshot_from_different_model_is_rejected():
    bundle=Bundle()
    bundle._loaded_model_sha256='b'*64
    with pytest.raises(ValueError,match='different versions'):
        ForecastInferenceService._predict(bundle,{},records(),['AAPL'])


def test_input_driver_failure_is_sanitized_and_no_csv_fallback():
    class Source:
        async def read(self,_):
            raise RuntimeError('secret connection text')
    service=ForecastInferenceService(Source(),Path('/unused'),loader=lambda _: (Bundle(),{}))
    with pytest.raises(ForecastUnavailable) as failure:
        asyncio.run(service.get_snapshot(['AAPL']))
    assert 'secret' not in str(failure.value)


def test_tampered_bundle_rejected_before_deserialization(tmp_path,monkeypatch):
    import joblib
    (tmp_path/'manifest.json').write_text(json.dumps({'format_version':1,'model_sha256':'0'*64}))
    (tmp_path/'model.joblib').write_bytes(b'not trusted pickle')
    monkeypatch.setattr(joblib,'load',lambda _: pytest.fail('tampered bytes deserialized'))
    with pytest.raises(ValueError,match='hash mismatch'):
        load_saved_model(str(tmp_path))
