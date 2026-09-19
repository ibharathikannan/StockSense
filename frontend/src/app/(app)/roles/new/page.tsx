"use client";

import { RequirePermission } from "@/components/RequirePermission";
import { RoleForm } from "@/components/RoleForm";
import { PageHeader } from "@/components/ui";

export default function NewRolePage() {
  return (
    <RequirePermission permission="roles:create">
      <PageHeader title="New role" />
      <RoleForm />
    </RequirePermission>
  );
}
