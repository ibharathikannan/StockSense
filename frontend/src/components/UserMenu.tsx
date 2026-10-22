"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { ChevronDown, LogOut, Settings, UserCircle } from "lucide-react";
import { Avatar } from "@/components/ui";
import { useAuth } from "@/lib/auth";

const itemClass =
  "flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-left text-sm text-ink transition-colors hover:bg-slate-100 focus-visible:bg-slate-100";

/** Top-bar account menu: who is signed in, shortcuts to profile and settings, and sign out. */
export function UserMenu() {
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onPointer = (e: PointerEvent) => {
      if (!root.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("pointerdown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (!user) return null;

  return (
    <div ref={root} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        className="flex items-center gap-2.5 rounded-full py-1 pr-2 pl-1 transition-colors hover:bg-slate-100 sm:pr-3"
      >
        <Avatar name={user.full_name} />
        <span className="hidden text-left sm:block">
          <span className="block text-sm leading-tight font-medium">{user.full_name}</span>
          <span className="block text-xs leading-tight text-muted capitalize">{user.role}</span>
        </span>
        <ChevronDown className={`size-4 text-muted transition-transform ${open ? "rotate-180" : ""}`} aria-hidden />
      </button>

      {open && (
        <div
          role="menu"
          aria-label="Account"
          className="absolute right-0 z-50 mt-2 w-64 animate-pop-in rounded-xl border border-line bg-surface p-1.5 shadow-pop motion-reduce:animate-none"
        >
          <div className="flex items-center gap-3 px-2.5 py-2.5">
            <Avatar name={user.full_name} size="lg" />
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold">{user.full_name}</p>
              <p className="truncate text-xs text-muted">{user.email}</p>
            </div>
          </div>
          <div className="my-1 h-px bg-line" role="separator" />
          <Link href="/profile" role="menuitem" onClick={() => setOpen(false)} className={itemClass}>
            <UserCircle className="size-4 text-muted" aria-hidden /> Profile
          </Link>
          <Link href="/account" role="menuitem" onClick={() => setOpen(false)} className={itemClass}>
            <Settings className="size-4 text-muted" aria-hidden /> Account settings
          </Link>
          <div className="my-1 h-px bg-line" role="separator" />
          <button type="button" role="menuitem" onClick={() => void logout()} className={itemClass}>
            <LogOut className="size-4 text-muted" aria-hidden /> Sign out
          </button>
        </div>
      )}
    </div>
  );
}
