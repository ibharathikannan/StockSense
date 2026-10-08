import { api } from "@/lib/api";
import type { ForecastSnapshot } from "@/lib/forecast-types";

export const forecastsService = {
  snapshot: (tickers: string[], signal?: AbortSignal) =>
    api<ForecastSnapshot>(`/api/forecasts?tickers=${encodeURIComponent(tickers.join(","))}`, { signal, silent: true }),
};
