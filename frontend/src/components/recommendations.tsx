import { Badge } from "@/components/ui";
import type { Forecast, Stance } from "@/lib/types";

const STANCE: Record<Stance, { tone: "green" | "amber" | "red"; label: string; blurb: string }> = {
  EXPLORE: { tone: "green", label: "Explore", blurb: "Worth a closer look" },
  MONITOR: { tone: "amber", label: "Monitor", blurb: "Keep on your radar" },
  CAUTION: { tone: "red", label: "Caution", blurb: "Higher risk — research carefully" },
};

/** The research signal pill. A trailing * marks a provisional (experimental) news-driven stance. */
export function StanceBadge({ stance, provisional }: { stance: Stance; provisional?: boolean }) {
  const meta = STANCE[stance];
  return (
    <Badge tone={meta.tone}>
      {meta.label}
      {provisional ? "*" : ""}
    </Badge>
  );
}

export function stanceBlurb(stance: Stance): string {
  return STANCE[stance].blurb;
}

/** Human-readable forecast, or the placeholder note while XGBoost serving isn't wired. */
export function forecastLabel(forecast: Forecast): string {
  if (forecast.return_10d === null) return "Forecast pending";
  const pct = `${forecast.return_10d >= 0 ? "+" : ""}${forecast.return_10d.toFixed(1)}%`;
  if (forecast.lower !== null && forecast.upper !== null) {
    return `${pct}  (range ${forecast.lower.toFixed(1)}% to ${forecast.upper.toFixed(1)}%)`;
  }
  return pct;
}

export function sourceLabel(sourceType: string): string {
  return sourceType === "sec" ? "SEC filing" : sourceType === "news" ? "News" : sourceType;
}
