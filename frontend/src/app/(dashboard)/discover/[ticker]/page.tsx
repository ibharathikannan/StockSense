"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft, ExternalLink } from "lucide-react";
import { Alert, Badge, Card, PageHeader, PageLoader } from "@/components/ui";
import { StanceBadge, forecastLabel, sourceLabel } from "@/components/recommendations";
import { errorMessage } from "@/lib/api";
import { useFetch } from "@/lib/hooks";
import { recommendationsService } from "@/services/recommendations";

function BackLink() {
  return (
    <Link href="/discover" className="mb-4 inline-flex items-center gap-1 text-sm text-muted hover:text-ink">
      <ArrowLeft className="size-4" /> Back to Discover
    </Link>
  );
}

export default function CompanyDetailPage() {
  const params = useParams<{ ticker: string }>();
  const ticker = String(params.ticker || "").toUpperCase();
  const { data: snap, error, loading } = useFetch(ticker ? ["detail", ticker] : null, () =>
    recommendationsService.detail(ticker),
  );

  if (loading && !snap) return <PageLoader />;
  if (error) {
    return (
      <>
        <BackLink />
        <Alert tone="error">{errorMessage(error)}</Alert>
      </>
    );
  }
  if (!snap) return null;

  return (
    <>
      <BackLink />
      <PageHeader
        title={`${snap.name} (${snap.ticker})`}
        description={`${snap.sector} · ${snap.asset_type}`}
        actions={<StanceBadge stance={snap.signal.news_aware_stance} provisional={snap.signal.provisional} />}
      />

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="p-5">
          <h2 className="text-sm font-semibold text-muted">10-day forecast</h2>
          <p className="mt-2 text-2xl font-semibold tabular-nums">{forecastLabel(snap.forecast)}</p>
          <p className="mt-1 text-xs text-muted">{snap.forecast.basis}</p>
        </Card>

        <Card className="p-5 lg:col-span-2">
          <h2 className="text-sm font-semibold text-muted">Why this signal</h2>
          <ul className="mt-3 space-y-2 text-sm">
            {snap.signal.decision_trace.map((line, i) => (
              <li key={i} className="flex gap-2">
                <span className="mt-0.5 text-brand-500">•</span>
                <span>{line}</span>
              </li>
            ))}
          </ul>
        </Card>
      </div>

      <Card className="mt-6 p-5">
        <h2 className="text-sm font-semibold">Supporting evidence</h2>
        {snap.explanation.abstained && (
          <p className="mt-2 text-sm text-muted">
            No recent news or filing evidence was found for {snap.ticker}; this reflects the
            deterministic signal only.
          </p>
        )}
        {snap.evidence.length > 0 && (
          <div className="mt-3 space-y-3">
            {snap.evidence.map((e, i) => (
              <div key={i} className="rounded-lg border border-line p-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-medium">{e.title || "(untitled)"}</span>
                  <Badge tone="neutral">
                    {sourceLabel(e.source_type)}
                    {e.published_at ? ` · ${e.published_at.slice(0, 10)}` : ""}
                  </Badge>
                </div>
                <p className="mt-1 text-sm text-muted">{e.snippet}</p>
                {e.source_url && (
                  <a
                    href={e.source_url}
                    target="_blank"
                    rel="noreferrer"
                    className="mt-1 inline-flex items-center gap-1 text-xs text-brand-600 hover:underline"
                  >
                    Source <ExternalLink className="size-3" />
                  </a>
                )}
              </div>
            ))}
          </div>
        )}
        {snap.explanation.caveats.length > 0 && (
          <div className="mt-4 border-t border-line pt-3">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted">Important</p>
            <ul className="mt-1 space-y-1 text-xs text-muted">
              {snap.explanation.caveats.map((c, i) => (
                <li key={i}>• {c}</li>
              ))}
            </ul>
          </div>
        )}
      </Card>
    </>
  );
}
