export interface ForecastItem {
  ticker: string;
  date: string;
  predicted_return_10d: number;
  lower_return: number;
  upper_return: number;
  uncertainty_width_pp: number;
  nominal_coverage: number;
  stale_snapshot: boolean;
  data_age_calendar_days: number;
  calibration_latest_outcome: string;
}

export interface ForecastSnapshot {
  model: string;
  as_of: string;
  generated_at: string;
  horizon_sessions: number;
  nominal_coverage: number;
  empirical_coverage: number | null;
  evaluation_mae_pp: number | null;
  direction_accuracy_pct: number | null;
  always_up_accuracy_pct: number | null;
  selected_tickers: string[];
  unavailable_tickers: string[];
  forecasts: ForecastItem[];
}
