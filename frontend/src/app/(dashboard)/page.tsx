"use client";

import { ArrowRight, Compass, SlidersHorizontal } from "lucide-react";
import { ForecastPanel } from "@/components/dashboard/ForecastPanel";
import { DashboardTiles } from "@/components/dashboard/DashboardTiles";
import { RiskCheckChart } from "@/components/dashboard/RiskCheckChart";
import { SectorSpreadChart } from "@/components/dashboard/SectorSpreadChart";
import { SuggestionList } from "@/components/dashboard/SuggestionList";
import { WatchlistCard } from "@/components/dashboard/WatchlistCard";
import { Alert, Badge, Card, LinkButton, Skeleton } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { formatDate } from "@/lib/format";
import { useFetch } from "@/lib/hooks";
import { useProfile } from "@/lib/profile";
import type { Dashboard } from "@/lib/types";
import { dashboardService } from "@/services/dashboard";

/** More interest chips than this collapse into a "+N more" chip. */
const MAX_INTEREST_CHIPS = 4;

const ASSET_TYPE_LABELS: Record<string, string> = {
  both: "Stocks & ETFs",
  stock: "Stocks only",
  etf: "ETFs only",
};

export default function DashboardPage() {
  const { user } = useAuth();
  const { profile } = useProfile();

  // Reload after profile changes so recommendations reflect the saved profile.
  const dashboard = useFetch(
    ["dashboard", profile?.updated_at],
    () => dashboardService.get(),
  );

  const firstName = user?.full_name.split(" ")[0] || "there";

  return (
    <>
      <Header firstName={firstName} data={dashboard.data} />

      <Card className="mb-8 flex flex-wrap items-center justify-between gap-4 border-brand-100 bg-gradient-to-r from-brand-50 via-white to-white p-5 sm:p-6">
        <div className="flex items-start gap-4">
          <span className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-brand-600 text-white shadow-sm" aria-hidden>
            <Compass className="size-5" />
          </span>
          <div>
            <h2 className="font-semibold">Your research set is ready</h2>
            <p className="mt-1 max-w-xl text-sm text-muted">
              Explore personalised, explainable signals — Explore / Monitor / Caution — with the reasons behind each.
            </p>
          </div>
        </div>
        <LinkButton href="/discover">
          Go to Discover
          <ArrowRight className="size-4" aria-hidden />
        </LinkButton>
      </Card>

      {dashboard.error ? (
        dashboard.error.status === 409 ? (
          <Alert tone="info">
            Complete your profile to see your dashboard.
          </Alert>
        ) : (
          <Alert>
            Couldn&apos;t load your dashboard: {dashboard.error.message}
          </Alert>
        )
      ) : !dashboard.data ? (
        <DashboardSkeleton />
      ) : (
        <div className="space-y-6">
          <DashboardTiles data={dashboard.data} />

          <div className="grid gap-6 lg:grid-cols-3">
            <RiskCheckChart
              data={dashboard.data}
              className="lg:col-span-2"
            />
            <SectorSpreadChart data={dashboard.data} />
          </div>

          <div className="grid gap-6 lg:grid-cols-3">
            <SuggestionList
              data={dashboard.data}
              className="lg:col-span-2"
            />
            <WatchlistCard data={dashboard.data} />
          </div>

          <ForecastPanel data={dashboard.data} />
        </div>
      )}
    </>
  );
}

function Header({
  firstName,
  data,
}: {
  firstName: string;
  data?: Dashboard;
}) {
  return (
    <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h1 className="text-[1.65rem] leading-tight font-semibold tracking-tight">
          Welcome back, {firstName}
        </h1>

        {data ? (
          <>
            <p className="mt-1.5 text-sm text-muted">
              {data.risk_level.label} risk level · {ASSET_TYPE_LABELS[data.asset_types] ?? data.asset_types}
              {data.prices_as_of && <> · Prices up to {formatDate(data.prices_as_of)}</>}
            </p>

            <div className="mt-3 flex flex-wrap items-center gap-1.5">
              <span className="mr-1 text-xs font-medium text-muted">Interests</span>
              {data.interests.slice(0, MAX_INTEREST_CHIPS).map((interest) => (
                <Badge key={interest.key} tone="brand">
                  {interest.label}
                </Badge>
              ))}
              {data.interests.length > MAX_INTEREST_CHIPS && (
                <span title={data.interests.slice(MAX_INTEREST_CHIPS).map((i) => i.label).join(", ")}>
                  <Badge>+{data.interests.length - MAX_INTEREST_CHIPS} more</Badge>
                </span>
              )}
            </div>
          </>
        ) : (
          <p className="mt-1.5 text-sm text-muted">
            Your research overview.
          </p>
        )}
      </div>

      <LinkButton href="/profile" variant="secondary">
        <SlidersHorizontal className="size-4" aria-hidden />
        Edit profile
      </LinkButton>
    </div>
  );
}

function DashboardSkeleton() {
  return (
    <div
      role="status"
      aria-label="Loading your dashboard"
      className="space-y-6"
    >
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {Array.from({ length: 4 }, (_, index) => (
          <Card key={index} className="space-y-3 p-5">
            <Skeleton className="h-4 w-24" />
            <Skeleton className="h-7 w-20" />
            <Skeleton className="h-3 w-40" />
          </Card>
        ))}
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <Skeleton className="h-72 rounded-xl lg:col-span-2" />
        <Skeleton className="h-72 rounded-xl" />
      </div>
    </div>
  );
}
