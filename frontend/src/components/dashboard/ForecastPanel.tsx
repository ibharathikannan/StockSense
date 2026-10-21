"use client";

import { useEffect, useState } from "react";
import { Alert, Badge, Button, Card } from "@/components/ui";
import { errorMessage } from "@/lib/api";
import type { ForecastSnapshot } from "@/lib/forecast-types";
import { formatDate, formatDateTime } from "@/lib/format";
import type { Dashboard } from "@/lib/types";
import { forecastsService } from "@/services/forecasts";

const percent = (value: number) => `${(value * 100).toFixed(2)}%`;

/** Forecasting is independent of the content-based suggestion ranking. */
export function ForecastPanel({ data }: { data: Dashboard }) {
  const selection = [...new Set(data.suggestions.map((item) => item.ticker))].join(",");
  const [attempt, setAttempt] = useState(0);
  const key = `${attempt}:${selection}:${data.risk_level.key}:${data.prices_as_of ?? ""}`;
  const [result, setResult] = useState<{ key: string; snapshot?: ForecastSnapshot; error?: string } | null>(null);

  useEffect(() => {
    if (!selection) return;
    const controller = new AbortController();
    forecastsService.recommended(controller.signal).then(
      (snapshot) => { if (!controller.signal.aborted) setResult({ key, snapshot }); },
      (error) => { if (!controller.signal.aborted) setResult({ key, error: errorMessage(error) }); },
    );
    return () => controller.abort();
  }, [key, selection]);

  const settled = result?.key === key ? result : null;
  const snapshot = settled?.snapshot;
  const selected = new Set(data.suggestions.map((item) => item.ticker));
  const forecasts = snapshot?.forecasts.filter((item) => selected.has(item.ticker)) ?? [];
  const missing = data.suggestions.filter((item) => !forecasts.some((forecast) => forecast.ticker === item.ticker));
  const inference = snapshot?.source_mode === "saved_model_inference";

  return (
    <Card>
      <div className="border-b border-line p-5">
        <h2 className="text-sm font-semibold">10-session forecasts for your suggestions</h2>
        <p className="mt-1 text-sm text-muted">Estimated returns and uncertainty for the stocks and ETFs suggested above. Forecasts do not determine the suggestion ranking.</p>
      </div>
      {!selection ? <p className="p-5 text-sm text-muted">No suggestions to forecast yet.</p> : !settled ? (
        <p role="status" className="p-5 text-sm text-muted">Loading forecasts for suggested assets…</p>
      ) : settled.error ? (
        <div className="space-y-3 p-5"><Alert>{settled.error}</Alert><Button variant="secondary" onClick={() => setAttempt((value) => value + 1)}>Retry forecasts</Button></div>
      ) : snapshot ? (
        <div className="space-y-5 p-5">
          <div>
            <div className="flex flex-wrap items-center gap-2"><Badge tone="amber">Experimental</Badge><Badge>{inference ? "Saved-model inference" : "Saved results"}</Badge></div>
            <p className="mt-2 text-xs text-muted">Data through {formatDate(snapshot.as_of)}{snapshot.model_as_of ? ` · Model as of ${formatDate(snapshot.model_as_of)}` : ""} · Generated {formatDateTime(snapshot.generated_at)}</p>
            <p className="mt-2 text-sm text-muted">Nominal interval coverage: {percent(snapshot.nominal_coverage)}. Measured historical coverage: {snapshot.empirical_coverage === null ? "unavailable" : percent(snapshot.empirical_coverage)}. Coverage is not forecast accuracy or a guarantee; wider intervals indicate more uncertainty.</p>
          </div>
          {forecasts.some((item) => item.stale_snapshot) && <Alert tone="info">Some estimates use older prices. Their forecast horizons begin on the displayed origin dates, not today.</Alert>}
          {missing.length > 0 && <p role="status" className="text-sm text-muted">Forecasts unavailable for {missing.map((item) => item.ticker).join(", ")}. These assets may be unsupported or lack sufficient price history.</p>}
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {forecasts.map((item) => (
              <div key={`${item.ticker}:${item.date}`} className="rounded-lg border border-line p-4">
                <h3 className="text-sm font-semibold">{item.ticker}</h3>
                <p className="mt-1 text-xs text-muted">Origin {formatDate(item.date)} · Next {snapshot.horizon_sessions} trading sessions</p>
                <dl className="mt-3 space-y-2 text-sm">
                  <div><dt className="text-xs text-muted">Predicted return</dt><dd className="text-xl font-semibold tabular-nums">{percent(item.predicted_return_10d)}</dd></div>
                  <div><dt className="text-xs text-muted">Nominal {percent(item.nominal_coverage)} interval</dt><dd className="tabular-nums">{percent(item.lower_return)} to {percent(item.upper_return)}</dd></div>
                  <div><dt className="text-xs text-muted">Uncertainty width</dt><dd className="tabular-nums">{item.uncertainty_width_pp.toFixed(2)} percentage points</dd></div>
                </dl>
                <div className="mt-4 border-t border-line pt-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="text-xs font-medium">Research stance</p>
                    {item.stance ? <Badge tone={item.stance === "CAUTION" ? "amber" : item.stance === "EXPLORE" ? "brand" : "neutral"}>{item.stance}</Badge> : <Badge>Unavailable</Badge>}
                    {item.assessment_status === "historical" && <Badge tone="amber">Historical assessment</Badge>}
                  </div>
                  {item.assessment_status === "historical" && <p className="mt-2 text-xs text-muted">This assessment uses historical forecast or risk inputs and does not describe conditions today.</p>}
                  {item.assessment_status === "unavailable" && <p className="mt-2 text-xs text-muted">A research stance could not be assessed because required risk inputs are unavailable.</p>}
                  {(!item.assessment_status || item.assessment_status === "not_evaluated") && <p className="mt-2 text-xs text-muted">Research stance has not been evaluated for this forecast.</p>}
                  {item.rule_inputs && <p className="mt-2 text-xs text-muted">Risk profile: {item.rule_inputs.user_risk_profile ?? "unavailable"}. Annual volatility: {item.rule_inputs.volatility === null ? "unavailable" : percent(item.rule_inputs.volatility)}{item.rule_inputs.volatility_as_of ? ` as of ${formatDate(item.rule_inputs.volatility_as_of)}` : ""}.{item.rule_inputs.sentiment_score !== null && " Sentiment was included in the assessment."}</p>}
                  {!!item.decision_trace?.length && <details className="mt-2 text-xs"><summary className="cursor-pointer rounded text-muted focus-visible:outline-2 focus-visible:outline-brand-500">Why this stance?</summary><ul className="mt-2 list-disc space-y-1 pl-4 text-muted">{item.decision_trace.map((reason, index) => <li key={`${index}:${reason}`}>{reason}</li>)}</ul></details>}
                </div>
                <p className="mt-3 text-xs text-muted">Data age: {item.data_age_calendar_days} calendar days. Calibration outcomes through {formatDate(item.calibration_latest_outcome)}.</p>
              </div>
            ))}
          </div>
          <p className="text-xs text-muted">Experimental research estimates, not personalized financial advice.</p>
        </div>
      ) : null}
    </Card>
  );
}
