"use client";

import Link from "next/link";
import { SearchX } from "lucide-react";
import { Alert, Badge, Card, EmptyState, LinkButton, PageHeader, PageLoader } from "@/components/ui";
import { TickerMark } from "@/components/dashboard/shared";
import { StanceBadge, forecastLabel, stanceBlurb } from "@/components/recommendations";
import { errorMessage } from "@/lib/api";
import { useFetch } from "@/lib/hooks";
import { recommendationsService } from "@/services/recommendations";
import type { RecommendationSnapshot } from "@/lib/types";

function CandidateCard({ snap }: { snap: RecommendationSnapshot }) {
  const reason = snap.signal.decision_trace[0] ?? stanceBlurb(snap.signal.news_aware_stance);
  return (
    <Link href={`/discover/${snap.ticker}`} className="group block rounded-xl focus-visible:outline-offset-4">
      <Card className="flex h-full flex-col p-5 transition-all duration-150 group-hover:-translate-y-0.5 group-hover:border-brand-200 group-hover:shadow-md motion-reduce:transition-none motion-reduce:group-hover:translate-y-0">
        <div className="flex items-start gap-3">
          <TickerMark ticker={snap.ticker} />
          <div className="min-w-0 flex-1">
            <p className="font-semibold tracking-tight">{snap.ticker}</p>
            <p className="truncate text-sm text-muted">{snap.name}</p>
          </div>
          <StanceBadge stance={snap.signal.news_aware_stance} provisional={snap.signal.provisional} />
        </div>
        <p className="mt-4 line-clamp-2 flex-1 text-sm leading-relaxed text-muted">{reason}</p>
        <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-line pt-4">
          <Badge tone="neutral">{snap.sector}</Badge>
          <span className="text-xs text-muted tabular-nums">{forecastLabel(snap.forecast)}</span>
        </div>
      </Card>
    </Link>
  );
}

export default function DiscoverPage() {
  const { data, error, loading } = useFetch(["discovery"], () => recommendationsService.discovery());

  if (loading && !data) return <PageLoader />;

  return (
    <>
      <PageHeader
        title="Discover"
        description="A small, explainable research set based on your interests and risk profile."
      />

      {error && <div className="mb-6"><Alert tone="error">{errorMessage(error)}</Alert></div>}

      {data?.diversification.warning && (
        <div className="mb-6">
          <Alert tone="info">{data.diversification.warning}</Alert>
        </div>
      )}

      {data && data.candidates.length === 0 ? (
        <Card>
          <EmptyState
            icon={SearchX}
            title="No matches for your interests yet"
            action={<LinkButton href="/profile" variant="secondary">Update your profile</LinkButton>}
          >
            We couldn&apos;t find research candidates for your current interests. Try broadening them on your profile.
          </EmptyState>
        </Card>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {data?.candidates.map((snap) => <CandidateCard key={snap.ticker} snap={snap} />)}
        </div>
      )}

      <p className="mt-8 text-xs text-muted">
        Signals guide research priority (Explore / Monitor / Caution), not trading decisions.
        A <span className="font-semibold">*</span> marks an experimental change of stance driven by news or SEC fundamentals.
      </p>
    </>
  );
}
