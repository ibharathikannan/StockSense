import { Eye, Gauge, ShieldCheck, Sparkles } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Card } from "@/components/ui";
import { formatPercent } from "@/lib/format";
import type { Dashboard } from "@/lib/types";
import { riskStatus } from "./shared";

function Tile({
  label,
  value,
  caption,
  icon: Icon,
  children,
}: {
  label: string;
  value: React.ReactNode;
  caption: React.ReactNode;
  icon: LucideIcon;
  children?: React.ReactNode;
}) {
  return (
    <Card className="flex flex-col p-5">
      <div className="flex items-start justify-between gap-3">
        <p className="text-sm text-muted">{label}</p>
        <span className="flex size-8 items-center justify-center rounded-lg bg-brand-50 text-brand-600" aria-hidden>
          <Icon className="size-4" />
        </span>
      </div>
      <p className="mt-1 text-2xl font-semibold tracking-tight">{value}</p>
      {children && <div className="mt-3">{children}</div>}
      <p className="mt-auto pt-2 text-xs text-muted">{caption}</p>
    </Card>
  );
}

/** Ordered steps from very conservative to aggressive, filled up to the investor's level. */
function RiskSteps({ step, steps, label }: { step: number | null; steps: number; label: string }) {
  return (
    <div
      className="flex gap-1"
      role="img"
      aria-label={step ? `${label}: step ${step} of ${steps}, from very conservative to aggressive` : label}
    >
      {Array.from({ length: steps }, (_, i) => (
        <span key={i} className={`h-1.5 flex-1 rounded-full ${step && i < step ? "bg-brand-500" : "bg-brand-100"}`} />
      ))}
    </div>
  );
}

function Meter({ value, label }: { value: number; label: string }) {
  return (
    <div
      className="h-1.5 overflow-hidden rounded-full bg-brand-100"
      role="meter"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(value * 100)}
    >
      <div className="h-full rounded-full bg-brand-500" style={{ width: `${value * 100}%` }} />
    </div>
  );
}

export function DashboardTiles({ data }: { data: Dashboard }) {
  const { label, volatility_limit: limit, step, steps } = data.risk_level;
  const within = (assets: Dashboard["watchlist"]) => assets.filter((a) => riskStatus(a, limit) === "within").length;
  const all = [...data.watchlist, ...data.suggestions];
  const withinAll = within(all);
  const interests = data.interests.map((i) => i.label);

  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <Tile label="Risk level" value={label} icon={Gauge} caption={`Comfortable with yearly swings up to ${formatPercent(limit)}`}>
        <RiskSteps step={step} steps={steps} label={label} />
      </Tile>
      <Tile
        label="Following"
        value={data.watchlist.length}
        icon={Eye}
        caption={
          data.watchlist.length
            ? `${within(data.watchlist)} of ${data.watchlist.length} within your risk level`
            : "Follow tickers on your profile to track them here"
        }
      />
      <Tile
        label="Suggestions"
        value={data.suggestions.length}
        icon={Sparkles}
        caption={interests.length ? `Matched to ${interests.join(", ")}` : "Matched to your profile"}
      />
      <Tile
        label="Within your risk level"
        value={all.length ? `${withinAll} of ${all.length}` : "—"}
        icon={ShieldCheck}
        caption="Across your watchlist and suggestions"
      >
        <Meter value={all.length ? withinAll / all.length : 0} label={`${withinAll} of ${all.length} within your risk level`} />
      </Tile>
    </div>
  );
}
