"use client";

import Link from "next/link";
import { Card, Badge, PageHeader } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { useFetch } from "@/lib/hooks";
import { rolesService } from "@/services/roles";
import { usersService } from "@/services/users";

function Stat({ label, value, href }: { label: string; value: number | undefined; href: string }) {
  return (
    <Link href={href}>
      <Card className="p-5 transition-shadow hover:shadow-md">
        <p className="text-sm text-muted">{label}</p>
        <p className="mt-2 text-3xl font-semibold tabular-nums">{value ?? "…"}</p>
      </Card>
    </Link>
  );
}

export default function DashboardPage() {
  const { user, can } = useAuth();
  // Only ask for what this user is allowed to see.
  const users = useFetch(can("users:read") ? ["users", "count"] : null, () => usersService.list({ pageSize: 1 }));
  const roles = useFetch(can("roles:read") ? ["roles", "count"] : null, () => rolesService.list({ pageSize: 1 }));

  return (
    <>
      <PageHeader title={`Welcome back, ${user?.full_name.split(" ")[0]}`} description="Here's an overview of your workspace." />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {can("users:read") && <Stat label="Users" value={users.data?.total} href="/users" />}
        {can("roles:read") && <Stat label="Roles" value={roles.data?.total} href="/roles" />}
        <Card className="p-5">
          <p className="text-sm text-muted">Your role</p>
          <p className="mt-2 text-3xl font-semibold">{user?.role}</p>
        </Card>
      </div>

      <Card className="mt-6 p-5">
        <h2 className="text-sm font-semibold">Your permissions</h2>
        <div className="mt-3 flex flex-wrap gap-2">
          {user?.permissions.length ? (
            user.permissions.map((p) => (
              <Badge key={p} tone="brand">
                {p}
              </Badge>
            ))
          ) : (
            <p className="text-sm text-muted">Your role doesn&apos;t grant any admin permissions.</p>
          )}
        </div>
      </Card>
    </>
  );
}
