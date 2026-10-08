"""Forecasting regressions: date purges, calibration and training-only transforms."""
import numpy as np
import pandas as pd
import pytest

from data.forecasting.inputs import RELATIVE_FEATURES
from data.forecasting.models import train_model


@pytest.fixture
def frame():
    dates = pd.bdate_range("2020-01-01", periods=360)
    n = len(dates)
    values = np.arange(n, dtype=float)
    data = pd.DataFrame({name: np.sin(values / (8 + j)) + values / 100
                         for j, name in enumerate(RELATIVE_FEATURES)})
    data["Date"] = dates
    data["ticker"] = "AAPL"
    data["label_end_date"] = pd.Series(dates).shift(-10)
    data["target_return_10d"] = .01 + .02 * np.sin(values / 11)
    data.loc[data["label_end_date"].isna(), "target_return_10d"] = np.nan
    data["is_training_row"] = data["target_return_10d"].notna()
    data["Adj Close"] = 100 + values
    return data


@pytest.fixture
def boundaries(frame):
    return {"tuning_start": str(frame.loc[120, "Date"].date()),
            "calibration_start": str(frame.loc[200, "Date"].date()),
            "evaluation_start": str(frame.loc[280, "Date"].date()),
            "min_training_rows": 50}


def test_calibration_intervals_are_finite_ordered_and_input_not_mutated(frame, boundaries):
    original = frame.copy(deep=True)
    bundle = train_model(frame, model="mean", **boundaries)
    latest = frame.tail(10)
    result = bundle.predict(latest)
    assert result["ticker"].tolist() == latest["ticker"].tolist()
    assert pd.to_datetime(result["Date"]).tolist() == latest["Date"].tolist()
    assert len(result) == 10  # forecast latest rows without labels
    assert np.isfinite(result[["predicted_return_10d", "lower_return", "upper_return", "uncertainty_width_pp"]]).all().all()
    assert (result["lower_return"] <= result["predicted_return_10d"]).all()
    assert (result["upper_return"] >= result["predicted_return_10d"]).all()
    assert result["uncertainty_width_pp"].gt(0).all()
    np.testing.assert_allclose(result["uncertainty_width_pp"],
                               100 * (result["upper_return"] - result["lower_return"]))
    assert result["nominal_coverage"].eq(.9).all()
    pd.testing.assert_frame_equal(frame, original)


def test_evaluation_targets_cannot_influence_model_or_calibration(frame, boundaries):
    base = train_model(frame, model="mean", **boundaries)
    changed = frame.copy()
    after = changed["Date"].ge(pd.Timestamp(boundaries["evaluation_start"]))
    changed.loc[after & changed["target_return_10d"].notna(), "target_return_10d"] = 999
    alternative = train_model(changed, model="mean", **boundaries)
    pd.testing.assert_frame_equal(base.predict(frame.tail(10)), alternative.predict(frame.tail(10)))


def test_unmatured_precalibration_labels_are_purged(frame, boundaries):
    base = train_model(frame, model="mean", **boundaries)
    changed = frame.copy()
    cutoff = pd.Timestamp(boundaries["calibration_start"])
    crossing = changed["Date"].lt(cutoff) & changed["label_end_date"].ge(cutoff)
    assert crossing.sum() == 10
    changed.loc[crossing, "target_return_10d"] = 999
    alternative = train_model(changed, model="mean", **boundaries)
    pd.testing.assert_frame_equal(base.predict(frame.tail(10)), alternative.predict(frame.tail(10)))


def test_unmatured_calibration_labels_are_purged(frame, boundaries):
    base = train_model(frame, model="mean", **boundaries)
    changed = frame.copy()
    cutoff = pd.Timestamp(boundaries["evaluation_start"])
    crossing = changed["Date"].lt(cutoff) & changed["label_end_date"].ge(cutoff)
    assert crossing.sum() == 10
    changed.loc[crossing, "target_return_10d"] = 999
    alternative = train_model(changed, model="mean", **boundaries)
    pd.testing.assert_frame_equal(base.predict(frame.tail(10)), alternative.predict(frame.tail(10)))


@pytest.mark.parametrize("failure", ["infinite", "empty_calibration", "bad_boundaries"])
def test_invalid_inputs_fail_closed(frame, boundaries, failure):
    if failure == "infinite":
        frame.loc[0, RELATIVE_FEATURES[0]] = np.inf
    elif failure == "empty_calibration":
        dates = frame["Date"]
        frame = frame.loc[~dates.between(pd.Timestamp(boundaries["calibration_start"]),
                                         pd.Timestamp(boundaries["evaluation_start"]), inclusive="left")]
    else:
        boundaries["evaluation_start"] = boundaries["tuning_start"]
    with pytest.raises(ValueError):
        train_model(frame, model="mean", **boundaries)


def test_calibration_requires_distinct_session_coverage(frame, boundaries):
    cal = frame["Date"].ge(pd.Timestamp(boundaries["calibration_start"])) & frame["Date"].lt(pd.Timestamp(boundaries["evaluation_start"]))
    # Keep only twenty sessions: many rows from one day must not substitute for history.
    keep = frame.loc[cal, "Date"].iloc[:20]
    reduced = frame.loc[~cal | frame["Date"].isin(keep)]
    with pytest.raises(ValueError):
        train_model(reduced, model="mean", **boundaries)


def test_missing_predictor_schema_fails(frame, boundaries):
    with pytest.raises(ValueError):
        train_model(frame.drop(columns=[RELATIVE_FEATURES[0]]), model="mean", **boundaries)


def test_ridge_preprocessing_fitted_on_purged_training_only(frame, boundaries):
    frame = frame.copy()
    frame.loc[5, "rsi_14"] = np.nan
    bundle = train_model(frame, model="ridge", **boundaries)
    cutoff = pd.Timestamp(boundaries["tuning_start"])
    train = frame.loc[frame["Date"].lt(cutoff) & frame["label_end_date"].lt(cutoff), list(RELATIVE_FEATURES)]
    imputer = bundle.estimator.named_steps["imputer"]
    scaler = bundle.estimator.named_steps["scaler"]
    np.testing.assert_allclose(imputer.statistics_, train.median().to_numpy())
    filled = train.fillna(train.median())
    np.testing.assert_allclose(scaler.mean_, filled.mean().to_numpy())
    assert scaler.n_samples_seen_ == len(train)
    assert len(train) == 110  # ten labels reaching the inner window were removed


def test_evaluation_metrics_match_predictions_without_refitting(frame, boundaries):
    from data.forecasting.models import evaluate
    bundle = train_model(frame, model="median", **boundaries)
    evaluation = frame.loc[frame["Date"].ge(pd.Timestamp(boundaries["evaluation_start"])) & frame["target_return_10d"].notna()]
    predictions = bundle.predict(evaluation)
    actual = evaluation["target_return_10d"].to_numpy()
    expected_mae = 100 * np.abs(actual - predictions["predicted_return_10d"].to_numpy()).mean()
    metrics = evaluate(bundle, frame)
    assert metrics["rows"] == len(evaluation)
    assert metrics["MAE_pp"] == pytest.approx(expected_mae)
    expected_coverage = ((actual >= predictions["lower_return"].to_numpy()) &
                         (actual <= predictions["upper_return"].to_numpy())).mean()
    assert metrics["interval_coverage"] == pytest.approx(expected_coverage)
    assert metrics["mean_interval_width_pp"] == pytest.approx(predictions["uncertainty_width_pp"].mean())


def test_trusted_local_bundle_roundtrip(frame, boundaries, tmp_path):
    import joblib
    bundle = train_model(frame, model="ridge", **boundaries)
    path = tmp_path / "model.joblib"
    joblib.dump(bundle, path)
    restored = joblib.load(path)
    pd.testing.assert_frame_equal(bundle.predict(frame.tail(10)), restored.predict(frame.tail(10)))


def test_intraday_boundary_is_rejected_before_date_metadata_can_truncate_it(frame, boundaries):
    boundaries["calibration_start"] += " 12:00:00"
    with pytest.raises(ValueError, match="completed-session"):
        train_model(frame, model="mean", **boundaries)


def test_requested_xgboost_stays_learned_and_excludes_later_outcomes(frame, boundaries):
    pytest.importorskip("xgboost")
    first = train_model(frame, model="xgboost", **boundaries)
    assert first.metadata["selected_model"].startswith("XGBoost rounds=")
    assert len(first.metadata["selection"]) == 3
    assert all(record["model"].startswith("XGBoost") for record in first.metadata["selection"])
    changed = frame.copy()
    later = changed.Date.ge(boundaries["evaluation_start"]) & changed.target_return_10d.notna()
    changed.loc[later, "target_return_10d"] = 999
    second = train_model(changed, model="xgboost", **boundaries)
    pd.testing.assert_frame_equal(first.predict(frame.tail(10)), second.predict(frame.tail(10)))
    np.testing.assert_allclose(first.estimator.named_steps["imputer"].statistics_,
                              frame.loc[frame.Date.lt(boundaries["tuning_start"])
                                        & frame.label_end_date.lt(boundaries["tuning_start"]),
                                        list(RELATIVE_FEATURES)].median())


def test_refit_uses_only_labels_matured_before_calibration(frame, boundaries):
    bundle = train_model(frame, model="ridge", refit_selected=True, **boundaries)
    cutoff = pd.Timestamp(boundaries["calibration_start"])
    refit = frame.loc[frame.Date.lt(cutoff) & frame.label_end_date.lt(cutoff), list(RELATIVE_FEATURES)]
    np.testing.assert_allclose(bundle.estimator.named_steps["imputer"].statistics_, refit.median())
    np.testing.assert_allclose(bundle.estimator.named_steps["scaler"].mean_, refit.mean())
    assert bundle.metadata["partitions"]["refit"]["rows"] == 190
    assert bundle.metadata["selected_parameters"]["alpha"] in (100, 1000)
    changed = frame.copy()
    changed.loc[changed.Date.ge(cutoff), "target_return_10d"] = .5
    changed.loc[changed.label_end_date.isna(), "target_return_10d"] = np.nan
    alternative = train_model(changed, model="ridge", refit_selected=True, **boundaries)
    # Calibration outcomes legitimately change interval widths, but never the fitted predictor.
    np.testing.assert_allclose(bundle.estimator.predict(frame[list(RELATIVE_FEATURES)]),
                               alternative.estimator.predict(frame[list(RELATIVE_FEATURES)]))


def test_refit_baselines_use_same_purged_history(frame, boundaries):
    bundle = train_model(frame, model="mean", refit_selected=True, **boundaries)
    cutoff = pd.Timestamp(boundaries["calibration_start"])
    targets = frame.loc[frame.Date.lt(cutoff) & frame.label_end_date.lt(cutoff), "target_return_10d"]
    assert bundle.estimator.value == pytest.approx(targets.mean())
    assert bundle.metadata["training_mean"] == pytest.approx(targets.mean())
    assert bundle.metadata["training_median"] == pytest.approx(targets.median())


@pytest.mark.parametrize("grid", [[], [{}] * 25, [{"n_jobs": 99}], [{"n_estimators": 1.5}],
                                    [{"learning_rate": 0}], [{"max_depth": 9}],
                                    [{"reg_lambda": np.inf}], [{"subsample": True}], [{}, {}]])
def test_custom_grid_rejects_unbounded_or_ambiguous_settings(frame, boundaries, grid):
    with pytest.raises(ValueError):
        train_model(frame, model="xgboost", xgboost_grid=grid, **boundaries)
