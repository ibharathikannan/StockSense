"""Validate offline result contracts before authenticated routes expose them."""
from datetime import datetime, timezone
import math
import re
from typing import Callable

from app.repositories.forecasts import ForecastReadError, ForecastRepository
from app.schemas.forecast import ForecastItem, ForecastSnapshot
from app.services.errors import BadRequest, ServiceError


class ForecastUnavailable(ServiceError):
    status_code = 503

    def __init__(self):
        super().__init__("Forecast results are unavailable. Ask an administrator to configure a valid forecast model/data source or saved snapshot.")


class ForecastService:
    def __init__(self, repository: ForecastRepository, *, now: Callable[[], datetime] | None = None):
        self._repository = repository
        self._now = now or (lambda: datetime.now(timezone.utc))

    def get_snapshot(self, tickers: list[str]) -> ForecastSnapshot:
        if (not isinstance(tickers, list) or not 1 <= len(tickers) <= 90
            or any(not isinstance(ticker, str) or not re.fullmatch(r"[A-Z0-9][A-Z0-9.\-^=]{0,15}", ticker)
                   for ticker in tickers) or len(set(tickers)) != len(tickers)):
            raise BadRequest("Provide 1 to 90 distinct valid selected tickers")
        try:
            rows, report = self._repository.read()
            metadata = report.get("metadata", report.get("model_metadata"))
            calibration = report["calibration"]
            model = metadata["selected_model"]
            coverage = float(calibration["coverage"])
            current = self._now().astimezone(timezone.utc)
            today = current.date()
            forecasts = []
            generated = set()
            for row in rows:
                if row["model"] != model or int(row["forecast_horizon_sessions"]) != 10:
                    raise ValueError("Inconsistent forecast identity")
                if not math.isclose(float(row["nominal_coverage"]), coverage, rel_tol=1e-10):
                    raise ValueError("Inconsistent forecast coverage")
                item = ForecastItem.model_validate({
                    "ticker": row["ticker"], "date": row["Date"],
                    **{name: row[name] for name in (
                        "predicted_return_10d", "lower_return", "upper_return", "uncertainty_width_pp",
                        "nominal_coverage", "calibration_latest_outcome")},
                    "data_age_calendar_days": 0, "stale_snapshot": False,
                })
                age = (today - item.date).days
                if age < 0 or item.calibration_latest_outcome.isoformat() != calibration["latest_outcome"]:
                    raise ValueError("Inconsistent forecast dates")
                item.data_age_calendar_days = age
                item.stale_snapshot = age > 7
                forecasts.append(item)
                stamp = datetime.fromisoformat(row["generated_at_utc"].replace("Z", "+00:00"))
                if stamp.tzinfo is None or stamp > current or stamp.date() < item.date:
                    raise ValueError("Invalid generation timestamp")
                generated.add(stamp)
            if len(generated) != 1 or len({item.ticker for item in forecasts}) != len(forecasts):
                raise ValueError("Duplicate ticker or mixed generation timestamps")
            # New exports bind the report to this exact prediction batch. Earlier
            # training exports have the timestamp in metadata instead.
            report_generated = report.get("generated_at_utc")
            if report_generated is None and "metadata" in report:
                report_generated = metadata.get("created_at_utc")
            if report_generated is not None:
                report_stamp = datetime.fromisoformat(report_generated.replace("Z", "+00:00"))
                if report_stamp.tzinfo is None or report_stamp != next(iter(generated)):
                    raise ValueError("CSV and report belong to different runs")
            # Report metadata may describe training's as-of; prediction reports
            # provide their own cutoff. Neither may precede any forecast origin.
            as_of = report.get("as_of", metadata.get("as_of"))
            if as_of and any(item.date.isoformat() > as_of for item in forecasts):
                raise ValueError("Forecast origin exceeds report cutoff")
            evaluation = report.get("evaluation", {})
            available = {item.ticker: item for item in forecasts}
            return ForecastSnapshot(
                model=model, as_of=max(item.date for item in forecasts), generated_at=next(iter(generated)),
                nominal_coverage=coverage, forecasts=[available[ticker] for ticker in tickers if ticker in available],
                selected_tickers=tickers, unavailable_tickers=[ticker for ticker in tickers if ticker not in available],
                empirical_coverage=evaluation.get("interval_coverage"),
                evaluation_mae_pp=evaluation.get("MAE_pp"),
                direction_accuracy_pct=evaluation.get("direction_accuracy_pct"),
                always_up_accuracy_pct=evaluation.get("always_up_accuracy_pct"),
            )
        except (ForecastReadError, ValueError, TypeError, KeyError, AttributeError, OverflowError):
            raise ForecastUnavailable() from None
