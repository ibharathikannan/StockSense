import { api } from "@/lib/api";
import type { CurrentUser, LoginResponse } from "@/lib/types";

/** Everything the frontend asks the backend about authentication (backend: app/api/routers/auth.py). */
export const authService = {
  // 401 is an expected answer for login (wrong password) and me (signed out), so it must not trigger the global sign-out.
  login: (email: string, password: string) =>
    api<LoginResponse>("/api/auth/login", { method: "POST", body: { email, password }, expectUnauthorized: true }),

  me: () => api<CurrentUser>("/api/auth/me", { expectUnauthorized: true }),

  logout: () => api("/api/auth/logout", { method: "POST", expectUnauthorized: true }),

  changePassword: (currentPassword: string, newPassword: string) =>
    api("/api/auth/change-password", {
      method: "POST",
      body: { current_password: currentPassword, new_password: newPassword },
    }),
};
