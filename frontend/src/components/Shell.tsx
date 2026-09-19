"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { LogOut, Menu, X } from "lucide-react";
import { useAuth } from "@/lib/auth";
import { Logo } from "@/components/Logo";
import { NAV_ITEMS } from "@/lib/nav";

function isActive(pathname: string, href: string) {
  return href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`);
}

function initials(name: string) {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]!.toUpperCase())
    .join("");
}

export function Shell({ children }: { children: React.ReactNode }) {
  const { user, can, logout } = useAuth();
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  if (!user) return null;

  const items = NAV_ITEMS.filter((item) => !item.permission || can(item.permission));

  return (
    <div className="min-h-screen lg:flex">
      {open && <div className="fixed inset-0 z-30 bg-slate-900/40 lg:hidden" onClick={() => setOpen(false)} />}

      <aside
        className={`fixed inset-y-0 left-0 z-40 flex w-64 flex-col bg-sidebar text-slate-200 transition-transform lg:sticky lg:top-0 lg:h-screen lg:translate-x-0 ${
          open ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="flex h-16 items-center justify-between px-5">
          <Logo className="text-white" />
          <button className="rounded p-1 hover:bg-sidebar-hover lg:hidden" onClick={() => setOpen(false)} aria-label="Close menu">
            <X className="size-5" />
          </button>
        </div>

        <nav className="flex-1 space-y-1 px-3 py-2" aria-label="Main">
          {items.map(({ label, href, icon: Icon }) => (
            <Link
              key={href}
              href={href}
              onClick={() => setOpen(false)}
              aria-current={isActive(pathname, href) ? "page" : undefined}
              className={`flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors ${
                isActive(pathname, href) ? "bg-sidebar-active text-white" : "hover:bg-sidebar-hover hover:text-white"
              }`}
            >
              <Icon className="size-[18px]" aria-hidden />
              {label}
            </Link>
          ))}
        </nav>

        <div className="border-t border-white/10 p-3">
          <button
            onClick={() => void logout()}
            className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium hover:bg-sidebar-hover hover:text-white"
          >
            <LogOut className="size-[18px]" aria-hidden />
            Sign out
          </button>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex h-16 items-center justify-between gap-4 border-b border-line bg-surface px-4 sm:px-8">
          <button className="rounded p-2 hover:bg-canvas lg:hidden" onClick={() => setOpen(true)} aria-label="Open menu">
            <Menu className="size-5" />
          </button>
          <div className="ml-auto flex items-center gap-3">
            <div className="hidden text-right sm:block">
              <p className="text-sm font-medium leading-tight">{user.full_name}</p>
              <p className="text-xs text-muted">{user.role}</p>
            </div>
            <div
              className="flex size-9 items-center justify-center rounded-full bg-brand-100 text-sm font-semibold text-brand-700"
              aria-hidden
            >
              {initials(user.full_name) || "?"}
            </div>
          </div>
        </header>

        <main className="flex-1 px-4 py-8 sm:px-8">
          {/* key={pathname}: re-mount on navigation so every page fades in */}
          <div key={pathname} className="mx-auto max-w-6xl animate-fade-in-up motion-reduce:animate-none">
            {children}
          </div>
        </main>

        <footer className="border-t border-line px-4 py-4 text-center text-xs text-muted sm:px-8">
          For research and educational purposes only. Not financial advice.
        </footer>
      </div>
    </div>
  );
}
