import { api } from "@/lib/api";
import type { DiscoveryResponse, RecommendationSnapshot } from "@/lib/types";

/** Research signals + explanations — the "Discover" feature (backend: app/api/routers/discovery.py). */
export const recommendationsService = {
  /** Personalised research set for the signed-in user + a diversification note. */
  discovery: () => api<DiscoveryResponse>("/api/discovery"),

  /** The full research snapshot for one asset at the user's risk tier. */
  detail: (ticker: string) =>
    api<RecommendationSnapshot>(`/api/discovery/${encodeURIComponent(ticker)}`),
};
