"use client";

import { use } from "react";
import { RequirePermission } from "@/components/RequirePermission";
import { UserForm } from "@/components/UserForm";
import { PageHeader } from "@/components/ui";

export default function EditUserPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return (
    <RequirePermission permission="users:update">
      <PageHeader title="Edit user" />
      <UserForm userId={id} />
    </RequirePermission>
  );
}
