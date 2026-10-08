"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Badge, Button, Card, Field, Input, PageHeader } from "@/components/ui";
import { errorMessage } from "@/lib/api";
import type { ForecastSnapshot } from "@/lib/forecast-types";
import { forecastsService } from "@/services/forecasts";

const percent = (value: number) => `${(value * 100).toFixed(2)}%`;
const metric = (value: number | null, suffix: string) => value === null ? "Unavailable" : `${value.toFixed(2)}${suffix}`;

export default function ForecastsPage() {
  return <Suspense fallback={<p role="status">Loading selected stocks…</p>}><SelectedForecasts /></Suspense>;
}

function SelectedForecasts() {
  const params = useSearchParams();
  const selectedTickers = [...new Set((params.get("tickers") ?? "").split(",").map((value) => value.trim().toUpperCase()).filter(Boolean))];
  const invalidSelection = selectedTickers.length > 90 || selectedTickers.some((value) => !/^[A-Z0-9][A-Z0-9.\-^=]{0,15}$/.test(value));
  const selection = invalidSelection ? "" : selectedTickers.join(",");
  const [request, setRequest] = useState(0);
  const [result, setResult] = useState<{ request: number; selection: string; data?: ForecastSnapshot; error?: string } | null>(null);
  const [query, setQuery] = useState("");

  useEffect(() => {
    if (!selection) return;
    const controller = new AbortController();
    forecastsService.snapshot(selection.split(","), controller.signal).then(
      (data) => { if (!controller.signal.aborted) setResult({ request, selection, data }); },
      (error) => { if (!controller.signal.aborted) setResult({ request, selection, error: errorMessage(error) }); },
    );
    return () => controller.abort();
  }, [request, selection]);

  const loading = Boolean(selection) && (result?.request !== request || result?.selection !== selection);
  const snapshot = result?.data;
  const rows = snapshot?.forecasts.filter((item) =>
    item.ticker.toLowerCase().includes(query.trim().toLowerCase()),
  ) ?? [];
  const stale = snapshot?.forecasts.some((item) => item.stale_snapshot);

  return (
    <>
      <PageHeader title="Selected stock forecasts" description="Estimated returns over the next 10 trading sessions, with a range of possible outcomes." />
      {!selection && <Card className="p-5"><p className="text-sm" role={invalidSelection ? "alert" : undefined}>{invalidSelection ? "The selected stock list is invalid. Return to your research shortlist and select up to 90 valid tickers." : "No stocks selected yet. Open forecasts from your research shortlist."}</p></Card>}
      {loading && <p role="status" className="text-sm text-muted">Loading forecasts…</p>}
      {selection && !loading && result?.error && (
        <Card className="p-5">
          <p role="alert" className="text-sm">{result.error}</p>
          <Button variant="secondary" className="mt-3" onClick={() => setRequest((value) => value + 1)}>Retry</Button>
        </Card>
      )}
      {selection && !loading && snapshot && (
        <>
          <Card className="p-5">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="font-semibold">{snapshot.model}</h2>
              <Badge tone={stale ? "amber" : "neutral"}>{stale ? "Historical snapshot · stale" : "Saved snapshot"}</Badge>
            </div>
            <p className="mt-2 text-sm text-muted">Prices through {snapshot.as_of}. Generated {new Date(snapshot.generated_at).toLocaleString()}. Forecast horizon: {snapshot.horizon_sessions} trading sessions after each origin date.</p>
            {snapshot.model.toLowerCase().includes("baseline") && <p className="mt-2 text-sm text-muted">This snapshot uses a constant historical-return baseline. Predicted returns are the same across stocks; uncertainty varies with each stock&apos;s historical volatility.</p>}
            {stale && <p className="mt-2 text-sm text-muted">These estimates use older prices and do not describe a forecast starting today.</p>}
            <p className="mt-3 text-sm">The nominal {percent(snapshot.nominal_coverage)} interval is a target for coverage, not prediction accuracy or a guarantee. Wider intervals mean more uncertainty.</p>
            <dl className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <div><dt className="text-xs text-muted">Measured interval coverage</dt><dd className="mt-1 font-medium">{snapshot.empirical_coverage === null ? "Unavailable" : percent(snapshot.empirical_coverage)}</dd></div>
              <div><dt className="text-xs text-muted">Average absolute return error</dt><dd className="mt-1 font-medium">{metric(snapshot.evaluation_mae_pp, " pp")}</dd></div>
              <div><dt className="text-xs text-muted">Direction accuracy</dt><dd className="mt-1 font-medium">{metric(snapshot.direction_accuracy_pct, "%")}</dd></div>
              <div><dt className="text-xs text-muted">Always-up benchmark accuracy</dt><dd className="mt-1 font-medium">{metric(snapshot.always_up_accuracy_pct, "%")}</dd></div>
            </dl>
            <p className="mt-3 text-xs text-muted">Metrics describe the full historical evaluation dataset, not just your selected stocks. Estimates are research information, not personalized financial advice.</p>
          </Card>
          {snapshot.unavailable_tickers.length > 0 && <p role="status" className="mt-4 text-sm text-muted">Forecasts unavailable for: {snapshot.unavailable_tickers.join(", ")}.</p>}
          <div className="my-5 max-w-md">
            <Field label="Search ticker" htmlFor="forecast-query"><Input id="forecast-query" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="e.g. AAPL" type="search" /></Field>
          </div>
          <p role="status" className="mb-3 text-sm text-muted">{rows.length} of {snapshot.forecasts.length} forecasts</p>
          {!rows.length ? <Card className="p-5"><p className="text-sm">{snapshot.forecasts.length ? "No tickers match these filters." : "No forecasts are available in this snapshot."}</p></Card> : (
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {rows.map((item) => (
                <Card key={`${item.ticker}:${item.date}`} className="p-5">
                  <div className="flex items-center justify-between gap-2"><h2 className="font-semibold">{item.ticker}</h2>{item.stale_snapshot && <Badge tone="amber">Stale</Badge>}</div>
                  <p className="mt-1 text-xs text-muted">Forecast origin: {item.date}</p>
                  <dl className="mt-4 space-y-3">
                    <div><dt className="text-xs text-muted">Predicted 10-session return</dt><dd className="text-2xl font-semibold tabular-nums">{percent(item.predicted_return_10d)}</dd></div>
                    <div><dt className="text-xs text-muted">Nominal {percent(item.nominal_coverage)} prediction interval</dt><dd className="font-medium tabular-nums">{percent(item.lower_return)} to {percent(item.upper_return)}</dd></div>
                    <div><dt className="text-xs text-muted">Uncertainty width</dt><dd className="tabular-nums">{item.uncertainty_width_pp.toFixed(2)} percentage points</dd></div>
                  </dl>
                  <p className="mt-4 text-xs text-muted">Price data age: {item.data_age_calendar_days} calendar days. Calibration outcomes through {item.calibration_latest_outcome}.</p>
                </Card>
              ))}
            </div>
          )}
        </>
      )}
    </>
  );
}
