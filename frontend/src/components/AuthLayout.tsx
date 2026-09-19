import { Logo } from "@/components/Logo";

const POINTS = [
  ["Explainable signals", "Explore, Monitor or Caution, each with plain-English reasons."],
  ["Forecasts with uncertainty", "10-day ranges and confidence levels, never a single number."],
  ["Made for learning", "Research support only. No buy or sell instructions."],
];

/** A plain decorative price line — flat colours, no gradients. */
function ChartLine() {
  return (
    <svg viewBox="0 0 400 120" className="h-28 w-full" fill="none" aria-hidden>
      {[30, 60, 90].map((y) => (
        <line key={y} x1="0" x2="400" y1={y} y2={y} stroke="white" strokeOpacity="0.08" />
      ))}
      <polyline
        points="0,95 40,88 80,92 120,70 160,76 200,52 240,58 280,36 320,42 360,20 400,14"
        stroke="#34d399"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/** Two-column shell for the signed-out pages: brand panel on the left, `children` (the form) on the right. */
export function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <main className="grid min-h-screen lg:grid-cols-[1.1fr_1fr]">
      <section className="hidden flex-col justify-between bg-sidebar p-12 text-slate-200 lg:flex">
        <Logo className="text-white" />
        <div className="max-w-md space-y-8">
          <div>
            <h2 className="text-3xl font-semibold leading-tight tracking-tight text-white">Research US stocks and ETFs with confidence.</h2>
            <p className="mt-3 text-slate-300">One place for market context, news and easy-to-follow research signals.</p>
          </div>
          <ChartLine />
          <ul className="space-y-4">
            {POINTS.map(([title, text]) => (
              <li key={title} className="flex gap-3">
                <span className="mt-2 size-1.5 shrink-0 rounded-full bg-emerald-400" aria-hidden />
                <p className="text-sm">
                  <span className="font-medium text-white">{title}.</span> {text}
                </p>
              </li>
            ))}
          </ul>
        </div>
        <p className="text-xs text-slate-400">Forecasts are model-based estimates, not guarantees. Past performance is not indicative of future results.</p>
      </section>

      <section className="flex items-center justify-center p-6 sm:p-12">{children}</section>
    </main>
  );
}
