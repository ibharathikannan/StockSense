import { api } from "@/lib/api";
import type { DiscoveryResponse, RecommendationSnapshot } from "@/lib/types";

/** Research signals + explanations (backend: app/api/routers/recommendations.py). */
export const recommendationsService = {
  /** Personalised research set for the signed-in user + a diversification note. */
  discovery: () => api<DiscoveryResponse>("/api/recommendations"),

  /** The full research snapshot for one asset at the user's risk tier. */
  detail: (ticker: string) =>
    api<RecommendationSnapshot>(`/api/recommendations/${encodeURIComponent(ticker)}`),
};
