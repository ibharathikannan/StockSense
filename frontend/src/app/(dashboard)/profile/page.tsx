"use client";

import { useState } from "react";
import { Alert, Badge, Button, Card, Field, Input, PageHeader } from "@/components/ui";
import { errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatDateTime } from "@/lib/format";
import { authService } from "@/services/auth";

export default function ProfilePage() {
  const { user } = useAuth();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [saving, setSaving] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setDone(false);
    if (next !== confirm) return setError("The new passwords don't match.");
    setSaving(true);
    try {
      await authService.changePassword(current, next);
      setCurrent("");
      setNext("");
      setConfirm("");
      setDone(true);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <PageHeader title="My profile" />
      <div className="grid gap-6 lg:grid-cols-2">
        <Card className="space-y-4 p-6">
          <h2 className="text-sm font-semibold">Account</h2>
          <dl className="grid grid-cols-[8rem_1fr] gap-y-3 text-sm">
            <dt className="text-muted">Name</dt>
            <dd>{user?.full_name}</dd>
            <dt className="text-muted">Email</dt>
            <dd>{user?.email}</dd>
            <dt className="text-muted">Role</dt>
            <dd>
              <Badge tone="brand">{user?.role}</Badge>
            </dd>
            <dt className="text-muted">Member since</dt>
            <dd>{formatDateTime(user?.created_at)}</dd>
            <dt className="text-muted">Last sign-in</dt>
            <dd>{formatDateTime(user?.last_login_at)}</dd>
          </dl>
        </Card>

        <Card className="p-6">
          <h2 className="mb-4 text-sm font-semibold">Change password</h2>
          <form onSubmit={onSubmit} className="space-y-4">
            {error && <Alert>{error}</Alert>}
            {done && <Alert tone="success">Password updated.</Alert>}
            <Field label="Current password" htmlFor="current">
              <Input id="current" type="password" autoComplete="current-password" required value={current} onChange={(e) => setCurrent(e.target.value)} />
            </Field>
            <Field label="New password" htmlFor="next" hint="At least 8 characters.">
              <Input id="next" type="password" autoComplete="new-password" required minLength={8} value={next} onChange={(e) => setNext(e.target.value)} />
            </Field>
            <Field label="Confirm new password" htmlFor="confirm">
              <Input id="confirm" type="password" autoComplete="new-password" required value={confirm} onChange={(e) => setConfirm(e.target.value)} />
            </Field>
            <Button type="submit" loading={saving}>
              Update password
            </Button>
          </form>
        </Card>
      </div>
    </>
  );
}
