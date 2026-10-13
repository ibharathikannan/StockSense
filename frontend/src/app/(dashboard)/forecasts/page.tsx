"use client";

import { ForecastPanel } from "@/components/dashboard/ForecastPanel";
import { Alert, Button, LinkButton, PageHeader } from "@/components/ui";
import { useFetch } from "@/lib/hooks";
import { useProfile } from "@/lib/profile";
import { dashboardService } from "@/services/dashboard";

export default function ForecastsPage() {
  const { profile } = useProfile();
  const dashboard = useFetch(["forecast-recommendations", profile?.updated_at], () => dashboardService.get());

  return (
    <>
      <PageHeader
        title="Stock forecasts"
        description="10-session return estimates, uncertainty and research assessments for your recommended stocks and ETFs."
      />
      {dashboard.error ? (
        <div className="space-y-3">
          <Alert tone={dashboard.error.status === 409 ? "info" : "error"}>
            {dashboard.error.status === 409
              ? "Complete your profile to see forecasts for your recommendations."
              : `Couldn’t load your recommendations: ${dashboard.error.message}`}
          </Alert>
          {dashboard.error.status === 409 ? (
            <LinkButton href="/profile">Complete profile</LinkButton>
          ) : (
            <Button variant="secondary" onClick={dashboard.reload}>Retry recommendations</Button>
          )}
        </div>
      ) : dashboard.loading || !dashboard.data ? (
        <p role="status" className="text-sm text-muted">Loading your recommended stocks…</p>
      ) : (
        <ForecastPanel data={dashboard.data} />
      )}
    </>
  );
}
