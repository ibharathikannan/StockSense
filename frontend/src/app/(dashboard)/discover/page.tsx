"use client";

import Link from "next/link";
import { Alert, Badge, Card, PageHeader, PageLoader } from "@/components/ui";
import { StanceBadge, forecastLabel, stanceBlurb } from "@/components/recommendations";
import { errorMessage } from "@/lib/api";
import { useFetch } from "@/lib/hooks";
import { recommendationsService } from "@/services/recommendations";
import type { RecommendationSnapshot } from "@/lib/types";

function CandidateCard({ snap }: { snap: RecommendationSnapshot }) {
  const reason = snap.signal.decision_trace[0] ?? stanceBlurb(snap.signal.news_aware_stance);
  return (
    <Link href={`/discover/${snap.ticker}`} className="block">
      <Card className="h-full p-5 transition-shadow hover:shadow-md">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="font-semibold">{snap.ticker}</p>
            <p className="truncate text-sm text-muted">{snap.name}</p>
          </div>
          <StanceBadge stance={snap.signal.news_aware_stance} provisional={snap.signal.provisional} />
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          <Badge tone="neutral">{snap.sector}</Badge>
          <Badge tone="neutral">{forecastLabel(snap.forecast)}</Badge>
        </div>
        <p className="mt-3 line-clamp-2 text-sm text-muted">{reason}</p>
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
        <Card className="p-6 text-sm text-muted">
          No matches for your current interests yet. Try broadening them on your{" "}
          <Link href="/profile" className="text-brand-600 underline">profile</Link>.
        </Card>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {data?.candidates.map((snap) => <CandidateCard key={snap.ticker} snap={snap} />)}
        </div>
      )}

      <p className="mt-8 text-xs text-muted">
        Signals guide research priority (Explore / Monitor / Caution), not trading decisions.
        A <span className="font-semibold">*</span> marks an experimental, news-driven change of stance.
      </p>
    </>
  );
}
