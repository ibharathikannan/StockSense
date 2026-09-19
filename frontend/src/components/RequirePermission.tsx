"use client";

import { ShieldAlert } from "lucide-react";
import { useAuth } from "@/lib/auth";

/**
 * Page-level authorization gate. Wrap a page's content so users without the
 * permission see "no access" instead of a screen full of 403 errors.
 * (This is UX only — the API enforces the permission regardless.)
 */
export function RequirePermission({ permission, children }: { permission: string; children: React.ReactNode }) {
  const { can } = useAuth();
  if (can(permission)) return <>{children}</>;
  return (
    <div className="mx-auto mt-16 max-w-md text-center">
      <ShieldAlert className="mx-auto size-10 text-muted" aria-hidden />
      <h1 className="mt-4 text-lg font-semibold">You don&apos;t have access to this page</h1>
      <p className="mt-1 text-sm text-muted">
        It requires the <code className="rounded bg-slate-100 px-1.5 py-0.5 text-xs">{permission}</code> permission. Ask an
        administrator to update your role.
      </p>
    </div>
  );
}
