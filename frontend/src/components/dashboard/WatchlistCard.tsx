import Link from "next/link";
import { ListPlus } from "lucide-react";
import { Card, LinkButton } from "@/components/ui";
import { formatPercent } from "@/lib/format";
import type { Dashboard } from "@/lib/types";
import { RiskStatusIcon, TickerMark, riskStatus } from "./shared";

/** The tickers the investor follows, with their headline risk numbers. */
export function WatchlistCard({ data, className = "" }: { data: Dashboard; className?: string }) {
  const { volatility_limit: limit, label } = data.risk_level;
  return (
    <Card className={`flex flex-col ${className}`}>
      <div className="flex items-start justify-between gap-3 border-b border-line p-5">
        <div>
          <h2 className="text-sm font-semibold">Your watchlist</h2>
          <p className="mt-1 text-sm text-muted">Tickers you follow, over the past year.</p>
        </div>
        {data.watchlist.length > 0 && (
          <Link href="/profile" className="shrink-0 text-xs font-medium text-brand-600 hover:underline">
            Manage
          </Link>
        )}
      </div>

      {data.watchlist.length === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-3 p-8 text-center">
          <span className="flex size-11 items-center justify-center rounded-xl bg-brand-50 text-brand-600" aria-hidden>
            <ListPlus className="size-5" />
          </span>
          <p className="text-sm text-muted">You&apos;re not following any tickers yet. Follow a few to compare them here.</p>
          <LinkButton href="/profile" variant="secondary">
            Follow tickers
          </LinkButton>
        </div>
      ) : (
        <ul className="divide-y divide-line">
          {data.watchlist.map((a) => {
            const status = riskStatus(a, limit);
            return (
              <li key={a.ticker} className="flex items-center gap-3 px-5 py-3.5">
                <TickerMark ticker={a.ticker} size="sm" />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm">
                    <span className="font-semibold">{a.ticker}</span> <span className="text-muted">{a.name}</span>
                  </p>
                  <p className="mt-0.5 text-xs text-muted">
                    Worst fall {formatPercent(a.risk?.max_drawdown_1y)} · Dividend {formatPercent(a.risk?.dividend_yield, true)}
                  </p>
                </div>
                <div
                  className="flex shrink-0 items-center gap-1.5 text-sm font-semibold tabular-nums"
                  title={`Yearly price swings, ${status === "above" ? "above" : status === "within" ? "within" : "unknown vs"} your ${label} level`}
                >
                  {formatPercent(a.risk?.volatility_1y)}
                  <RiskStatusIcon status={status} className="size-4" />
                  <span className="sr-only">{status === "above" ? "above your risk level" : status === "within" ? "within your risk level" : "not enough history"}</span>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}
