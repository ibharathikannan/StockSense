"use client";

import { use } from "react";
import { RequirePermission } from "@/components/RequirePermission";
import { RoleForm } from "@/components/RoleForm";
import { PageHeader } from "@/components/ui";

export default function EditRolePage({ params }: { params: Promise<{ name: string }> }) {
  const { name } = use(params);
  return (
    <RequirePermission permission="roles:update">
      <PageHeader title={`Edit role: ${name}`} />
      <RoleForm roleName={name} />
    </RequirePermission>
  );
}
