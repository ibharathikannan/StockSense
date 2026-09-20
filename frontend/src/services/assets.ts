import { api } from "@/lib/api";
import type { AssetSummary } from "@/lib/types";

/** The recommendable stocks and ETFs (backend: app/api/routers/assets.py). */
export const assetsService = {
  /** Type-ahead by ticker prefix or name. Silent: no full-screen overlay while typing. */
  search: (query: string) => api<AssetSummary[]>(`/api/assets/search?q=${encodeURIComponent(query)}&limit=8`, { silent: true }),
};
