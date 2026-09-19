// Thin fetch wrapper for the FastAPI backend.
//
// Requests go to same-origin /api/* (proxied by next.config.ts), so the browser
// attaches the httpOnly session cookie automatically — no token handling here.

import { beginActivity, endActivity } from "@/lib/activity";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

type UnauthorizedListener = () => void;
let unauthorizedListener: UnauthorizedListener | null = null;

/** AuthProvider registers here so an expired session anywhere logs the user out. */
export function onUnauthorized(listener: UnauthorizedListener | null) {
  unauthorizedListener = listener;
}

// FastAPI returns {"detail": "text"} or, for validation errors,
// {"detail": [{"loc": [...], "msg": "..."}]}.
function messageFrom(body: unknown, fallback: string): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d) => {
        const field = Array.isArray(d.loc) ? d.loc.filter((p: unknown) => p !== "body").join(".") : "";
        const msg = String(d.msg ?? "").replace(/^Value error, /, "");
        return field ? `${field}: ${msg}` : msg;
      })
      .join("; ");
  }
  return fallback;
}

interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  body?: unknown;
  /** Endpoints where a 401 is an expected answer (login, initial /me) — don't trigger global logout. */
  expectUnauthorized?: boolean;
  signal?: AbortSignal;
}

export async function api<T = void>(path: string, opts: RequestOptions = {}): Promise<T> {
  beginActivity(); // drives the global top progress bar
  try {
    return await request<T>(path, opts);
  } finally {
    endActivity();
  }
}

async function request<T>(path: string, opts: RequestOptions): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      method: opts.method ?? "GET",
      headers: opts.body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
      signal: opts.signal,
    });
  } catch (err) {
    if ((err as Error).name === "AbortError") throw err;
    throw new ApiError(0, "Can't reach the server. Is the backend running?");
  }

  if (res.status === 204) return undefined as T;

  const body = await res.json().catch(() => null);
  if (!res.ok) {
    if (res.status === 401 && !opts.expectUnauthorized) unauthorizedListener?.();
    throw new ApiError(res.status, messageFrom(body, `Request failed (${res.status})`));
  }
  return body as T;
}

export function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : "Something went wrong";
}
