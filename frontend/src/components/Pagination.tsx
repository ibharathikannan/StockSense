import { ChevronLeft, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui";
import type { Page } from "@/lib/types";

export function Pagination({ page, onChange }: { page: Page<unknown>; onChange: (page: number) => void }) {
  const first = page.total === 0 ? 0 : (page.page - 1) * page.page_size + 1;
  const last = Math.min(page.page * page.page_size, page.total);
  return (
    <div className="flex items-center justify-between gap-4 px-4 py-3 text-sm text-muted">
      <span>
        {first}–{last} of {page.total}
      </span>
      <div className="flex items-center gap-2">
        <Button variant="secondary" className="px-2.5" disabled={page.page <= 1} onClick={() => onChange(page.page - 1)} aria-label="Previous page">
          <ChevronLeft className="size-4" />
        </Button>
        <span>
          Page {page.page} of {page.total_pages}
        </span>
        <Button
          variant="secondary"
          className="px-2.5"
          disabled={page.page >= page.total_pages}
          onClick={() => onChange(page.page + 1)}
          aria-label="Next page"
        >
          <ChevronRight className="size-4" />
        </Button>
      </div>
    </div>
  );
}
