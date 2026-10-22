"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { CircleAlert, CircleCheck, Eye, EyeOff, Info, Loader2 } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { beginActivity, endActivity } from "@/lib/activity";

// Small, dependency-free UI kit used across the app. Tailwind classes only —
// swap for shadcn/ui or MUI later without touching page logic.

type ButtonVariant = "primary" | "secondary" | "danger" | "ghost";

const buttonBase =
  "inline-flex min-h-10 items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-medium whitespace-nowrap " +
  "transition-[background-color,border-color,box-shadow,color] duration-150 " +
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-500 " +
  "disabled:cursor-not-allowed disabled:opacity-50";

const buttonVariants: Record<ButtonVariant, string> = {
  primary: "bg-brand-600 text-white shadow-sm hover:bg-brand-700 active:bg-brand-700",
  secondary: "border border-slate-300/80 bg-surface text-ink shadow-card hover:border-slate-400 hover:bg-slate-50",
  danger: "bg-red-600 text-white shadow-sm hover:bg-red-700",
  ghost: "text-muted hover:bg-slate-100 hover:text-ink",
};

export function Button({
  variant = "primary",
  loading = false,
  className = "",
  children,
  disabled,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant; loading?: boolean }) {
  return (
    <button className={`${buttonBase} ${buttonVariants[variant]} ${className}`} disabled={disabled || loading} {...props}>
      {loading && <Loader2 className="size-4 animate-spin" aria-hidden />}
      {children}
    </button>
  );
}

export function LinkButton({
  href,
  variant = "primary",
  className = "",
  children,
}: {
  href: string;
  variant?: ButtonVariant;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <Link href={href} className={`${buttonBase} ${buttonVariants[variant]} ${className}`}>
      {children}
    </Link>
  );
}

const fieldControl =
  "w-full min-h-10 rounded-lg border border-slate-300/80 bg-surface px-3 py-2 text-sm text-ink shadow-card " +
  "placeholder:text-slate-400 hover:border-slate-400 " +
  "focus:border-brand-500 focus:outline-none focus:ring-4 focus:ring-brand-500/15 " +
  "disabled:cursor-not-allowed disabled:bg-slate-50 disabled:text-muted disabled:shadow-none";

export function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={`${fieldControl} ${props.className ?? ""}`} />;
}

/** A password field with a show/hide toggle. Same props as <Input>. */
export function PasswordInput(props: Omit<React.InputHTMLAttributes<HTMLInputElement>, "type">) {
  const [visible, setVisible] = useState(false);
  return (
    <div className="relative">
      <Input {...props} type={visible ? "text" : "password"} className={`pr-11 ${props.className ?? ""}`} />
      <button
        type="button"
        onClick={() => setVisible((v) => !v)}
        aria-label={visible ? "Hide password" : "Show password"}
        aria-pressed={visible}
        className="absolute top-1/2 right-1.5 flex size-8 -translate-y-1/2 items-center justify-center rounded-md text-muted transition-colors hover:bg-slate-100 hover:text-ink"
      >
        {visible ? <EyeOff className="size-4" aria-hidden /> : <Eye className="size-4" aria-hidden />}
      </button>
    </div>
  );
}

export function Select(props: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={`${fieldControl} ${props.className ?? ""}`} />;
}

export function Field({
  label,
  htmlFor,
  hint,
  children,
}: {
  label: string;
  htmlFor: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={htmlFor} className="block text-sm font-medium text-ink">
        {label}
      </label>
      {children}
      {hint && <p className="text-xs text-muted">{hint}</p>}
    </div>
  );
}

export function Card({ className = "", children }: { className?: string; children: React.ReactNode }) {
  return <div className={`rounded-xl border border-line bg-surface shadow-card ${className}`}>{children}</div>;
}

type BadgeTone = "neutral" | "brand" | "green" | "amber" | "red";
const badgeTones: Record<BadgeTone, string> = {
  neutral: "bg-slate-100 text-slate-700 ring-slate-500/15",
  brand: "bg-brand-50 text-brand-700 ring-brand-600/15",
  green: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
  amber: "bg-amber-50 text-amber-800 ring-amber-600/20",
  red: "bg-red-50 text-red-700 ring-red-600/15",
};

export function Badge({ tone = "neutral", children }: { tone?: BadgeTone; children: React.ReactNode }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset ${badgeTones[tone]}`}
    >
      {children}
    </span>
  );
}

export function Alert({ tone = "error", children }: { tone?: "error" | "success" | "info"; children: React.ReactNode }) {
  const tones = {
    error: { box: "border-red-200 bg-red-50 text-red-900", icon: "text-red-600", Icon: CircleAlert },
    success: { box: "border-emerald-200 bg-emerald-50 text-emerald-900", icon: "text-emerald-600", Icon: CircleCheck },
    info: { box: "border-brand-200 bg-brand-50 text-brand-700", icon: "text-brand-600", Icon: Info },
  }[tone];
  return (
    <div role={tone === "error" ? "alert" : "status"} className={`flex gap-3 rounded-lg border px-4 py-3 text-sm ${tones.box}`}>
      <tones.Icon className={`mt-0.5 size-4 shrink-0 ${tones.icon}`} aria-hidden />
      <div className="min-w-0">{children}</div>
    </div>
  );
}

/**
 * Placeholder shown while a page or form has nothing to render yet. It draws
 * nothing itself: while mounted it registers as pending work, so the shared
 * <LoadingOverlay> (blur + circle loader) covers the screen.
 */
export function PageLoader() {
  useEffect(() => {
    beginActivity();
    return endActivity;
  }, []);
  return <div className="min-h-[60vh]" aria-hidden />;
}

/** Friendly placeholder for a list or section with nothing to show yet. */
export function EmptyState({
  icon: Icon,
  title,
  action,
  children,
}: {
  icon: LucideIcon;
  title: string;
  action?: React.ReactNode;
  children?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center px-6 py-12 text-center">
      <span className="flex size-12 items-center justify-center rounded-xl bg-slate-100 text-slate-500" aria-hidden>
        <Icon className="size-6" />
      </span>
      <h2 className="mt-4 text-sm font-semibold">{title}</h2>
      {children && <p className="mt-1 max-w-sm text-sm leading-relaxed text-muted">{children}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded-md bg-slate-200/70 ${className}`} aria-hidden />;
}

/** Placeholder rows shown while a list loads (keeps the layout from jumping). */
export function TableSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div role="status" aria-label="Loading" className="divide-y divide-line">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="flex items-center gap-4 px-4 py-4">
          <Skeleton className="size-9 rounded-full" />
          <div className="flex-1 space-y-2">
            <Skeleton className="h-4 w-40" />
            <Skeleton className="h-3 w-56" />
          </div>
          <Skeleton className="h-5 w-16 rounded-full" />
          <Skeleton className="h-5 w-16 rounded-full" />
        </div>
      ))}
    </div>
  );
}

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: string;
  actions?: React.ReactNode;
}) {
  return (
    <div className="mb-8 flex flex-wrap items-start justify-between gap-4">
      <div className="min-w-0">
        <h1 className="text-[1.65rem] leading-tight font-semibold tracking-tight text-ink">{title}</h1>
        {description && <p className="mt-1.5 max-w-2xl text-sm leading-relaxed text-muted">{description}</p>}
      </div>
      {actions}
    </div>
  );
}

export function Table({ children }: { children: React.ReactNode }) {
  return (
    <div className="scroll-thin overflow-x-auto">
      <table className="w-full text-left text-sm [&_tbody_tr]:transition-colors [&_tbody_tr:hover]:bg-slate-50/80 [&_tbody_tr:last-child_td]:border-b-0">
        {children}
      </table>
    </div>
  );
}

export function Th({ children, className = "" }: { children?: React.ReactNode; className?: string }) {
  return (
    <th
      className={`border-b border-line bg-slate-50/80 px-4 py-3 text-[11px] font-semibold tracking-wider text-muted uppercase ${className}`}
    >
      {children}
    </th>
  );
}

export function Td({ children, className = "", colSpan }: { children?: React.ReactNode; className?: string; colSpan?: number }) {
  return (
    <td colSpan={colSpan} className={`border-b border-line px-4 py-3.5 align-middle ${className}`}>
      {children}
    </td>
  );
}

const AVATAR_TONES = [
  "bg-brand-100 text-brand-700",
  "bg-emerald-100 text-emerald-700",
  "bg-amber-100 text-amber-800",
  "bg-violet-100 text-violet-700",
  "bg-sky-100 text-sky-700",
  "bg-rose-100 text-rose-700",
];

function initials(name: string) {
  return (
    name
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((part) => part[0]!.toUpperCase())
      .join("") || "?"
  );
}

/** Initials in a soft circle. The tint is derived from the name, so a person keeps the same colour everywhere. */
export function Avatar({ name, size = "md", className = "" }: { name: string; size?: "sm" | "md" | "lg"; className?: string }) {
  const hash = [...name].reduce((sum, ch) => (sum * 31 + ch.charCodeAt(0)) >>> 0, 7);
  const box = size === "sm" ? "size-8 text-xs" : size === "lg" ? "size-11 text-base" : "size-9 text-sm";
  return (
    <span
      className={`flex shrink-0 items-center justify-center rounded-full font-semibold ${box} ${AVATAR_TONES[hash % AVATAR_TONES.length]} ${className}`}
      aria-hidden
    >
      {initials(name)}
    </span>
  );
}
