import { ChartNoAxesCombined, GraduationCap, ShieldCheck } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Logo } from "@/components/Logo";

const POINTS: { icon: LucideIcon; title: string; text: string }[] = [
  { icon: ShieldCheck, title: "Explainable signals", text: "Explore, Monitor or Caution, each with plain-English reasons." },
  { icon: ChartNoAxesCombined, title: "Forecasts with uncertainty", text: "10-day ranges and confidence levels, never a single number." },
  { icon: GraduationCap, title: "Made for learning", text: "Research support only. No buy or sell instructions." },
];

/** A decorative price line. Illustration only: it is not real market data, and is labelled as such. */
function ChartIllustration() {
  const line = "0,95 40,88 80,92 120,70 160,76 200,52 240,58 280,36 320,42 360,20 400,14";
  return (
    <div className="rounded-2xl border border-white/10 bg-white/[0.04] p-5">
      <div className="flex items-center justify-between text-xs text-slate-400">
        <span className="font-medium text-slate-300">Price trend</span>
        <span>Illustration</span>
      </div>
      <svg viewBox="0 0 400 120" className="mt-3 h-28 w-full" fill="none" aria-hidden>
        <defs>
          <linearGradient id="auth-area" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor="#34d399" stopOpacity="0.28" />
            <stop offset="100%" stopColor="#34d399" stopOpacity="0" />
          </linearGradient>
        </defs>
        {[30, 60, 90].map((y) => (
          <line key={y} x1="0" x2="400" y1={y} y2={y} stroke="white" strokeOpacity="0.07" />
        ))}
        <polygon points={`0,120 ${line} 400,120`} fill="url(#auth-area)" />
        <polyline points={line} stroke="#34d399" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </div>
  );
}

/** Two-column shell for the signed-out pages: brand panel on the left, `children` (the form) on the right. */
export function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <main className="grid min-h-screen lg:grid-cols-[1.1fr_1fr]">
      <section
        className="relative hidden flex-col justify-between overflow-hidden bg-sidebar p-12 text-slate-300 lg:flex"
        style={{
          backgroundImage:
            "radial-gradient(60rem 30rem at 85% -10%, rgb(37 99 235 / 0.22), transparent 60%), linear-gradient(rgb(255 255 255 / 0.035) 1px, transparent 1px), linear-gradient(90deg, rgb(255 255 255 / 0.035) 1px, transparent 1px)",
          backgroundSize: "auto, 44px 44px, 44px 44px",
        }}
      >
        <Logo className="text-white" />
        <div className="max-w-md space-y-8">
          <div>
            <h2 className="text-[2rem] leading-tight font-semibold tracking-tight text-white">Research US stocks and ETFs with confidence.</h2>
            <p className="mt-3 leading-relaxed text-slate-300">One place for market context, news and easy-to-follow research signals.</p>
          </div>
          <ChartIllustration />
          <ul className="space-y-4">
            {POINTS.map(({ icon: Icon, title, text }) => (
              <li key={title} className="flex gap-3.5">
                <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-white/[0.07] text-emerald-300 ring-1 ring-white/10 ring-inset" aria-hidden>
                  <Icon className="size-[18px]" />
                </span>
                <p className="text-sm leading-relaxed">
                  <span className="font-medium text-white">{title}.</span> {text}
                </p>
              </li>
            ))}
          </ul>
        </div>
        <p className="max-w-md text-xs leading-relaxed text-slate-400">
          Forecasts are model-based estimates, not guarantees. Past performance is not indicative of future results.
        </p>
      </section>

      <section className="flex items-center justify-center bg-surface p-6 sm:p-12">{children}</section>
    </main>
  );
}
