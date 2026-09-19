"use client";

import { useEffect, useRef, useState } from "react";
import type { ApiError } from "@/lib/api";

/**
 * Run a service call and keep the result in state.
 *
 *   const users = useFetch(["users", page, q], () => usersService.list({ page, q }));
 *
 * `key` identifies the request: the call re-runs whenever it changes (put every
 * value the fetcher depends on in it). Pass `null` to skip the request. While a
 * new key/reload is in flight, `data` keeps showing the previous result (no
 * flicker when paging) and `loading` is true.
 */
export function useFetch<T>(key: readonly unknown[] | null, fetcher: () => Promise<T>) {
  const [nonce, setNonce] = useState(0);
  const requestKey = key ? `${nonce}:${JSON.stringify(key)}` : null;
  const [result, setResult] = useState<{ key: string; data?: T; error?: ApiError } | null>(null);

  // Always call the latest fetcher without making it an effect dependency.
  const fetcherRef = useRef(fetcher);
  useEffect(() => {
    fetcherRef.current = fetcher;
  });

  useEffect(() => {
    if (!requestKey) return;
    let cancelled = false;
    fetcherRef.current().then(
      (data) => !cancelled && setResult({ key: requestKey, data }),
      (error: ApiError) => !cancelled && setResult({ key: requestKey, error }),
    );
    return () => {
      cancelled = true;
    };
  }, [requestKey]);

  const settled = result?.key === requestKey ? result : null;
  return {
    data: result?.data,
    error: settled?.error,
    loading: requestKey !== null && !settled,
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
