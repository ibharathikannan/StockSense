"use client";

import { ProfileForm } from "@/components/ProfileForm";
import { PageHeader } from "@/components/ui";
import { useProfile } from "@/lib/profile";

/** First visit = onboarding for a new user; afterwards the same page is where they update their profile whenever they like. */
export default function ProfilePage() {
  const { profile } = useProfile();
  return (
    <>
      <PageHeader
        title={profile ? "Profile" : "Welcome to StockSense"}
        description={
          profile
            ? "Your risk profile, interests and watchlist. Update them whenever your goals change."
            : "Help us personalise your experience. It takes a minute."
        }
      />
      <ProfileForm />
    </>
  );
}
