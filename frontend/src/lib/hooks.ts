"use client";

import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";

/**
 * GET `path` and keep the result in state. Pass `null` to skip the request.
 * While a new path/reload is in flight, `data` keeps showing the previous
 * result (no flicker when paging) and `loading` is true.
 */
export function useFetch<T>(path: string | null) {
  const [nonce, setNonce] = useState(0);
  const key = path ? `${nonce}:${path}` : null;
  const [result, setResult] = useState<{ key: string; data?: T; error?: ApiError } | null>(null);

  useEffect(() => {
    if (!key || !path) return;
    let cancelled = false;
    api<T>(path).then(
      (data) => !cancelled && setResult({ key, data }),
      (error) => !cancelled && setResult({ key, error }),
    );
    return () => {
      cancelled = true;
    };
  }, [key, path]);

  const settled = result?.key === key ? result : null;
  return {
    data: result?.data,
    error: settled?.error,
    loading: key !== null && !settled,
    reload: () => setNonce((n) => n + 1),
  };
}

/** Returns `value` after it has stopped changing for `delayMs` (for search boxes). */
export function useDebounced<T>(value: T, delayMs = 300): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);
  return debounced;
}
