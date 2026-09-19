"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { onUnauthorized } from "@/lib/api";
import type { CurrentUser } from "@/lib/types";
import { authService } from "@/services/auth";

interface AuthState {
  user: CurrentUser | null;
  /** True until the first GET /api/auth/me has answered. */
  loading: boolean;
  login: (email: string, password: string) => Promise<CurrentUser>;
  /** Create a normal-user account and sign in as it. */
  register: (fullName: string, email: string, password: string) => Promise<CurrentUser>;
  logout: () => Promise<void>;
  /** Re-read the current user (e.g. after editing your own profile). */
  refresh: () => Promise<void>;
  /** Authorization check for UI (hiding buttons/menu items). The API enforces it for real. */
  can: (permission: string) => boolean;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      setUser(await authService.me());
    } catch {
      setUser(null);
    }
  }, []);

  // Who am I? (the browser sends the session cookie; 401 just means "signed out")
  useEffect(() => {
    let active = true;
    authService
      .me()
      .then((me) => active && setUser(me))
      .catch(() => {})
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, []);

  // Any API call that comes back 401 (expired/revoked session) signs the user out.
  useEffect(() => {
    onUnauthorized(() => setUser(null));
    return () => onUnauthorized(null);
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const res = await authService.login(email, password);
    setUser(res.user);
    return res.user;
  }, []);

  const register = useCallback(async (fullName: string, email: string, password: string) => {
    const res = await authService.register(fullName, email, password);
    setUser(res.user);
    return res.user;
  }, []);

  const logout = useCallback(async () => {
    try {
      await authService.logout();
    } finally {
      // Hard navigation: drops all in-memory state and can't race the
      // "session expired" redirect in the app layout.
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination -- deliberate full reload
      window.location.href = "/login";
    }
  }, []);

  const value = useMemo<AuthState>(
    () => ({
      user,
      loading,
      login,
      register,
      logout,
      refresh,
      can: (permission) => !!user?.permissions.includes(permission),
    }),
    [user, loading, login, register, logout, refresh],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
