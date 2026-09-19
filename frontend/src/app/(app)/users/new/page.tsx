"use client";

import { RequirePermission } from "@/components/RequirePermission";
import { UserForm } from "@/components/UserForm";
import { PageHeader } from "@/components/ui";

export default function NewUserPage() {
  return (
    <RequirePermission permission="users:create">
      <PageHeader title="New user" />
      <UserForm />
    </RequirePermission>
  );
}
