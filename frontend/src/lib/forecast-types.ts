export interface ForecastRuleInputs {
  forecast_return: number;
  prediction_interval_width: number;
  volatility: number | null;
  volatility_as_of: string | null;
  sentiment_score: number | null;
  user_risk_profile: string | null;
}

export interface ForecastItem {
  stance?: "EXPLORE" | "MONITOR" | "CAUTION" | null;
  decision_trace?: string[];
  assessment_status?: "not_evaluated" | "evaluated" | "historical" | "unavailable";
  rule_inputs?: ForecastRuleInputs | null;
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
  status?: "experimental_offline_snapshot" | "experimental_saved_model_inference";
  source_mode?: "saved_model_inference" | "saved_results";
  model_as_of?: string | null;
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
