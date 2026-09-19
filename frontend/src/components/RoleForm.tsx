"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Alert, Button, Card, Field, Input, LinkButton, PageLoader } from "@/components/ui";
import { errorMessage } from "@/lib/api";
import { useFetch } from "@/lib/hooks";
import type { Permission, Role } from "@/lib/types";
import { rolesService } from "@/services/roles";

/** Create (no `roleName`) or edit a role. Permission checkboxes come from the backend catalogue. */
export function RoleForm({ roleName }: { roleName?: string }) {
  const role = useFetch(roleName ? ["role", roleName] : null, () => rolesService.get(roleName!));
  const catalogue = useFetch(["permissions"], () => rolesService.permissions());

  const error = role.error ?? catalogue.error;
  if (error) return <Alert>{error.status === 404 ? "Role not found." : error.message}</Alert>;
  if (!catalogue.data || (roleName && !role.data)) return <PageLoader />;
  return <Form existing={role.data} catalogue={catalogue.data} />;
}

function Form({ existing, catalogue }: { existing?: Role; catalogue: Permission[] }) {
  const router = useRouter();
  const editing = !!existing;
  const locked = existing?.name === "admin"; // admin always has every permission

  const [name, setName] = useState(existing?.name ?? "");
  const [description, setDescription] = useState(existing?.description ?? "");
  const [selected, setSelected] = useState<Set<string>>(new Set(existing?.permissions ?? []));
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const groups = Object.entries(
    catalogue.reduce<Record<string, Permission[]>>((acc, p) => {
      (acc[p.group] ??= []).push(p);
      return acc;
    }, {}),
  );

  function toggle(key: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (!next.delete(key)) next.add(key);
      return next;
    });
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSaving(true);
    try {
      if (editing) {
        await rolesService.update(existing.name, {
          description: description || null,
          ...(locked ? {} : { permissions: [...selected] }),
        });
      } else {
        await rolesService.create({ name, description: description || null, permissions: [...selected] });
      }
      router.push("/roles");
    } catch (err) {
      setError(errorMessage(err));
      setSaving(false);
    }
  }

  return (
    <Card className="max-w-2xl p-6">
      <form onSubmit={onSubmit} className="space-y-5">
        {error && <Alert>{error}</Alert>}
        {locked && <Alert tone="info">The admin role always has every permission, so only its description can be edited.</Alert>}

        <Field
          label="Name"
          htmlFor="name"
          hint={editing ? "The name can't be changed." : "Lowercase key, 2–30 characters: a–z, 0–9, _ and -"}
        >
          <Input
            id="name"
            required
            disabled={editing}
            pattern="^[a-z][a-z0-9_\-]{1,29}$"
            title="Lowercase letters, digits, _ or -; start with a letter; 2–30 characters"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </Field>

        <Field label="Description" htmlFor="description">
          <Input id="description" maxLength={300} value={description} onChange={(e) => setDescription(e.target.value)} />
        </Field>

        <fieldset className="space-y-3">
          <legend className="text-sm font-medium">Permissions</legend>
          <div className="grid gap-4 sm:grid-cols-2">
            {groups.map(([group, perms]) => (
              <div key={group} className="rounded-lg border border-line p-4">
                <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">{group}</p>
                <div className="space-y-2">
                  {perms.map((p) => (
                    <label key={p.key} className="flex items-start gap-2 text-sm">
                      <input
                        type="checkbox"
                        className="mt-0.5 size-4 accent-brand-500"
                        checked={locked || selected.has(p.key)}
                        disabled={locked}
                        onChange={() => toggle(p.key)}
                      />
                      <span>
                        {p.description}
                        <span className="block text-xs text-muted">{p.key}</span>
                      </span>
                    </label>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </fieldset>

        <div className="flex gap-2 pt-2">
          <Button type="submit" loading={saving}>
            {editing ? "Save changes" : "Create role"}
          </Button>
          <LinkButton href="/roles" variant="secondary">
            Cancel
          </LinkButton>
        </div>
      </form>
    </Card>
  );
}
