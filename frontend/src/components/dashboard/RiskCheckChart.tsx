"use client";

import { useState } from "react";
import { formatPercent } from "@/lib/format";
import type { Dashboard, DashboardAsset } from "@/lib/types";
import { ChartCard, LegendSwatch, RiskStatusIcon, riskStatus, tableClass } from "./shared";

interface Row {
  key: string;
  group: string;
  asset: DashboardAsset;
  volatility: number;
}

const LABEL_COLUMN = "5rem";
const VALUE_ROOM = "3.25rem"; // space right of the scale for the value label at a bar's tip

/**
 * Horizontal bars of one-year volatility ("yearly price swings") for the watchlist and the
 * suggestions, on one scale, with the investor's limit as a reference line.
 */
export function RiskCheckChart({ data, className = "" }: { data: Dashboard; className?: string }) {
  const { volatility_limit: limit, label } = data.risk_level;
  const [active, setActive] = useState<{ row: Row; top: number } | null>(null);

  const groups = [
    { name: "Watchlist", assets: data.watchlist },
    { name: "Suggested", assets: data.suggestions },
  ]
    .map(({ name, assets }) => ({
      name,
      rows: assets
        .filter((a) => a.risk?.volatility_1y != null)
        .map((a) => ({ key: `${name}-${a.ticker}`, group: name, asset: a, volatility: a.risk!.volatility_1y! }))
        .sort((a, b) => a.volatility - b.volatility),
    }))
    .filter((g) => g.rows.length > 0);
  const rows = groups.flatMap((g) => g.rows);
  const unknown = [...data.watchlist, ...data.suggestions].filter((a) => a.risk?.volatility_1y == null);

  const peak = Math.max(limit, ...rows.map((r) => r.volatility));
  const step = peak > 0.8 ? 0.2 : 0.1;
  const xMax = Math.ceil((peak * 1.05) / step) * step;
  const ticks = Array.from({ length: Math.round(xMax / step) + 1 }, (_, i) => i * step);
  const at = (value: number) => `${(value / xMax) * 100}%`;
  const scaleBox = { left: LABEL_COLUMN, right: VALUE_ROOM };

  const table = (
    <table className={tableClass}>
      <thead>
        <tr>
          <th>Ticker</th>
          <th>List</th>
          <th>Yearly swings</th>
          <th>Worst fall</th>
          <th>Beta</th>
          <th>vs your {label} level</th>
        </tr>
      </thead>
      <tbody>
        {[...rows.map((r) => ({ group: r.group, asset: r.asset })), ...unknown.map((a) => ({ group: "", asset: a }))].map(
          ({ group, asset }) => (
            <tr key={`${group}-${asset.ticker}`}>
              <td className="font-medium text-ink">{asset.ticker}</td>
              <td>{group || (data.watchlist.includes(asset) ? "Watchlist" : "Suggested")}</td>
              <td className="tabular-nums">{formatPercent(asset.risk?.volatility_1y)}</td>
              <td className="tabular-nums">{formatPercent(asset.risk?.max_drawdown_1y)}</td>
              <td className="tabular-nums">{asset.risk?.beta?.toFixed(2) ?? "—"}</td>
              <td>{{ within: "Within", above: "Above", unknown: "Not enough history" }[riskStatus(asset, limit)]}</td>
            </tr>
          ),
        )}
      </tbody>
    </table>
  );

  return (
    <ChartCard
      className={className}
      title="Risk check"
      description={`How much each price moved over the past year, against your ${label} level (up to ${formatPercent(limit)}).`}
      legend={
        <>
          <LegendSwatch className="bg-chart-within">
            Within your level <RiskStatusIcon status="within" className="size-3.5" />
          </LegendSwatch>
          <LegendSwatch className="bg-chart-over-limit">
            Above your level <RiskStatusIcon status="above" className="size-3.5" />
          </LegendSwatch>
          <span className="inline-flex items-center gap-1.5">
            <span className="inline-block h-3 w-0.5 rounded-full bg-ink" aria-hidden />
            Your limit
          </span>
        </>
      }
      table={table}
    >
      {rows.length === 0 ? (
        <p className="py-8 text-center text-sm text-muted">No price history yet for your watchlist or suggestions.</p>
      ) : (
        <div className="relative pt-6" onMouseLeave={() => setActive(null)}>
          {/* Gridlines and the limit line span every row, behind the bars. */}
          <div className="pointer-events-none absolute top-6 bottom-7" style={scaleBox} aria-hidden>
            {ticks.map((t) => (
              <div key={t} className="absolute inset-y-0 w-px bg-line" style={{ left: at(t) }} />
            ))}
            <div className="absolute inset-y-0 z-10 w-0.5 -translate-x-1/2 rounded-full bg-ink" style={{ left: at(limit) }}>
              <span className="absolute -top-6 left-1/2 -translate-x-1/2 whitespace-nowrap rounded bg-ink px-1.5 py-0.5 text-[11px] font-medium text-white">
                {formatPercent(limit)} limit
              </span>
            </div>
          </div>

          {groups.map((group) => (
            <div key={group.name} role="list" aria-label={group.name}>
              <p className="pt-2 pb-1 text-[11px] font-semibold uppercase tracking-wide text-muted">{group.name}</p>
              {group.rows.map((row) => {
                const status = riskStatus(row.asset, limit);
                const describe = `${row.asset.ticker}: yearly price swings ${formatPercent(row.volatility)}, ${
                  status === "above" ? "above" : "within"
                } your ${label} level`;
                return (
                  <div
                    key={row.key}
                    role="listitem"
                    tabIndex={0}
                    aria-label={describe}
                    onMouseEnter={(e) => setActive({ row, top: e.currentTarget.offsetTop })}
                    onFocus={(e) => setActive({ row, top: e.currentTarget.offsetTop })}
                    onBlur={() => setActive(null)}
                    className={`relative flex h-7 items-center rounded-md outline-none focus-visible:ring-2 focus-visible:ring-brand-500 ${
                      active?.row.key === row.key ? "bg-canvas" : ""
                    }`}
                  >
                    <span className="shrink-0 pl-1 text-xs font-medium" style={{ width: LABEL_COLUMN }}>
                      {row.asset.ticker}
                    </span>
                    <div className="relative h-full flex-1" style={{ marginRight: VALUE_ROOM }}>
                      <div
                        className={`absolute top-1/2 left-0 h-3.5 -translate-y-1/2 rounded-r-[4px] transition-opacity ${
                          status === "above" ? "bg-chart-over-limit" : "bg-chart-within"
                        } ${active && active.row.key !== row.key ? "opacity-60" : ""}`}
                        style={{ width: at(row.volatility) }}
                      />
                      {/* Above the limit line (z-20 vs z-10), on a surface patch so the line passes behind the text. */}
                      <span
                        className="absolute top-1/2 z-20 ml-1 flex -translate-y-1/2 items-center gap-1 rounded bg-surface px-1 text-xs tabular-nums text-ink"
                        style={{ left: at(row.volatility) }}
                      >
                        {formatPercent(row.volatility)}
                        {status === "above" && <RiskStatusIcon status="above" className="size-3.5" />}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          ))}

          {/* x-axis */}
          <div className="relative mt-1 h-6" style={{ marginLeft: LABEL_COLUMN, marginRight: VALUE_ROOM }} aria-hidden>
            {ticks.map((t) => (
              <span key={t} className="absolute top-1 -translate-x-1/2 text-[11px] tabular-nums text-muted" style={{ left: at(t) }}>
                {formatPercent(t)}
              </span>
            ))}
          </div>

          {active && <RowTooltip row={active.row} top={active.top} limit={limit} label={label} />}
        </div>
      )}
      {unknown.length > 0 && (
        <p className="mt-2 text-xs text-muted">
          Not enough price history yet: {unknown.map((a) => a.ticker).join(", ")}.
        </p>
      )}
    </ChartCard>
  );
}

function RowTooltip({ row, top, limit, label }: { row: Row; top: number; limit: number; label: string }) {
  const { asset, volatility } = row;
  const above = volatility > limit;
  return (
    <div
      role="status"
      className="pointer-events-none absolute right-0 z-20 w-56 -translate-y-full rounded-lg border border-line bg-surface px-3 py-2.5 text-xs shadow-lg"
      style={{ top: top - 4 }}
    >
      <p className="truncate text-muted">
        <span className="font-semibold text-ink">{asset.ticker}</span> · {asset.name}
      </p>
      <p className="mt-1.5 flex items-center gap-1.5">
        <span className="text-sm font-semibold tabular-nums text-ink">{formatPercent(volatility)}</span>
        <span className="text-muted">yearly swings</span>
      </p>
      <p className="mt-1 flex items-center gap-1.5 text-muted">
        <RiskStatusIcon status={above ? "above" : "within"} className="size-3.5" />
        {above ? "Above" : "Within"} your {label} level ({formatPercent(limit)})
      </p>
      <p className="mt-1 text-muted">
        Worst fall <span className="tabular-nums text-ink">{formatPercent(asset.risk?.max_drawdown_1y)}</span> · Beta{" "}
        <span className="tabular-nums text-ink">{asset.risk?.beta?.toFixed(2) ?? "—"}</span>
      </p>
    </div>
  );
}
