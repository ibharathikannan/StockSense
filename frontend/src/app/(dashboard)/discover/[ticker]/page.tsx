"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft, ExternalLink, FileText } from "lucide-react";
import { Alert, Card, PageHeader, PageLoader } from "@/components/ui";
import {
  StanceBadge,
  forecastLabel,
  hostname,
  reasonStyle,
  takeaway,
} from "@/components/recommendations";
import { errorMessage } from "@/lib/api";
import { useFetch } from "@/lib/hooks";
import { recommendationsService } from "@/services/recommendations";
import type { Evidence, Stance } from "@/lib/types";

function BackLink() {
  return (
    <Link href="/discover" className="mb-4 inline-flex items-center gap-1 text-sm text-muted hover:text-ink">
      <ArrowLeft className="size-4" /> Back to Discover
    </Link>
  );
}

const takeawayTint: Record<Stance, string> = {
  EXPLORE: "border-emerald-200 bg-emerald-50",
  MONITOR: "border-amber-200 bg-amber-50",
  CAUTION: "border-red-200 bg-red-50",
};

function ReasonList({ lines }: { lines: string[] }) {
  return (
    <ul className="mt-3 space-y-2.5">
      {lines.map((line, i) => {
        const { Icon, iconClass, chipClass } = reasonStyle(line);
        return (
          <li key={i} className="flex items-start gap-3">
            <span className={`mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-lg ${chipClass}`}>
              <Icon className={`size-4 ${iconClass}`} aria-hidden />
            </span>
            <span className="text-sm leading-relaxed">{line}</span>
          </li>
        );
      })}
    </ul>
  );
}

function NewsItem({ e }: { e: Evidence }) {
  const outlet = hostname(e.source_url);
  const date = e.published_at ? e.published_at.slice(0, 10) : "";
  const headline = (
    <p className="font-medium leading-snug">{e.title || "News update"}</p>
  );
  return (
    <div className="rounded-xl border border-line p-4 transition-shadow hover:shadow-sm">
      {e.source_url ? (
        <a href={e.source_url} target="_blank" rel="noreferrer" className="group">
          <span className="group-hover:text-brand-600">{headline}</span>
        </a>
      ) : (
        headline
      )}
      <p className="mt-1 text-xs text-muted">
        {[outlet, date].filter(Boolean).join(" · ")}
      </p>
      <p className="mt-2 text-sm text-muted">{e.snippet}</p>
      {e.source_url && (
        <a
          href={e.source_url}
          target="_blank"
          rel="noreferrer"
          className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-brand-600 hover:underline"
        >
          Read the article <ExternalLink className="size-3" />
        </a>
      )}
    </div>
  );
}

function FilingItem({ e }: { e: Evidence }) {
  const date = e.published_at ? e.published_at.slice(0, 10) : "";
  return (
    <div className="rounded-lg border border-line bg-canvas/40 p-3">
      <div className="flex items-center gap-2 text-xs font-medium text-muted">
        <FileText className="size-3.5" aria-hidden />
        {e.title || "Company SEC filing"}
        {date && <span>· {date}</span>}
      </div>
      <p className="mt-1.5 text-sm text-muted">{e.snippet}</p>
      {e.source_url && (
        <a
          href={e.source_url}
          target="_blank"
          rel="noreferrer"
          className="mt-1 inline-flex items-center gap-1 text-xs text-brand-600 hover:underline"
        >
          View filing <ExternalLink className="size-3" />
        </a>
      )}
    </div>
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

  const news = snap.evidence.filter((e) => e.source_type === "news");
  const filings = snap.evidence.filter((e) => e.source_type === "sec");

  return (
    <>
      <BackLink />
      <PageHeader
        title={`${snap.name} (${snap.ticker})`}
        description={`${snap.sector} · ${snap.asset_type}`}
        actions={<StanceBadge stance={snap.signal.news_aware_stance} provisional={snap.signal.provisional} />}
      />

      {/* Plain-English takeaway */}
      <Card className={`mb-6 p-5 ${takeawayTint[snap.signal.news_aware_stance]}`}>
        <p className="text-sm font-medium leading-relaxed text-ink">{takeaway(snap)}</p>
      </Card>

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="p-5">
          <h2 className="text-sm font-semibold text-muted">10-day forecast</h2>
          <p className="mt-2 text-2xl font-semibold tabular-nums">{forecastLabel(snap.forecast)}</p>
          <p className="mt-1 text-xs text-muted">{snap.forecast.basis}</p>
        </Card>

        <Card className="p-5 lg:col-span-2">
          <h2 className="text-sm font-semibold">Why this signal</h2>
          <ReasonList lines={snap.signal.decision_trace} />
        </Card>
      </div>

      {/* Recent news — the primary, most readable evidence */}
      <section className="mt-8">
        <h2 className="mb-1 text-lg font-semibold">Recent news</h2>
        <p className="mb-3 text-sm text-muted">What&apos;s been reported about {snap.name} lately.</p>
        {news.length > 0 ? (
          <div className="grid gap-3 md:grid-cols-2">
            {news.map((e, i) => (
              <NewsItem key={i} e={e} />
            ))}
          </div>
        ) : (
          <Card className="p-4 text-sm text-muted">No recent news coverage was found for {snap.ticker}.</Card>
        )}
      </section>

      {/* Company filings — secondary, official but denser */}
      {filings.length > 0 && (
        <section className="mt-8">
          <h2 className="mb-1 text-lg font-semibold">From company filings</h2>
          <p className="mb-3 text-sm text-muted">
            Excerpts from {snap.name}&apos;s official SEC disclosures (for reference — these are dense by nature).
          </p>
          <div className="space-y-3">
            {filings.map((e, i) => (
              <FilingItem key={i} e={e} />
            ))}
          </div>
        </section>
      )}

      {snap.explanation.caveats.length > 0 && (
        <div className="mt-8 border-t border-line pt-4">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted">Important</p>
          <ul className="mt-2 space-y-1 text-xs text-muted">
            {snap.explanation.caveats.map((c, i) => (
              <li key={i}>• {c}</li>
            ))}
          </ul>
        </div>
      )}
    </>
  );
}
