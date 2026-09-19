"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Alert, Button, Card, Field, Input, LinkButton, PageLoader, Select } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useFetch } from "@/lib/hooks";
import type { RoleOption, User } from "@/lib/types";

/**
 * Create (no `userId`) or edit (`userId`) a user — one form for both, like
 * RoleForm. Loads what it needs, then hands off to <Form> so the inputs can
 * be initialised straight from the loaded user.
 */
export function UserForm({ userId }: { userId?: string }) {
  const user = useFetch<User>(userId ? `/api/users/${userId}` : null);
  const roles = useFetch<RoleOption[]>("/api/roles/options");

  const error = user.error ?? roles.error;
  if (error) return <Alert>{error.status === 404 ? "User not found." : error.message}</Alert>;
  if (!roles.data || (userId && !user.data)) return <PageLoader />;
  return <Form existing={user.data} roles={roles.data} />;
}

function Form({ existing, roles }: { existing?: User; roles: RoleOption[] }) {
  const router = useRouter();
  const { user: me, refresh } = useAuth();
  const editing = !!existing;
  const isSelf = editing && existing.id === me?.id;

  const [fullName, setFullName] = useState(existing?.full_name ?? "");
  const [email, setEmail] = useState(existing?.email ?? "");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState(existing?.role ?? "user");
  const [isActive, setIsActive] = useState(existing?.is_active ?? true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSaving(true);
    try {
      if (editing) {
        await api(`/api/users/${existing.id}`, {
          method: "PATCH",
          body: {
            full_name: fullName,
            // The API rejects self role/status changes, so don't send them.
            ...(isSelf ? {} : { role, is_active: isActive }),
            ...(password ? { password } : {}),
          },
        });
        if (isSelf) await refresh(); // header shows your own name
      } else {
        await api("/api/users", { method: "POST", body: { full_name: fullName, email, password, role, is_active: isActive } });
      }
      router.push("/users");
    } catch (err) {
      setError(errorMessage(err));
      setSaving(false);
    }
  }

  return (
    <Card className="max-w-xl p-6">
      <form onSubmit={onSubmit} className="space-y-5">
        {error && <Alert>{error}</Alert>}

        <Field label="Full name" htmlFor="full_name">
          <Input id="full_name" required maxLength={100} value={fullName} onChange={(e) => setFullName(e.target.value)} />
        </Field>

        <Field label="Email" htmlFor="email" hint={editing ? "Email can't be changed." : undefined}>
          <Input id="email" type="email" required disabled={editing} value={email} onChange={(e) => setEmail(e.target.value)} />
        </Field>

        <Field
          label={editing ? "Reset password" : "Password"}
          htmlFor="password"
          hint={editing ? "Leave blank to keep the current password." : "At least 8 characters."}
        >
          <Input
            id="password"
            type="password"
            autoComplete="new-password"
            required={!editing}
            minLength={8}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </Field>

        <Field label="Role" htmlFor="role" hint={isSelf ? "You can't change your own role." : undefined}>
          <Select id="role" value={role} disabled={isSelf} onChange={(e) => setRole(e.target.value)}>
            {roles.map((r) => (
              <option key={r.name} value={r.name}>
                {r.name}
                {r.description ? ` — ${r.description}` : ""}
              </option>
            ))}
          </Select>
        </Field>

        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            className="size-4 accent-brand-500"
            checked={isActive}
            disabled={isSelf}
            onChange={(e) => setIsActive(e.target.checked)}
          />
          Active (can sign in)
          {isSelf && <span className="text-xs text-muted">— you can&apos;t deactivate yourself</span>}
        </label>

        <div className="flex gap-2 pt-2">
          <Button type="submit" loading={saving}>
            {editing ? "Save changes" : "Create user"}
          </Button>
          <LinkButton href="/users" variant="secondary">
            Cancel
          </LinkButton>
        </div>
      </form>
    </Card>
  );
}
