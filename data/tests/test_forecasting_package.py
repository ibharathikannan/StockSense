"""Deployment export binds learned artifact and label-free predictors atomically."""
import hashlib
import json
import numpy as np
import pandas as pd
import pytest
from data.forecasting.inputs import RELATIVE_FEATURES
from data.forecasting.package import export_package

class Bundle:
    metadata={'selected_model':'XGBoost test','eligible_tickers':['AAPL']}
    calibration={'latest_outcome':'2023-12-29','coverage':.9}
    def predict(self,rows):
        result=rows[['Date','ticker']].copy()
        result['predicted_return_10d']=.01
        result['lower_return']=-.04
        result['upper_return']=.06
        result['uncertainty_width_pp']=10.
        result['nominal_coverage']=.9
        return result

def frame():
    result=pd.DataFrame({name:[.01,.02] for name in RELATIVE_FEATURES})
    result['Date']=pd.to_datetime(['2024-01-02','2024-01-03'])
    result['ticker']='AAPL'
    result['target_return_10d']=999.
    return result

def test_package_contains_only_latest_predictors_with_bound_file_hashes(tmp_path):
    bundle=Bundle();bundle.metadata=dict(Bundle.metadata)
    output=tmp_path/'version-one'
    manifest=export_package(bundle,frame(),output,{'source':'unit'})
    inputs=pd.read_csv(output/'inference_features.csv')
    assert list(inputs)==['Date','ticker',*RELATIVE_FEATURES]
    assert len(inputs)==1
    assert 'target_return_10d' not in inputs
    for name,key in [('model.joblib','model_sha256'),('inference_features.csv','inference_features_sha256'),('report.json','report_sha256')]:
        assert hashlib.sha256((output/name).read_bytes()).hexdigest()==manifest[key]
    assert not list(tmp_path.glob('.forecast-package-*'))
    with pytest.raises(ValueError,match='exists'):
        export_package(bundle,frame(),output,{})

def test_invalid_inputs_produce_no_package(tmp_path):
    rows=frame();rows.loc[1,'return_1d']=np.inf
    with pytest.raises(ValueError,match='Invalid predictor'):
        export_package(Bundle(),rows,tmp_path/'invalid',{})
    assert not (tmp_path/'invalid').exists()
