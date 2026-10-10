import {
  AlertTriangle,
  Clock,
  Info,
  Minus,
  Newspaper,
  PieChart,
  ThumbsDown,
  ThumbsUp,
  TrendingUp,
  type LucideIcon,
} from "lucide-react";
import { Badge } from "@/components/ui";
import type { Forecast, RecommendationSnapshot, Stance } from "@/lib/types";

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

/** The outlet name from a URL (e.g. "benzinga.com"), for a news byline. */
export function hostname(url: string | null): string {
  if (!url) return "";
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "";
  }
}

/** Icon + colour for a decision-trace line, so the "why" reads at a glance. */
export function reasonStyle(line: string): { Icon: LucideIcon; iconClass: string; chipClass: string } {
  const l = line.toLowerCase();
  if (/favorable|supportive|bullish|aligned|confidence|narrow|strong/.test(l))
    return { Icon: TrendingUp, iconClass: "text-emerald-600", chipClass: "bg-emerald-50" };
  if (/mismatch|downside|adverse|bearish|exceeds|loss/.test(l))
    return { Icon: AlertTriangle, iconClass: "text-red-600", chipClass: "bg-red-50" };
  if (/news|sentiment|coverage/.test(l))
    return { Icon: Newspaper, iconClass: "text-brand-600", chipClass: "bg-brand-50" };
  if (/concentration|diversif/.test(l))
    return { Icon: PieChart, iconClass: "text-amber-600", chipClass: "bg-amber-50" };
  if (/pending|uncertainty|capped|moderate|below|mild|neutral/.test(l))
    return { Icon: Clock, iconClass: "text-slate-500", chipClass: "bg-slate-100" };
  return { Icon: Info, iconClass: "text-brand-600", chipClass: "bg-brand-50" };
}

/** Good/bad flag for a news article from its sentiment score (null → no flag). */
export function sentimentFlag(
  score: number | null,
): { label: string; tone: "green" | "red" | "neutral"; Icon: LucideIcon } | null {
  if (score === null || score === undefined) return null;
  if (score <= -0.15) return { label: "Negative", tone: "red", Icon: ThumbsDown };
  if (score >= 0.15) return { label: "Positive", tone: "green", Icon: ThumbsUp };
  return { label: "Neutral", tone: "neutral", Icon: Minus };
}

/** Split a short summary into its lead sentences, for scannable bullets. */
export function toBullets(text: string, max = 3): string[] {
  return (text || "")
    .split(/(?<=[.!?])\s+/)
    .map((s) => s.trim())
    .filter((s) => s.length > 12)
    .slice(0, max);
}

/** One plain-English takeaway sentence, composed from the structured signal (no jargon). */
export function takeaway(snap: RecommendationSnapshot): string {
  const stance = snap.signal.news_aware_stance;
  const base =
    stance === "CAUTION"
      ? "Flagged Caution — treat this as higher-risk and research it carefully before acting."
      : stance === "EXPLORE"
        ? "Worth exploring — the current signals are constructive."
        : "One to monitor — keep it on your radar; the signals are mixed right now.";
  const score = snap.signal.news_signal.score;
  const news =
    score === null
      ? ""
      : score <= -0.15
        ? " Recent news coverage has been negative."
        : score >= 0.15
          ? " Recent news coverage has been positive."
          : " Recent news coverage is mixed.";
  return base + news;
}
