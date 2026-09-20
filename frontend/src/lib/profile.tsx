"use client";

import { createContext, useContext, useEffect, useMemo, useState } from "react";
import type { Profile } from "@/lib/types";
import { profileService } from "@/services/profile";

interface ProfileState {
  /** `undefined` while loading, `null` when the user hasn't completed onboarding, otherwise their profile. */
  profile: Profile | null | undefined;
  /** True if the profile couldn't be loaded (network/server error). The gate then lets the user through. */
  failed: boolean;
  /** Store a freshly saved profile so the onboarding gate lets the user through immediately. */
  setProfile: (profile: Profile) => void;
}

const ProfileContext = createContext<ProfileState | null>(null);

/** Loads the signed-in user's investor profile once; the app layout uses it to send new users to onboarding. */
export function ProfileProvider({ children }: { children: React.ReactNode }) {
  const [profile, setProfile] = useState<Profile | null | undefined>(undefined);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    profileService
      .get()
      .then((p) => active && setProfile(p))
      .catch(() => active && setFailed(true));
    return () => {
      active = false;
    };
  }, []);

  const value = useMemo(() => ({ profile, failed, setProfile }), [profile, failed]);
  return <ProfileContext.Provider value={value}>{children}</ProfileContext.Provider>;
}

export function useProfile(): ProfileState {
  const ctx = useContext(ProfileContext);
  if (!ctx) throw new Error("useProfile must be used inside <ProfileProvider>");
  return ctx;
}
