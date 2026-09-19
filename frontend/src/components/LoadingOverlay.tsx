"use client";

import { useEffect, useState, useSyncExternalStore } from "react";
import { getPendingCount, subscribeActivity } from "@/lib/activity";

const SHOW_AFTER_MS = 200; // near-instant responses never show the overlay (no flicker)
const HIDE_AFTER_MS = 200; // bridge chained requests so it doesn't blink off and on

/**
 * The app's single loading indicator: while any API request (or a <PageLoader>)
 * is pending, the page behind blurs softly and a circle loader appears in the middle.
 * It also blocks clicks, which prevents double submits on slow connections.
 */
export function LoadingOverlay() {
  const pending = useSyncExternalStore(subscribeActivity, getPendingCount, () => 0);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => setVisible(pending > 0), pending > 0 ? SHOW_AFTER_MS : HIDE_AFTER_MS);
    return () => clearTimeout(timer);
  }, [pending]);

  if (!visible) return null;
  return (
    <div
      role="status"
      aria-live="polite"
      aria-label="Loading"
      className="fixed inset-0 z-[100] flex animate-fade-in items-center justify-center bg-white/40 backdrop-blur-sm motion-reduce:animate-none"
    >
      <div className="rounded-2xl bg-surface/90 p-5 shadow-xl ring-1 ring-line">
        <span className="block size-10 animate-spin rounded-full border-4 border-brand-100 border-t-brand-500 motion-reduce:animate-pulse" />
      </div>
    </div>
  );
}
