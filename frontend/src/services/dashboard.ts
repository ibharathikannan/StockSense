import { api } from "@/lib/api";
import type { Dashboard } from "@/lib/types";

/** The signed-in investor's dashboard (backend: app/api/routers/dashboard.py). */
export const dashboardService = {
  /** Profile summary, watchlist and suggestions. Fails with 409 until the profile is complete. */
  get: () => api<Dashboard>("/api/dashboard"),
};
