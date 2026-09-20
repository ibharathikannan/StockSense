"use client";

import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Shell } from "@/components/Shell";
import { PageLoader } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { ProfileProvider, useProfile } from "@/lib/profile";

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
  return (
    <ProfileProvider>
      <Shell>
        <OnboardingGate>{children}</OnboardingGate>
      </Shell>
    </ProfileProvider>
  );
}

/** Until a user has completed their profile (onboarding), every page redirects to /profile. */
function OnboardingGate({ children }: { children: React.ReactNode }) {
  const { profile, failed } = useProfile();
  const router = useRouter();
  const pathname = usePathname();
  const needsOnboarding = profile === null && pathname !== "/profile";

  useEffect(() => {
    if (needsOnboarding) router.replace("/profile");
  }, [needsOnboarding, router]);

  // While loading (or redirecting) show the loader. If loading failed, don't trap the user: show the app.
  if ((profile === undefined && !failed) || needsOnboarding) return <PageLoader />;
  return <>{children}</>;
}
