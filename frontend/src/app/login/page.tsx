"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Logo } from "@/components/Logo";
import { Alert, Button, Field, Input } from "@/components/ui";
import { errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";

// Only same-site relative paths — never redirect to an attacker-supplied URL.
function safeNext(next: string | null): string {
  return next && next.startsWith("/") && !next.startsWith("//") ? next : "/";
}

function LoginForm() {
  const { user, loading, login } = useAuth();
  const router = useRouter();
  const params = useSearchParams();
  const next = safeNext(params.get("next"));

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // Already signed in (e.g. opened /login in a second tab) -> go on to the app.
  useEffect(() => {
    if (!loading && user) router.replace(next);
  }, [loading, user, next, router]);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(email, password);
      router.replace(next);
    } catch (err) {
      setError(errorMessage(err));
      setSubmitting(false);
    }
  }

  return (
    <div className="w-full max-w-sm">
      <Logo className="mb-8 text-ink lg:hidden" />
      <h1 className="text-2xl font-semibold tracking-tight">Sign in</h1>
      <p className="mt-1 mb-6 text-sm text-muted">Welcome back. Enter your details to continue.</p>

      <form onSubmit={onSubmit} className="space-y-4">
        {params.get("reason") === "expired" && !error && <Alert tone="info">Your session has ended. Please sign in again.</Alert>}
        {error && <Alert>{error}</Alert>}
        <Field label="Email" htmlFor="email">
          <Input id="email" type="email" autoComplete="username" required autoFocus value={email} onChange={(e) => setEmail(e.target.value)} />
        </Field>
        <Field label="Password" htmlFor="password">
          <Input
            id="password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </Field>
        <Button type="submit" className="w-full" loading={submitting}>
          Sign in
        </Button>
      </form>

      <p className="mt-8 text-xs text-muted">For research and educational purposes only. Not financial advice.</p>
    </div>
  );
}

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

export default function LoginPage() {
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

      <section className="flex items-center justify-center p-6 sm:p-12">
        {/* useSearchParams needs a Suspense boundary for static rendering. */}
        <Suspense>
          <LoginForm />
        </Suspense>
      </section>
    </main>
  );
}
