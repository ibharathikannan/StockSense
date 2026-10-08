"""Public precomputed forecast fields, with no artifact paths or provenance secrets."""
from datetime import date, datetime
import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator


class ForecastItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str = Field(pattern=r"^[A-Z0-9][A-Z0-9.\-^=]{0,15}$")
    date: date
    predicted_return_10d: FiniteFloat
    lower_return: FiniteFloat
    upper_return: FiniteFloat
    uncertainty_width_pp: FiniteFloat = Field(ge=0)
    nominal_coverage: FiniteFloat = Field(gt=0, lt=1)
    stale_snapshot: bool
    data_age_calendar_days: int = Field(ge=0)
    calibration_latest_outcome: date

    @model_validator(mode="after")
    def valid_interval(self):
        if not self.lower_return <= self.predicted_return_10d <= self.upper_return:
            raise ValueError("Invalid forecast interval")
        if not math.isclose(self.uncertainty_width_pp,
                            100 * (self.upper_return - self.lower_return), rel_tol=1e-7, abs_tol=1e-7):
            raise ValueError("Invalid uncertainty width")
        if self.calibration_latest_outcome >= self.date:
            raise ValueError("Forecast precedes calibration completion")
        return self


class ForecastSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str = Field(min_length=1, max_length=120)
    as_of: date
    generated_at: datetime
    horizon_sessions: Literal[10] = 10
    nominal_coverage: FiniteFloat = Field(gt=0, lt=1)
    empirical_coverage: FiniteFloat | None = Field(default=None, ge=0, le=1)
    evaluation_mae_pp: FiniteFloat | None = Field(default=None, ge=0)
    direction_accuracy_pct: FiniteFloat | None = Field(default=None, ge=0, le=100)
    always_up_accuracy_pct: FiniteFloat | None = Field(default=None, ge=0, le=100)
    forecasts: list[ForecastItem] = Field(max_length=90)
    selected_tickers: list[str] = Field(min_length=1, max_length=90)
    unavailable_tickers: list[str] = Field(max_length=90)
    status: Literal["experimental_offline_snapshot"] = "experimental_offline_snapshot"
    uncertainty_description: Literal["Interval width in percentage points; not a probability of accuracy"] = "Interval width in percentage points; not a probability of accuracy"
