"use client";

import { useState } from "react";
import { ChartBar, ShieldCheck, Table2, TriangleAlert, Info } from "lucide-react";
import { Card } from "@/components/ui";
import type { DashboardAsset } from "@/lib/types";

export type RiskStatus = "within" | "above" | "unknown";

/** Whether an asset's one-year volatility is within the investor's limit. */
export function riskStatus(asset: DashboardAsset, limit: number): RiskStatus {
  const volatility = asset.risk?.volatility_1y;
  if (volatility == null) return "unknown";
  return volatility <= limit ? "within" : "above";
}

/** Icon that carries the risk status next to its text label (colour is never the only cue). */
export function RiskStatusIcon({ status, className = "size-4" }: { status: RiskStatus; className?: string }) {
  if (status === "within") return <ShieldCheck className={`${className} shrink-0 text-emerald-600`} aria-hidden />;
  if (status === "above") return <TriangleAlert className={`${className} shrink-0 text-amber-600`} aria-hidden />;
  return <Info className={`${className} shrink-0 text-muted`} aria-hidden />;
}

export function TickerMark({ ticker, size = "md" }: { ticker: string; size?: "sm" | "md" }) {
  const box = size === "sm" ? "size-9 text-[11px]" : "size-11 text-xs";
  return (
    <span
      className={`flex ${box} shrink-0 items-center justify-center rounded-xl bg-brand-50 font-semibold tracking-tight text-brand-700 ring-1 ring-brand-100`}
      aria-hidden
    >
      {ticker.replace(/[^A-Z]/g, "").slice(0, 4)}
    </span>
  );
}

export function LegendSwatch({ className, children }: { className: string; children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={`inline-block size-2.5 rounded-sm ${className}`} aria-hidden />
      {children}
    </span>
  );
}

/**
 * A chart in a card, with the accessible table view one click away. `table` renders the
 * same data as an HTML table; `legend` sits between the heading and the plot.
 */
export function ChartCard({
  title,
  description,
  legend,
  table,
  className = "",
  children,
}: {
  title: string;
  description?: React.ReactNode;
  legend?: React.ReactNode;
  table: React.ReactNode;
  className?: string;
  children: React.ReactNode;
}) {
  const [showTable, setShowTable] = useState(false);
  return (
    <Card className={`flex flex-col p-5 ${className}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold">{title}</h2>
          {description && <p className="mt-1 text-sm text-muted">{description}</p>}
        </div>
        <button
          type="button"
          onClick={() => setShowTable((v) => !v)}
          aria-pressed={showTable}
          className="inline-flex shrink-0 items-center gap-1.5 rounded-md border border-line px-2.5 py-1 text-xs font-medium text-muted transition-colors hover:bg-canvas hover:text-ink focus-visible:outline-2 focus-visible:outline-brand-500"
        >
          {showTable ? <ChartBar className="size-3.5" aria-hidden /> : <Table2 className="size-3.5" aria-hidden />}
          {showTable ? "Chart" : "Table"}
        </button>
      </div>
      {legend && !showTable && <div className="mt-4 flex flex-wrap gap-x-4 gap-y-1.5 text-xs text-muted">{legend}</div>}
      <div className="mt-4 flex-1">{showTable ? <div className="overflow-x-auto">{table}</div> : children}</div>
    </Card>
  );
}

export const tableClass = "w-full text-left text-xs [&_td]:border-b [&_td]:border-line [&_td]:py-2 [&_td]:pr-3 [&_th]:pb-2 [&_th]:pr-3 [&_th]:font-semibold [&_th]:text-muted";
