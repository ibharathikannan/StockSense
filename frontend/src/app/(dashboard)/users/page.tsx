"use client";

import Link from "next/link";
import { useState } from "react";
import { Pencil, Plus, Search, Trash2 } from "lucide-react";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { Pagination } from "@/components/Pagination";
import { RequirePermission } from "@/components/RequirePermission";
import { Alert, Badge, Card, Input, LinkButton, PageHeader, TableSkeleton, Table, Td, Th } from "@/components/ui";
import { errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatDateTime } from "@/lib/format";
import { useDebounced, useFetch } from "@/lib/hooks";
import type { User } from "@/lib/types";
import { usersService } from "@/services/users";

function UsersTable() {
  const { user: me, can } = useAuth();
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const q = useDebounced(search.trim());

  const { data, error, loading, reload } = useFetch(["users", page, q], () => usersService.list({ page, q }));
  const [toDelete, setToDelete] = useState<User | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  async function confirmDelete() {
    if (!toDelete) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      await usersService.remove(toDelete.id);
      setToDelete(null);
      // Deleting the last row of the last page would leave an empty page.
      if (data && data.items.length === 1 && page > 1) setPage(page - 1);
      else reload();
    } catch (err) {
      setDeleteError(errorMessage(err));
    } finally {
      setDeleting(false);
    }
  }

  return (
    <>
      <PageHeader
        title="Users"
        description="Manage who can sign in and what they can do."
        actions={
          can("users:create") && (
            <LinkButton href="/users/new">
              <Plus className="size-4" /> New user
            </LinkButton>
          )
        }
      />

      <Card>
        <div className="border-b border-line p-4">
          <div className="relative max-w-sm">
            <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted" aria-hidden />
            <Input
              className="pl-9"
              placeholder="Search by name or email"
              aria-label="Search users"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setPage(1);
              }}
            />
          </div>
        </div>

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
                  <Th>User</Th>
                  <Th>Role</Th>
                  <Th>Status</Th>
                  <Th>Last sign-in</Th>
                  <Th className="text-right">Actions</Th>
                </tr>
              </thead>
              <tbody className={loading ? "opacity-60" : undefined}>
                {data.items.map((u) => (
                  <tr key={u.id}>
                    <Td>
                      <p className="font-medium">{u.full_name}</p>
                      <p className="text-xs text-muted">{u.email}</p>
                    </Td>
                    <Td>
                      <Badge tone={u.role === "admin" ? "brand" : "neutral"}>{u.role}</Badge>
                    </Td>
                    <Td>
                      <Badge tone={u.is_active ? "green" : "red"}>{u.is_active ? "Active" : "Disabled"}</Badge>
                    </Td>
                    <Td className="text-muted">{formatDateTime(u.last_login_at)}</Td>
                    <Td>
                      <div className="flex justify-end gap-1">
                        {can("users:update") && (
                          <Link href={`/users/${u.id}`} className="rounded-lg p-2 text-muted hover:bg-canvas hover:text-ink" aria-label={`Edit ${u.full_name}`}>
                            <Pencil className="size-4" />
                          </Link>
                        )}
                        {can("users:delete") && u.id !== me?.id && (
                          <button
                            className="rounded-lg p-2 text-muted hover:bg-red-50 hover:text-red-600"
                            aria-label={`Delete ${u.full_name}`}
                            onClick={() => {
                              setDeleteError(null);
                              setToDelete(u);
                            }}
                          >
                            <Trash2 className="size-4" />
                          </button>
                        )}
                      </div>
                    </Td>
                  </tr>
                ))}
                {data.items.length === 0 && (
                  <tr>
                    <Td colSpan={5} className="py-10 text-center text-muted">
                      No users found.
                    </Td>
                  </tr>
                )}
              </tbody>
            </Table>
            <Pagination page={data} onChange={setPage} />
          </>
        )}
      </Card>

      {toDelete && (
        <ConfirmDialog
          title="Delete user"
          message={
            <>
              Permanently delete <strong>{toDelete.full_name}</strong> ({toDelete.email})? This can&apos;t be undone.
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

export default function UsersPage() {
  return (
    <RequirePermission permission="users:read">
      <UsersTable />
    </RequirePermission>
  );
}
