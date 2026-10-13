import { Check } from "lucide-react";
import { Badge, Card } from "@/components/ui";
import { formatPercent } from "@/lib/format";
import type { Dashboard } from "@/lib/types";
import { RiskStatusIcon, TickerMark, riskStatus } from "./shared";

/** The content-based suggestions, each with the plain-English reasons behind it. */
export function SuggestionList({ data, className = "" }: { data: Dashboard; className?: string }) {
  const limit = data.risk_level.volatility_limit;
  return (
    <Card className={className}>
      <div className="border-b border-line p-5">
        <h2 className="text-sm font-semibold">Suggested for you</h2>
        <p className="mt-1 text-sm text-muted">
          Stocks and ETFs that resemble your interests, the tickers you follow and your risk level. A starting point for your
          own research, not financial advice.
        </p>
      </div>

      {data.suggestions.length === 0 ? (
        <p className="p-5 text-sm text-muted">
          Nothing in the catalogue matches your profile yet. Try adding interests or following a few tickers on your profile.
        </p>
      ) : (
        <ol aria-label="Suggested stocks and ETFs" className="divide-y divide-line">
          {data.suggestions.map((s) => {
            const status = riskStatus(s, limit);
            return (
              <li key={s.ticker} className="flex gap-4 p-5">
                <TickerMark ticker={s.ticker} />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-baseline gap-x-2">
                    <span className="font-semibold">{s.ticker}</span>
                    <span className="truncate text-sm text-muted">{s.name}</span>
                  </div>
                  <div className="mt-1.5 flex flex-wrap gap-1.5">
                    <Badge tone="brand">{s.asset_type === "etf" ? "ETF" : "Stock"}</Badge>
                    <Badge>{s.category ?? s.sector}</Badge>
                  </div>
                  <ul className="mt-3 space-y-1.5 text-sm text-muted">
                    {s.reasons.map((reason, i) => (
                      <li key={reason} className="flex gap-2">
                        {/* The recommender always puts the risk reason last. */}
                        {i === s.reasons.length - 1 ? (
                          <RiskStatusIcon status={status} className="mt-0.5 size-4" />
                        ) : (
                          <Check className="mt-0.5 size-4 shrink-0 text-brand-500" aria-hidden />
                        )}
                        {reason}
                      </li>
                    ))}
                  </ul>
                </div>
                <div className="hidden shrink-0 text-right sm:block">
                  <p className="text-xs text-muted">Yearly swings</p>
                  <p className="mt-0.5 text-sm font-semibold tabular-nums">{formatPercent(s.risk?.volatility_1y)}</p>
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </Card>
  );
}
