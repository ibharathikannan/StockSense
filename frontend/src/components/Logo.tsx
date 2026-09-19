import { TrendingUp } from "lucide-react";
import { APP_NAME } from "@/lib/config";

/** Brand mark: an up-trend icon in a rounded tile + the app name. */
export function Logo({ className = "" }: { className?: string }) {
  return (
    <span className={`inline-flex items-center gap-2.5 ${className}`}>
      <span className="flex size-8 items-center justify-center rounded-lg bg-brand-500 text-white">
        <TrendingUp className="size-[18px]" strokeWidth={2.5} aria-hidden />
      </span>
      <span className="text-lg font-semibold tracking-tight">{APP_NAME}</span>
    </span>
  );
}
