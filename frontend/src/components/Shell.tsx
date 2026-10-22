"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { Menu, X } from "lucide-react";
import { Logo } from "@/components/Logo";
import { UserMenu } from "@/components/UserMenu";
import { useAuth } from "@/lib/auth";
import { NAV_GROUPS, NAV_ITEMS, navItemFor } from "@/lib/nav";

function isActive(pathname: string, href: string) {
  return href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`);
}

export function Shell({ children }: { children: React.ReactNode }) {
  const { user, can } = useAuth();
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  if (!user) return null;

  const visible = NAV_ITEMS.filter((item) => !item.permission || can(item.permission));
  const current = navItemFor(pathname);

  return (
    <div className="min-h-screen lg:flex">
      {open && <div className="fixed inset-0 z-30 bg-slate-900/50 backdrop-blur-[1px] lg:hidden" onClick={() => setOpen(false)} />}

      <aside
        className={`fixed inset-y-0 left-0 z-40 flex w-64 flex-col bg-sidebar text-slate-300 transition-transform lg:sticky lg:top-0 lg:h-screen lg:translate-x-0 ${
          open ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="flex h-16 items-center justify-between border-b border-white/[0.07] px-5">
          <Link href="/" onClick={() => setOpen(false)} aria-label="StockSense home" className="rounded-md text-white">
            <Logo />
          </Link>
          <button
            className="rounded-md p-1.5 text-slate-400 hover:bg-sidebar-hover hover:text-white lg:hidden"
            onClick={() => setOpen(false)}
            aria-label="Close menu"
          >
            <X className="size-5" />
          </button>
        </div>

        <nav className="scroll-thin flex-1 space-y-6 overflow-y-auto px-3 py-5" aria-label="Main">
          {NAV_GROUPS.map((group) => {
            const items = visible.filter((item) => item.group === group);
            if (items.length === 0) return null;
            return (
              <div key={group}>
                <p className="mb-2 px-3 text-[11px] font-semibold tracking-wider text-slate-500 uppercase">{group}</p>
                <ul className="space-y-0.5">
                  {items.map(({ label, href, icon: Icon }) => {
                    const active = isActive(pathname, href);
                    return (
                      <li key={href}>
                        <Link
                          href={href}
                          onClick={() => setOpen(false)}
                          aria-current={active ? "page" : undefined}
                          className={`relative flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                            active
                              ? "bg-sidebar-active text-white before:absolute before:top-2 before:bottom-2 before:-left-3 before:w-[3px] before:rounded-r-full before:bg-brand-400"
                              : "text-slate-300 hover:bg-sidebar-hover hover:text-white"
                          }`}
                        >
                          <Icon className={`size-[18px] ${active ? "text-brand-200" : "text-slate-400"}`} aria-hidden />
                          {label}
                        </Link>
                      </li>
                    );
                  })}
                </ul>
              </div>
            );
          })}
        </nav>

        <p className="border-t border-white/[0.07] px-5 py-4 text-xs leading-relaxed text-slate-500">
          Research and education only. Not financial advice.
        </p>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex h-16 items-center gap-3 border-b border-line bg-surface/85 px-4 backdrop-blur sm:px-8">
          <button className="rounded-md p-2 text-muted hover:bg-slate-100 hover:text-ink lg:hidden" onClick={() => setOpen(true)} aria-label="Open menu">
            <Menu className="size-5" />
          </button>
          {current && (
            <nav aria-label="Breadcrumb" className="hidden min-w-0 items-center gap-2 text-sm sm:flex">
              <span className="text-muted">{current.group}</span>
              <span className="text-slate-300" aria-hidden>
                /
              </span>
              <span className="truncate font-medium text-ink">{current.label}</span>
            </nav>
          )}
          <div className="ml-auto">
            <UserMenu />
          </div>
        </header>

        <main className="flex-1 px-4 py-8 sm:px-8 sm:py-10">
          {/* key={pathname}: re-mount on navigation so every page fades in */}
          <div key={pathname} className="mx-auto max-w-7xl animate-fade-in-up motion-reduce:animate-none">
            {children}
          </div>
        </main>

        <footer className="border-t border-line px-4 py-5 text-center text-xs text-muted sm:px-8">
          For research and educational purposes only. Not financial advice.
        </footer>
      </div>
    </div>
  );
}
