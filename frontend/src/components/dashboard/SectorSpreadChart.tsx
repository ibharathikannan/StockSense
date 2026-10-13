"use client";

import { useState } from "react";
import type { Dashboard } from "@/lib/types";
import { ChartCard, LegendSwatch, tableClass } from "./shared";

interface SectorRow {
  sector: string;
  watchlist: number;
  suggested: number;
}

/** Stacked bars: how many watchlist and suggested assets fall in each sector. */
export function SectorSpreadChart({ data, className = "" }: { data: Dashboard; className?: string }) {
  const [active, setActive] = useState<string | null>(null);

  const bySector = new Map<string, SectorRow>();
  const add = (sector: string, list: "watchlist" | "suggested") => {
    const row = bySector.get(sector) ?? { sector, watchlist: 0, suggested: 0 };
    row[list] += 1;
    bySector.set(sector, row);
  };
  data.watchlist.forEach((a) => add(a.sector, "watchlist"));
  data.suggestions.forEach((a) => add(a.sector, "suggested"));
  const rows = [...bySector.values()].sort(
    (a, b) => b.watchlist + b.suggested - (a.watchlist + a.suggested) || a.sector.localeCompare(b.sector),
  );
  const max = Math.max(1, ...rows.map((r) => r.watchlist + r.suggested));

  const table = (
    <table className={tableClass}>
      <thead>
        <tr>
          <th>Sector</th>
          <th>Watchlist</th>
          <th>Suggested</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.sector}>
            <td className="text-ink">{r.sector}</td>
            <td className="tabular-nums">{r.watchlist}</td>
            <td className="tabular-nums">{r.suggested}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );

  return (
    <ChartCard
      className={className}
      title="Sector spread"
      description={rows.length > 1 ? `Your list spans ${rows.length} sectors.` : "Where your list sits by sector."}
      legend={
        <>
          <LegendSwatch className="bg-chart-watchlist">Watchlist</LegendSwatch>
          <LegendSwatch className="bg-chart-suggested">Suggested</LegendSwatch>
        </>
      }
      table={table}
    >
      {rows.length === 0 ? (
        <p className="py-8 text-center text-sm text-muted">Nothing to show yet.</p>
      ) : (
        <ul className="space-y-3.5">
          {rows.map((r) => {
            const total = r.watchlist + r.suggested;
            const detail = [r.watchlist && `${r.watchlist} watchlist`, r.suggested && `${r.suggested} suggested`]
              .filter(Boolean)
              .join(" · ");
            const isActive = active === r.sector;
            return (
              <li
                key={r.sector}
                tabIndex={0}
                aria-label={`${r.sector}: ${detail}`}
                onMouseEnter={() => setActive(r.sector)}
                onMouseLeave={() => setActive(null)}
                onFocus={() => setActive(r.sector)}
                onBlur={() => setActive(null)}
                className="rounded-md outline-none focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:ring-offset-2"
              >
                <div className="flex items-baseline justify-between gap-3 text-xs">
                  <span className="truncate text-ink">{r.sector}</span>
                  <span className={`shrink-0 tabular-nums ${isActive ? "text-ink" : "text-muted"}`}>
                    {isActive ? detail : total}
                  </span>
                </div>
                {/* Segments are separated by a 2px surface gap; only the data end is rounded. */}
                <div className="mt-1.5 flex h-3 gap-0.5" style={{ width: `${(total / max) * 100}%` }} aria-hidden>
                  {r.watchlist > 0 && (
                    <div
                      className={`h-full bg-chart-watchlist ${r.suggested ? "" : "rounded-r-[4px]"}`}
                      style={{ flexGrow: r.watchlist }}
                    />
                  )}
                  {r.suggested > 0 && (
                    <div className="h-full rounded-r-[4px] bg-chart-suggested" style={{ flexGrow: r.suggested }} />
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </ChartCard>
  );
}
