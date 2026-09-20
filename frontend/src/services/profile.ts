import { api } from "@/lib/api";
import type { Profile, ProfileOptions } from "@/lib/types";

export interface ProfileInput {
  risk_level: string;
  interests: string[];
  asset_types: string;
  followed_tickers: string[];
}

/** The investor profile collected at onboarding (backend: app/api/routers/profile.py). */
export const profileService = {
  /** The caller's profile, or `null` if they haven't completed onboarding yet. */
  get: () => api<Profile | null>("/api/profile"),

  /** Creates the profile (completing onboarding) or replaces its answers. */
  save: (input: ProfileInput) => api<Profile>("/api/profile", { method: "PUT", body: input }),

  options: () => api<ProfileOptions>("/api/profile/options"),
};
