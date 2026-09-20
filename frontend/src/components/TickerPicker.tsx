"use client";

import { useState } from "react";
import { Plus, X } from "lucide-react";
import { Input } from "@/components/ui";
import { useDebounced, useFetch } from "@/lib/hooks";
import { assetsService } from "@/services/assets";

/** Pick tickers to follow: type a ticker or company name, choose from the matches, remove chips with ×. */
export function TickerPicker({
  value,
  onChange,
  max,
}: {
  value: string[];
  onChange: (tickers: string[]) => void;
  max: number;
}) {
  const [query, setQuery] = useState("");
  const [focused, setFocused] = useState(false);
  const typed = query.trim();
  const debounced = useDebounced(typed, 200);

  const results = useFetch(debounced ? ["asset-search", debounced] : null, () => assetsService.search(debounced));
  const options = (results.data ?? []).filter((a) => !value.includes(a.ticker));
  const atLimit = value.length >= max;
  const settled = debounced === typed && !results.loading;

  function add(ticker: string) {
    if (atLimit || value.includes(ticker)) return;
    onChange([...value, ticker]);
    setQuery("");
  }

  return (
    <div className="space-y-3">
      {value.length > 0 && (
        <ul className="flex flex-wrap gap-2" aria-label="Followed tickers">
          {value.map((ticker) => (
            <li
              key={ticker}
              className="inline-flex items-center gap-1 rounded-md border border-brand-100 bg-brand-50 py-1 pr-1 pl-2.5 text-sm font-medium text-brand-700"
            >
              {ticker}
              <button
                type="button"
                onClick={() => onChange(value.filter((t) => t !== ticker))}
                className="rounded p-0.5 hover:bg-brand-100"
                aria-label={`Stop following ${ticker}`}
              >
                <X className="size-3.5" />
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className="relative">
        <Plus className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted" aria-hidden />
        <Input
          className="pl-9"
          placeholder={atLimit ? `You can follow up to ${max} tickers` : "Add a ticker or company, e.g. NVDA"}
          aria-label="Add a ticker to follow"
          autoComplete="off"
          disabled={atLimit}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault(); // don't submit the form
              if (options[0]) add(options[0].ticker);
            }
          }}
        />

        {focused && typed && (options.length > 0 || settled) && (
          <ul className="absolute z-10 mt-1 max-h-64 w-full overflow-auto rounded-lg border border-line bg-surface py-1 shadow-lg" role="listbox">
            {options.map((a) => (
              <li key={a.ticker} role="option" aria-selected={false}>
                {/* onMouseDown (not onClick) so the input keeps focus and the list doesn't close first */}
                <button
                  type="button"
                  onMouseDown={(e) => {
                    e.preventDefault();
                    add(a.ticker);
                  }}
                  className="flex w-full items-center gap-3 px-3 py-2 text-left text-sm hover:bg-canvas"
                >
                  <span className="w-14 shrink-0 font-semibold">{a.ticker}</span>
                  <span className="min-w-0 flex-1 truncate text-muted">{a.name}</span>
                  <span className="shrink-0 text-xs text-muted uppercase">{a.asset_type}</span>
                </button>
              </li>
            ))}
            {options.length === 0 && <li className="px-3 py-2 text-sm text-muted">No matching assets.</li>}
          </ul>
        )}
      </div>
    </div>
  );
}
