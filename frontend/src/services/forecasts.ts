import { api } from "@/lib/api";
import type { ForecastSnapshot } from "@/lib/forecast-types";

export const forecastsService = {
  recommended: (signal?: AbortSignal) =>
    api<ForecastSnapshot>("/api/forecasts/recommended", { signal, silent: true }),
  snapshot: (tickers: string[], signal?: AbortSignal) =>
    api<ForecastSnapshot>(`/api/forecasts?tickers=${encodeURIComponent(tickers.join(","))}`, { signal, silent: true }),
};
