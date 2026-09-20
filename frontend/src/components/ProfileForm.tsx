"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Check, Info, Plus } from "lucide-react";
import { TickerPicker } from "@/components/TickerPicker";
import { Alert, Button, Card, PageLoader } from "@/components/ui";
import { errorMessage } from "@/lib/api";
import { useFetch } from "@/lib/hooks";
import { useProfile } from "@/lib/profile";
import type { Profile, ProfileOptions } from "@/lib/types";
import { profileService } from "@/services/profile";

/**
 * The investor-profile form, used for first-time onboarding and for updating it later:
 * risk profile, interests, preferred asset type, and tickers to follow.
 */
export function ProfileForm() {
  const { profile } = useProfile();
  const options = useFetch(["profile-options"], () => profileService.options());

  if (options.error) return <Alert>{options.error.message}</Alert>;
  if (!options.data) return <PageLoader />;
  return <Form options={options.data} existing={profile ?? null} />;
}

function Form({ options, existing }: { options: ProfileOptions; existing: Profile | null }) {
  const router = useRouter();
  const { setProfile } = useProfile();

  const [risk, setRisk] = useState(existing?.risk_level ?? "");
  const [interests, setInterests] = useState<string[]>(existing?.interests ?? []);
  const [assetTypes, setAssetTypes] = useState(existing?.asset_types ?? "both");
  const [tickers, setTickers] = useState<string[]>(existing?.followed_tickers ?? []);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [justSaved, setJustSaved] = useState(false);

  // Does the form still match what is stored? (drives the disabled Save button and the confirmation)
  const sameAsSaved =
    !!existing &&
    existing.risk_level === risk &&
    existing.asset_types === assetTypes &&
    [...existing.interests].sort().join() === [...interests].sort().join() &&
    existing.followed_tickers.join() === tickers.join();

  function toggleInterest(key: string) {
    setInterests((prev) => (prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]));
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!risk) return setError("Choose the risk profile that fits you best.");
    if (interests.length === 0) return setError("Pick at least one topic you are interested in.");

    setSaving(true);
    try {
      const firstTime = !existing;
      const saved = await profileService.save({ risk_level: risk, interests, asset_types: assetTypes, followed_tickers: tickers });
      setProfile(saved); // lets the onboarding gate through right away
      if (firstTime) {
        router.replace("/"); // finished onboarding
      } else {
        setJustSaved(true); // updating later: stay here and confirm
        setSaving(false);
      }
    } catch (err) {
      setError(errorMessage(err));
      setSaving(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="space-y-6">
      {error && <Alert>{error}</Alert>}

      <div className="grid gap-6 lg:grid-cols-2">
        {/* ---- Risk profile ---- */}
        <Card className="p-6">
          <fieldset>
            <legend className="text-base font-semibold">What is your risk profile?</legend>
            <p className="mt-1 mb-4 text-sm text-muted">Your choice helps us tailor insights and suggestions.</p>
            <div className="space-y-2.5">
              {options.risk_levels.map((r) => {
                const selected = risk === r.key;
                return (
                  <label
                    key={r.key}
                    className={`flex cursor-pointer items-start gap-3 rounded-lg border p-3.5 transition-colors has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-brand-500 ${
                      selected ? "border-brand-500 bg-brand-50" : "border-line hover:bg-canvas"
                    }`}
                  >
                    <input type="radio" name="risk" value={r.key} checked={selected} onChange={() => setRisk(r.key)} className="sr-only" />
                    <span
                      className={`mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-full border ${
                        selected ? "border-brand-500 bg-brand-500" : "border-slate-300"
                      }`}
                      aria-hidden
                    >
                      {selected && <span className="size-1.5 rounded-full bg-white" />}
                    </span>
                    <span>
                      <span className="block text-sm font-semibold">{r.label}</span>
                      <span className="block text-xs text-muted">{r.description}</span>
                    </span>
                  </label>
                );
              })}
            </div>
            <p className="mt-4 flex items-center gap-2 rounded-lg bg-canvas px-3 py-2.5 text-xs text-muted">
              <Info className="size-4 shrink-0" aria-hidden />
              You can update this anytime in your profile settings.
            </p>
          </fieldset>
        </Card>

        {/* ---- Interests, asset type, watchlist ---- */}
        <Card className="space-y-7 p-6">
          <fieldset>
            <legend className="text-base font-semibold">What are you interested in?</legend>
            <p className="mt-1 mb-4 text-sm text-muted">Select topics you&apos;d like to see more of.</p>
            <div className="grid grid-cols-[repeat(auto-fill,minmax(9.5rem,1fr))] gap-2.5">
              {options.interests.map((i) => {
                const selected = interests.includes(i.key);
                return (
                  <button
                    key={i.key}
                    type="button"
                    aria-pressed={selected}
                    onClick={() => toggleInterest(i.key)}
                    className={`flex items-center justify-between gap-2 rounded-lg border px-3.5 py-2.5 text-left text-sm font-medium transition-colors ${
                      selected ? "border-brand-500 bg-brand-50 text-brand-700" : "border-line hover:bg-canvas"
                    }`}
                  >
                    <span>
                      {i.label}
                      <span className="ml-1.5 text-xs font-normal text-muted">{i.asset_count}</span>
                    </span>
                    {selected ? <Check className="size-4 shrink-0" aria-hidden /> : <Plus className="size-4 shrink-0 text-muted" aria-hidden />}
                  </button>
                );
              })}
            </div>
          </fieldset>

          <fieldset>
            <legend className="text-sm font-semibold">Which would you like to explore?</legend>
            <div className="mt-2.5 inline-flex rounded-lg border border-line p-0.5" role="radiogroup">
              {options.asset_types.map((a) => {
                const selected = assetTypes === a.key;
                return (
                  <label
                    key={a.key}
                    className={`cursor-pointer rounded-md px-3.5 py-1.5 text-sm font-medium transition-colors has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-brand-500 ${
                      selected ? "bg-brand-500 text-white" : "text-muted hover:text-ink"
                    }`}
                  >
                    <input type="radio" name="asset_types" value={a.key} checked={selected} onChange={() => setAssetTypes(a.key)} className="sr-only" />
                    {a.label}
                  </label>
                );
              })}
            </div>
          </fieldset>

          <div>
            <h2 className="text-sm font-semibold">Add tickers you want to follow (optional)</h2>
            <p className="mt-1 mb-3 text-sm text-muted">We&apos;ll keep an eye on these for you.</p>
            <TickerPicker value={tickers} onChange={setTickers} max={options.max_followed} />
          </div>
        </Card>
      </div>

      <div className="flex items-center justify-end gap-4">
        {justSaved && sameAsSaved && (
          <p role="status" className="flex items-center gap-1.5 text-sm font-medium text-emerald-700">
            <Check className="size-4" aria-hidden /> Profile saved
          </p>
        )}
        <Button type="submit" loading={saving} disabled={sameAsSaved} className="min-w-40">
          {existing ? "Save changes" : "Continue"}
        </Button>
      </div>
    </form>
  );
}
