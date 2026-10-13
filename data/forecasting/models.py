"""Train-only preprocessing, purged selection and separate interval calibration.

Intervals are empirical: market dependence and distribution shifts mean that
their nominal coverage is not a guaranteed probability for an individual asset.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import math
from numbers import Real

from sklearn.base import clone

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.metrics import balanced_accuracy_score, mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from .inputs import RELATIVE_FEATURES

TARGET = "target_return_10d"
HORIZON = 10
MINIMUM_SCALE = 0.005
FORMAT_VERSION = 1


@dataclass
class ConstantRegressor:
    """A persisted training-derived baseline with the same prediction interface."""

    value: float

    def predict(self, features: pd.DataFrame) -> np.ndarray:
        return np.full(len(features), self.value)


def _predictors(frame: pd.DataFrame, names: tuple[str, ...]) -> pd.DataFrame:
    absent = sorted(set(names) - set(frame))
    if absent:
        raise ValueError(f"Missing forecasting predictors: {absent}")
    result = frame.loc[:, list(names)].astype(float)
    if np.isinf(result.to_numpy()).any():
        raise ValueError("Infinite forecasting predictors are not permitted")
    return result


def _scale(frame: pd.DataFrame) -> np.ndarray:
    vol = frame["rolling_volatility_20"].to_numpy(dtype=float)
    if not np.isfinite(vol).all() or (vol < 0).any():
        raise ValueError("Volatility scale must be finite and nonnegative")
    return np.maximum(vol * np.sqrt(HORIZON / 252), MINIMUM_SCALE)


def _quantile(scores: np.ndarray, coverage: float) -> float:
    if not np.isfinite(scores).all() or len(scores) == 0:
        raise ValueError("Calibration requires finite nonempty residuals")
    rank = int(np.ceil((len(scores) + 1) * coverage))
    if rank > len(scores):
        raise ValueError("Too few calibration observations for the requested coverage")
    return float(np.sort(scores)[rank - 1])


def _xgboost_configs(grid):
    defaults = dict(n_estimators=1, max_depth=2, learning_rate=0.03,
                    min_child_weight=100, reg_lambda=20, subsample=1, colsample_bytree=1)
    if grid is None:
        return [dict(defaults, n_estimators=n) for n in (1, 10, 50)]
    if not isinstance(grid, (list, tuple)) or not 1 <= len(grid) <= 24:
        raise ValueError("XGBoost grid requires 1 to 24 parameter dictionaries")
    limits = {"n_estimators": (1, 1000), "max_depth": (1, 8),
              "learning_rate": (0, .3), "min_child_weight": (1, 10000),
              "reg_lambda": (0, 10000), "subsample": (0, 1), "colsample_bytree": (0, 1)}
    configs = []
    for item in grid:
        if not isinstance(item, dict) or set(item) - set(defaults):
            raise ValueError("Unsupported XGBoost grid parameters")
        config = dict(defaults, **item)
        for name, value in config.items():
            low, high = limits[name]
            if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
                raise ValueError("XGBoost parameters must be finite numbers")
            if not low <= value <= high or (name in {"learning_rate", "subsample", "colsample_bytree"} and value == 0):
                raise ValueError(f"XGBoost {name} outside bounded range")
            if name in {"n_estimators", "max_depth"} and value != int(value):
                raise ValueError(f"XGBoost {name} must be an integer")
            config[name] = int(value) if name in {"n_estimators", "max_depth"} else float(value)
        if config in configs:
            raise ValueError("Duplicate XGBoost parameter candidates")
        configs.append(config)
    return configs


@dataclass
class ForecastBundle:
    estimator: Any
    feature_names: tuple[str, ...]
    metadata: dict
    calibration: dict

    def predict(self, frame: pd.DataFrame) -> pd.DataFrame:
        if frame.empty:
            raise ValueError("No forecast rows supplied")
        origins = pd.to_datetime(frame["Date"])
        if origins.isna().any() or (origins < pd.Timestamp(self.metadata["evaluation_start"])).any():
            raise ValueError("Forecast origins must follow the completed calibration window")
        unknown = sorted(set(frame["ticker"]) - set(self.metadata["eligible_tickers"]))
        if unknown:
            raise ValueError(f"Tickers absent from model training: {unknown}")
        p = np.asarray(self.estimator.predict(_predictors(frame, self.feature_names)), dtype=float)
        if not np.isfinite(p).all():
            raise ValueError("Model produced nonfinite predictions")
        half_width = self.calibration["scaled_quantile"] * _scale(frame)
        result = frame[["Date", "ticker"]].copy()
        result["predicted_return_10d"] = p
        result["lower_return"] = p - half_width
        result["upper_return"] = p + half_width
        result["uncertainty_width_pp"] = half_width * 200
        result["nominal_coverage"] = self.calibration["coverage"]
        result["model"] = self.metadata["selected_model"]
        result["forecast_horizon_sessions"] = HORIZON
        result["status"] = "experimental_snapshot_forecast"
        return result


def train_model(
    frame: pd.DataFrame, *, tuning_start: str, calibration_start: str,
    evaluation_start: str, coverage: float = 0.9, model: str = "xgboost",
    min_training_rows: int = 252, min_calibration_dates: int = 30,
    xgboost_grid: list[dict] | tuple[dict, ...] | None = None, refit_selected: bool = False,
) -> ForecastBundle:
    """Choose Ridge/baselines on inner MAE, then calibrate a frozen estimator.

    Explicit boundaries are essential: no automatic use of the already inspected
    2025–2026 period as an untouched test. Rows with overlapping outcomes are purged.
    """
    if model not in {"auto", "ridge", "xgboost", "mean", "median"}:
        raise ValueError("Model must be auto, ridge, xgboost, mean or median")
    if not 0.5 <= coverage < 1:
        raise ValueError("Coverage must be at least 0.5 and below 1")
    if min_training_rows < 2 or min_calibration_dates < 2:
        raise ValueError("At least two training rows and calibration dates are required")
    bounds = [pd.Timestamp(x) for x in (tuning_start, calibration_start, evaluation_start)]
    if any(pd.isna(x) or x.tzinfo is not None or x != x.normalize() for x in bounds) or not bounds[0] < bounds[1] < bounds[2]:
        raise ValueError("Expected strictly ordered timezone-naive completed-session date boundaries")
    if not isinstance(refit_selected, bool):
        raise ValueError("refit_selected must be boolean")
    configs = _xgboost_configs(xgboost_grid)
    if xgboost_grid is not None and model not in {"auto", "xgboost"}:
        raise ValueError("XGBoost grid requires auto or xgboost model")
    names = tuple(RELATIVE_FEATURES)
    _predictors(frame, names)
    data = frame.copy()
    for column in ("Date", "label_end_date"):
        data[column] = pd.to_datetime(data[column])
    if data.duplicated(["ticker", "Date"]).any() or data["Date"].isna().any():
        raise ValueError("Duplicate or missing forecast origins")
    labeled = data[TARGET].notna()
    if not np.isfinite(data.loc[labeled, TARGET].to_numpy(dtype=float)).all():
        raise ValueError("Targets must be finite")
    if data.loc[labeled, "label_end_date"].isna().any() or (
        data.loc[labeled, "label_end_date"] <= data.loc[labeled, "Date"]
    ).any():
        raise ValueError("Labeled rows require a later outcome date")
    masks = {
        "training": labeled & (data.Date < bounds[0]) & (data.label_end_date < bounds[0]),
        "inner": labeled & (data.Date >= bounds[0]) & (data.Date < bounds[1]) & (data.label_end_date < bounds[1]),
        "calibration": labeled & (data.Date >= bounds[1]) & (data.Date < bounds[2]) & (data.label_end_date < bounds[2]),
    }
    counts = data.loc[masks["training"]].groupby("ticker").size()
    eligible = sorted(counts[counts >= min_training_rows].index.tolist())
    if not eligible:
        raise ValueError("No ticker has sufficient purged training history")
    parts = {key: data.loc[mask & data.ticker.isin(eligible)].sort_values(["Date", "ticker"])
             for key, mask in masks.items()}
    if any(part.empty for part in parts.values()):
        raise ValueError("Training, inner selection and calibration must all be nonempty")
    tr, inner, cal = (parts[key] for key in ("training", "inner", "calibration"))
    if cal.Date.nunique() < min_calibration_dates:
        raise ValueError("Calibration has insufficient distinct trading dates")
    for key, part in parts.items():
        missing_all = _predictors(part, names).isna().all()
        if missing_all.any():
            raise ValueError(f"All-missing predictors in {key}: {missing_all[missing_all].index.tolist()}")
    # Missing RSI/volume changes are replaced using training medians only.
    candidates: list[tuple[str, Any]] = []
    if model in {"auto", "xgboost"}:
        # Optional offline dependency: the web runtime serves validated results
        # and does not import or fit this estimator.
        from xgboost import XGBRegressor

        for index, config in enumerate(configs):
            pipe = Pipeline([
                ("imputer", SimpleImputer(strategy="median")),
                ("xgboost", XGBRegressor(
                    **config, objective="reg:squarederror",
                    tree_method="hist", n_jobs=2, random_state=42,
                )),
            ])
            pipe.fit(_predictors(tr, names), tr[TARGET])
            name = (f"XGBoost rounds={config['n_estimators']}" if xgboost_grid is None
                    else f"XGBoost grid={index + 1} rounds={config['n_estimators']}")
            candidates.append((name, pipe))
    if model in {"auto", "ridge"}:
        for alpha in (100.0, 1000.0):
            pipe = Pipeline([
                ("imputer", SimpleImputer(strategy="median")),
                ("scaler", StandardScaler()), ("ridge", Ridge(alpha=alpha)),
            ])
            pipe.fit(_predictors(tr, names), tr[TARGET])
            candidates.append((f"Ridge alpha={alpha:g}", pipe))
    if model in {"auto", "mean"}:
        candidates.append(("Training-mean baseline", ConstantRegressor(float(tr[TARGET].mean()))))
    if model in {"auto", "median"}:
        candidates.append(("Training-median baseline", ConstantRegressor(float(tr[TARGET].median()))))
    records = []
    for name, estimator in candidates:
        p = estimator.predict(_predictors(inner, names))
        records.append({"model": name, "inner_mae": float(mean_absolute_error(inner[TARGET], p)),
                        "inner_rmse": float(np.sqrt(mean_squared_error(inner[TARGET], p)))})
    choice = min(range(len(records)), key=lambda i: (records[i]["inner_mae"], records[i]["inner_rmse"]))
    selected_name, estimator = candidates[choice]
    fit_frame = tr
    if refit_selected:
        # Once parameters are fixed, labels previously purged at the inner
        # boundary may be used if their outcomes mature before calibration.
        fit_frame = data.loc[labeled & (data.Date < bounds[1]) &
                             (data.label_end_date < bounds[1]) & data.ticker.isin(eligible)].sort_values(["Date", "ticker"])
        if isinstance(estimator, ConstantRegressor):
            value = fit_frame[TARGET].median() if model == "median" or selected_name == "Training-median baseline" else fit_frame[TARGET].mean()
            estimator = ConstantRegressor(float(value))
        else:
            estimator = clone(estimator)
            estimator.fit(_predictors(fit_frame, names), fit_frame[TARGET])
    if isinstance(estimator, ConstantRegressor):
        selected_parameters = {"value": estimator.value}
    else:
        selected_parameters = estimator.steps[-1][1].get_params(deep=False)
        # XGBoost uses NaN as its missing sentinel; spell it out in JSON metadata.
        selected_parameters = {key: ("NaN" if isinstance(value, Real) and math.isnan(value) else value)
                               for key, value in selected_parameters.items()}
    residual = np.abs(cal[TARGET].to_numpy() - estimator.predict(_predictors(cal, names)))
    calibration = {"coverage": coverage, "scaled_quantile": _quantile(residual / _scale(cal), coverage),
                   "constant_quantile": _quantile(residual, coverage), "rows": len(cal),
                   "dates": int(cal.Date.nunique()), "latest_outcome": str(cal.label_end_date.max().date()),
                   "method": "pooled_volatility_scaled_absolute_residuals", "minimum_scale": MINIMUM_SCALE,
                   "coverage_guaranteed": False}
    boundaries = dict(zip(("tuning_start", "calibration_start", "evaluation_start"),
                          (str(x.date()) for x in bounds)))
    partitions = {key: {"rows": len(part), "first_origin": str(part.Date.min().date()),
                        "last_origin": str(part.Date.max().date()),
                        "latest_outcome": str(part.label_end_date.max().date())}
                  for key, part in parts.items()}
    if refit_selected:
        partitions["refit"] = {"rows": len(fit_frame), "first_origin": str(fit_frame.Date.min().date()),
                               "last_origin": str(fit_frame.Date.max().date()),
                               "latest_outcome": str(fit_frame.label_end_date.max().date())}
    metadata = {"format_version": FORMAT_VERSION, "selected_model": selected_name,
                "requested_model": model, "selection_metric": "inner MAE; RMSE tie-breaker",
                "selected_parameters": selected_parameters, "refit_selected": refit_selected,
                "selection_scope": ("XGBoost parameter grid; learned family explicitly requested"
                                    if model == "xgboost" else "requested candidate set"),
                "selection": records, "eligible_tickers": eligible, "partitions": partitions,
                "training_mean": float(fit_frame[TARGET].mean()), "training_median": float(fit_frame[TARGET].median()),
                "training_majority_up": bool(fit_frame[TARGET].gt(0).mean() > 0.5),
                "feature_names": list(names), "horizon_sessions": HORIZON,
                "research_status": "retrospective_experimental_not_prospectively_validated",
                **boundaries}
    return ForecastBundle(estimator, names, metadata, calibration)


def evaluate(bundle: ForecastBundle, frame: pd.DataFrame) -> dict:
    """Evaluate subsequent known outcomes without fitting or recalibrating."""
    valid = frame[TARGET].notna() & frame.Date.ge(pd.Timestamp(bundle.metadata["evaluation_start"]))
    data = frame.loc[valid & frame.ticker.isin(bundle.metadata["eligible_tickers"])].copy()
    if data.empty:
        raise ValueError("No later labeled rows available for evaluation")
    prediction = bundle.predict(data)
    y = data[TARGET].to_numpy(dtype=float)
    if not np.isfinite(y).all():
        raise ValueError("Evaluation targets must be finite")
    p = prediction.predicted_return_10d.to_numpy()
    lower, upper = prediction.lower_return.to_numpy(), prediction.upper_return.to_numpy()
    alpha = 1 - bundle.calibration["coverage"]
    score = upper - lower + 2 / alpha * ((lower - y) * (y < lower) + (y - upper) * (y > upper))
    metrics = {"rows": len(data), "MAE_pp": float(mean_absolute_error(y, p) * 100),
               "RMSE_pp": float(np.sqrt(mean_squared_error(y, p)) * 100),
               "R2": float(r2_score(y, p)), "direction_accuracy_pct": float(np.mean((y > 0) == (p > 0)) * 100),
               # A one-class period cannot measure discrimination of both directions.
               "balanced_accuracy_pct": (float(balanced_accuracy_score(y > 0, p > 0) * 100)
                                         if np.unique(y > 0).size == 2 else None),
               "always_up_accuracy_pct": float(np.mean(y > 0) * 100),
               "training_majority_accuracy_pct": float(np.mean((y > 0) == bundle.metadata["training_majority_up"]) * 100),
               "interval_coverage": float(np.mean((y >= lower) & (y <= upper))),
               "mean_interval_width_pp": float(np.mean(upper - lower) * 100),
               "interval_score_pp": float(np.mean(score) * 100),
               "evaluation_first_origin": str(data.Date.min().date()),
               "evaluation_last_origin": str(data.Date.max().date()),
               "status": "retrospective_diagnostic"}
    metrics["baseline_errors"] = {}
    for name in ("mean", "median"):
        b = np.full(len(y), bundle.metadata[f"training_{name}"])
        metrics["baseline_errors"][name] = {"MAE_pp": float(mean_absolute_error(y, b) * 100),
                                            "RMSE_pp": float(np.sqrt(mean_squared_error(y, b)) * 100)}
    return metrics
