"use client";

import Link from "next/link";
import { useState } from "react";
import { Pencil, Plus, Trash2 } from "lucide-react";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { Pagination } from "@/components/Pagination";
import { RequirePermission } from "@/components/RequirePermission";
import { Alert, Badge, Card, LinkButton, PageHeader, TableSkeleton, Table, Td, Th } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useFetch } from "@/lib/hooks";
import type { Page, Role } from "@/lib/types";

function RolesTable() {
  const { can } = useAuth();
  const [page, setPage] = useState(1);
  const { data, error, loading, reload } = useFetch<Page<Role>>(`/api/roles?page=${page}&page_size=10`);
  const [toDelete, setToDelete] = useState<Role | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  async function confirmDelete() {
    if (!toDelete) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      await api(`/api/roles/${toDelete.name}`, { method: "DELETE" });
      setToDelete(null);
      if (data && data.items.length === 1 && page > 1) setPage(page - 1);
      else reload();
    } catch (err) {
      setDeleteError(errorMessage(err)); // e.g. "N user(s) are assigned to it"
    } finally {
      setDeleting(false);
    }
  }

  return (
    <>
      <PageHeader
        title="Roles"
        description="A role is a named set of permissions. Assign roles to users to control what they can do."
        actions={
          can("roles:create") && (
            <LinkButton href="/roles/new">
              <Plus className="size-4" /> New role
            </LinkButton>
          )
        }
      />

      <Card>
        {error && (
          <div className="p-4">
            <Alert>{error.message}</Alert>
          </div>
        )}
        {!data && loading && <TableSkeleton />}
        {data && (
          <>
            <Table>
              <thead>
                <tr>
                  <Th>Role</Th>
                  <Th>Permissions</Th>
                  <Th>Users</Th>
                  <Th className="text-right">Actions</Th>
                </tr>
              </thead>
              <tbody className={loading ? "opacity-60" : undefined}>
                {data.items.map((r) => (
                  <tr key={r.name}>
                    <Td>
                      <div className="flex items-center gap-2">
                        <span className="font-medium">{r.name}</span>
                        {r.is_system && <Badge tone="amber">system</Badge>}
                      </div>
                      {r.description && <p className="text-xs text-muted">{r.description}</p>}
                    </Td>
                    <Td className="text-muted">{r.name === "admin" ? "All" : r.permissions.length}</Td>
                    <Td className="text-muted tabular-nums">{r.user_count}</Td>
                    <Td>
                      <div className="flex justify-end gap-1">
                        {can("roles:update") && (
                          <Link href={`/roles/${r.name}`} className="rounded-lg p-2 text-muted hover:bg-canvas hover:text-ink" aria-label={`Edit ${r.name}`}>
                            <Pencil className="size-4" />
                          </Link>
                        )}
                        {can("roles:delete") && !r.is_system && (
                          <button
                            className="rounded-lg p-2 text-muted hover:bg-red-50 hover:text-red-600"
                            aria-label={`Delete ${r.name}`}
                            onClick={() => {
                              setDeleteError(null);
                              setToDelete(r);
                            }}
                          >
                            <Trash2 className="size-4" />
                          </button>
                        )}
                      </div>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
            <Pagination page={data} onChange={setPage} />
          </>
        )}
      </Card>

      {toDelete && (
        <ConfirmDialog
          title="Delete role"
          message={
            <>
              Delete the <strong>{toDelete.name}</strong> role? Roles that still have users assigned can&apos;t be deleted.
            </>
          }
          busy={deleting}
          error={deleteError}
          onConfirm={() => void confirmDelete()}
          onCancel={() => setToDelete(null)}
        />
      )}
    </>
  );
}

export default function RolesPage() {
  return (
    <RequirePermission permission="roles:read">
      <RolesTable />
    </RequirePermission>
  );
}
