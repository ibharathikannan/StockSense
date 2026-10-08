"""Offline CLI regressions with trusted local artifacts and no network access."""
import json
from unittest.mock import patch

import numpy as np
import pandas as pd

from data.forecasting.__main__ import main
from data.forecasting.inputs import RELATIVE_FEATURES


def _frame():
    dates = pd.bdate_range("2020-01-01", periods=650)
    rows = np.arange(len(dates))
    frame = pd.DataFrame({name: .1 + np.sin(rows / 30) / 100 for name in RELATIVE_FEATURES})
    frame["Date"] = dates
    frame["ticker"] = "AAPL"
    frame["target_return_10d"] = .01 + np.sin(rows / 15) / 100
    frame["label_end_date"] = pd.Series(dates).shift(-10)
    frame.loc[frame.label_end_date.isna(), "target_return_10d"] = np.nan
    frame["is_training_row"] = frame.target_return_10d.notna()
    return frame


def _args(frame, command, output):
    return [command, "--as-of", str(frame.Date.max().date()), "--output-dir", str(output)]


def test_train_save_reload_predict_with_same_forecast_and_no_source_mutation(tmp_path):
    frame = _frame()
    original = frame.copy(deep=True)
    train_dir, predict_dir = tmp_path / "trained", tmp_path / "predicted"
    args = _args(frame, "train", train_dir) + [
        "--tuning-start", str(frame.loc[300, "Date"].date()),
        "--calibration-start", str(frame.loc[400, "Date"].date()),
        "--evaluation-start", str(frame.loc[500, "Date"].date()), "--model", "ridge"]
    with patch("data.forecasting.__main__.load_local", return_value=(None, None, None, {"source": "fixture"})), \
            patch("data.forecasting.__main__.build_inputs", return_value=frame):
        assert main(args) == 0
        assert main(_args(frame, "predict", predict_dir) + ["--model-dir", str(train_dir)]) == 0
    first = pd.read_csv(train_dir / "forecasts.csv")
    second = pd.read_csv(predict_dir / "forecasts.csv")
    pd.testing.assert_frame_equal(first.drop(columns="generated_at_utc"), second.drop(columns="generated_at_utc"))
    pd.testing.assert_frame_equal(frame, original)
    report = json.loads((train_dir / "report.json").read_text())
    assert report["evaluation"]["rows"] > 0
    assert report["metadata"]["selected_model"].startswith("Ridge")
    assert first.stale_snapshot.all()


def test_existing_output_is_preserved_without_reading_sources(tmp_path):
    output = tmp_path / "existing"
    output.mkdir()
    (output / "keep.txt").write_text("user content")
    with patch("data.forecasting.__main__._source") as read:
        assert main(["predict", "--model-dir", str(tmp_path), "--as-of", "2024-01-01",
                     "--output-dir", str(output)]) == 1
        read.assert_not_called()
    assert (output / "keep.txt").read_text() == "user content"


def test_modified_model_is_rejected_before_deserialization(tmp_path):
    from data.forecasting.__main__ import _load_bundle
    import pytest
    (tmp_path / "model.joblib").write_bytes(b"not a trusted serialized model")
    (tmp_path / "manifest.json").write_text(json.dumps({"format_version": 1, "model_sha256": "wrong"}))
    with patch("data.forecasting.__main__.joblib.load") as load:
        with pytest.raises(ValueError, match="hash"):
            _load_bundle(tmp_path)
        load.assert_not_called()


def test_source_failure_is_sanitized_and_writes_nothing(tmp_path, capsys):
    out = tmp_path / "run"
    with patch("data.forecasting.__main__._source", side_effect=ValueError("password=private")):
        assert main(["predict", "--as-of", "2024-01-01", "--model-dir", "trusted",
                     "--output-dir", str(out)]) == 1
    assert "private" not in capsys.readouterr().err
    assert not out.exists()
