"use client";

import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Shell } from "@/components/Shell";
import { PageLoader } from "@/components/ui";
import { useAuth } from "@/lib/auth";

/** Everything under the (dashboard) route group requires a signed-in user. */
export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (loading || user) return;
    const params = new URLSearchParams({ reason: "expired" });
    if (pathname !== "/") params.set("next", pathname);
    router.replace(`/login?${params}`);
  }, [loading, user, pathname, router]);

  if (loading || !user) return <PageLoader />;
  return <Shell>{children}</Shell>;
}
