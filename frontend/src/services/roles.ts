import { api } from "@/lib/api";
import type { Page, Permission, Role, RoleOption } from "@/lib/types";

export interface ListRolesParams {
  page?: number;
  pageSize?: number;
}

export interface RoleCreateInput {
  name: string;
  description: string | null;
  permissions: string[];
}

export interface RoleUpdateInput {
  description?: string | null;
  permissions?: string[];
}

/** Everything the frontend asks the backend about roles (backend: app/api/routers/roles.py). */
export const rolesService = {
  list: ({ page = 1, pageSize = 10 }: ListRolesParams = {}) =>
    api<Page<Role>>(`/api/roles?page=${page}&page_size=${pageSize}`),

  get: (name: string) => api<Role>(`/api/roles/${encodeURIComponent(name)}`),

  create: (input: RoleCreateInput) => api<Role>("/api/roles", { method: "POST", body: input }),

  update: (name: string, input: RoleUpdateInput) =>
    api<Role>(`/api/roles/${encodeURIComponent(name)}`, { method: "PATCH", body: input }),

  remove: (name: string) => api(`/api/roles/${encodeURIComponent(name)}`, { method: "DELETE" }),

  /** The permission catalogue that drives the role editor's checkboxes. */
  permissions: () => api<Permission[]>("/api/roles/permissions"),

  /** Lightweight name list for the "assign role" dropdown on the user form. */
  options: () => api<RoleOption[]>("/api/roles/options"),
};
