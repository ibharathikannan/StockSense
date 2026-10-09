"use client";

import { SlidersHorizontal } from "lucide-react";
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

const ASSET_TYPE_LABELS: Record<string, string> = { both: "Stocks & ETFs", stock: "Stocks only", etf: "ETFs only" };

export default function DashboardPage() {
  const { user } = useAuth();
  const { profile } = useProfile();
  // Keyed on the profile's last save, so edits made on the Profile page show up here.
  const dashboard = useFetch(["dashboard", profile?.updated_at], () => dashboardService.get());
  const firstName = user?.full_name.split(" ")[0] || "there";

  return (
    <>
      <Header firstName={firstName} data={dashboard.data} />
      {dashboard.error ? (
        dashboard.error.status === 409 ? (
          <Alert tone="info">Complete your profile to see your dashboard.</Alert>
        ) : (
          <Alert>Couldn&apos;t load your dashboard: {dashboard.error.message}</Alert>
        )
      ) : !dashboard.data ? (
        <DashboardSkeleton />
      ) : (
        <div className="space-y-6">
          <DashboardTiles data={dashboard.data} />
          <div className="grid gap-6 lg:grid-cols-3">
            <RiskCheckChart data={dashboard.data} className="lg:col-span-2" />
            <SectorSpreadChart data={dashboard.data} />
          </div>
          <div className="grid gap-6 lg:grid-cols-3">
            <SuggestionList data={dashboard.data} className="lg:col-span-2" />
            <WatchlistCard data={dashboard.data} />
          </div>
        </div>
      )}
    </>
  );
}

function Header({ firstName, data }: { firstName: string; data?: Dashboard }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Welcome back, {firstName}</h1>
        {data ? (
          <div className="mt-2 flex flex-wrap items-center gap-2 text-sm text-muted">
            <span>Your interests</span>
            {data.interests.map((i) => (
              <Badge key={i.key} tone="brand">
                {i.label}
              </Badge>
            ))}
            <span aria-hidden>·</span>
            <span>{ASSET_TYPE_LABELS[data.asset_types] ?? data.asset_types}</span>
            {data.prices_as_of && (
              <>
                <span aria-hidden>·</span>
                <span>Prices up to {formatDate(data.prices_as_of)}</span>
              </>
            )}
          </div>
        ) : (
          <p className="mt-1 text-sm text-muted">Your research overview.</p>
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
    <div role="status" aria-label="Loading your dashboard" className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {Array.from({ length: 4 }, (_, i) => (
          <Card key={i} className="space-y-3 p-5">
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
