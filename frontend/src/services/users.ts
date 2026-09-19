import { api } from "@/lib/api";
import type { Page, User } from "@/lib/types";

export interface ListUsersParams {
  page?: number;
  pageSize?: number;
  /** Search text (matches name or email). */
  q?: string;
}

export interface UserCreateInput {
  full_name: string;
  email: string;
  password: string;
  role: string;
  is_active: boolean;
}

/** Only the fields you send are changed. */
export interface UserUpdateInput {
  full_name?: string;
  role?: string;
  is_active?: boolean;
  /** Admin-initiated password reset. */
  password?: string;
}

/** Everything the frontend asks the backend about users (backend: app/api/routers/users.py). */
export const usersService = {
  list: ({ page = 1, pageSize = 10, q }: ListUsersParams = {}) => {
    const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
    if (q) params.set("q", q);
    return api<Page<User>>(`/api/users?${params}`);
  },

  get: (id: string) => api<User>(`/api/users/${encodeURIComponent(id)}`),

  create: (input: UserCreateInput) => api<User>("/api/users", { method: "POST", body: input }),

  update: (id: string, input: UserUpdateInput) =>
    api<User>(`/api/users/${encodeURIComponent(id)}`, { method: "PATCH", body: input }),

  remove: (id: string) => api(`/api/users/${encodeURIComponent(id)}`, { method: "DELETE" }),
};
