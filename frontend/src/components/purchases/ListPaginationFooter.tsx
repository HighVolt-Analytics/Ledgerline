import { ChevronLeft, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";

const MAX_PAGE_BUTTONS = 7;

export type PaginationItem = number | "ellipsis";

/** Compact page list with first/last and ellipsis gaps, matching 1 2 … 4 5. */
export function paginationItems(page: number, totalPages: number): PaginationItem[] {
  if (totalPages <= 1) return totalPages === 1 ? [1] : [];
  if (totalPages <= 5) {
    return Array.from({ length: totalPages }, (_, i) => i + 1);
  }

  const current = Math.min(Math.max(1, page), totalPages);
  const items: PaginationItem[] = [1];
  const start = Math.max(2, current - 1);
  const end = Math.min(totalPages - 1, current + 1);

  if (start > 2) items.push("ellipsis");
  for (let n = start; n <= end; n++) items.push(n);
  if (end < totalPages - 1) items.push("ellipsis");
  items.push(totalPages);
  return items;
}

function CirclePager({
  page,
  totalPages,
  onPageChange,
}: {
  page: number;
  totalPages: number;
  onPageChange: (page: number) => void;
}) {
  const items = paginationItems(page, totalPages);

  return (
    <nav className="table-circle-pager" aria-label="Pagination">
      <button
        type="button"
        className="table-circle-pager__btn"
        onClick={() => onPageChange(Math.max(1, page - 1))}
        disabled={page <= 1}
        aria-label="Previous page"
      >
        <ChevronLeft className="h-4 w-4" />
      </button>
      {items.map((item, index) =>
        item === "ellipsis" ? (
          <span key={`ellipsis-${index}`} className="table-circle-pager__ellipsis" aria-hidden>
            …
          </span>
        ) : (
          <button
            key={item}
            type="button"
            aria-label={`Page ${item}`}
            aria-current={item === page ? "page" : undefined}
            className={cn(
              "table-circle-pager__btn tnum",
              item === page && "table-circle-pager__btn--active"
            )}
            onClick={() => onPageChange(item)}
          >
            {item}
          </button>
        )
      )}
      <button
        type="button"
        className="table-circle-pager__btn"
        onClick={() => onPageChange(Math.min(totalPages, page + 1))}
        disabled={page >= totalPages}
        aria-label="Next page"
      >
        <ChevronRight className="h-4 w-4" />
      </button>
    </nav>
  );
}

export function ListPaginationFooter({
  page,
  totalPages,
  pageSize,
  onPageChange,
  itemLabel = "per page",
}: {
  page: number;
  totalPages: number;
  pageSize: number;
  onPageChange: (page: number) => void;
  itemLabel?: string;
}) {
  if (totalPages <= 1) return null;

  const start = Math.max(1, page - Math.floor(MAX_PAGE_BUTTONS / 2));
  const end = Math.min(totalPages, start + MAX_PAGE_BUTTONS - 1);
  const pageStart = Math.max(1, end - MAX_PAGE_BUTTONS + 1);
  const pages = Array.from({ length: end - pageStart + 1 }, (_, i) => pageStart + i);

  return (
    <div className="flex items-center justify-between gap-3 px-4 py-3 border-t border-border">
      <p className="text-xs text-muted-foreground">
        Page {page} of {totalPages}
        <span className="hidden sm:inline">
          {" "}
          · {pageSize} {itemLabel}
        </span>
      </p>
      <div className="flex items-center gap-1.5">
        <Button
          variant="outline"
          size="sm"
          className="h-8 px-2 text-xs"
          onClick={() => onPageChange(Math.max(1, page - 1))}
          disabled={page <= 1}
        >
          Prev
        </Button>
        {pages.map((p) => (
          <Button
            key={p}
            variant={p === page ? "default" : "outline"}
            size="sm"
            className="h-8 min-w-8 px-2 text-xs tnum"
            onClick={() => onPageChange(p)}
          >
            {p}
          </Button>
        ))}
        <Button
          variant="outline"
          size="sm"
          className="h-8 px-2 text-xs"
          onClick={() => onPageChange(Math.min(totalPages, page + 1))}
          disabled={page >= totalPages}
        >
          Next
        </Button>
      </div>
    </div>
  );
}

/** Upload-table footer: Total on the left, circled page numbers on the right. No page-size control or divider. */
export function TableCirclePagination({
  page,
  totalPages,
  total,
  onPageChange,
}: {
  page: number;
  totalPages: number;
  total: number;
  onPageChange: (page: number) => void;
}) {
  if (total <= 0) return null;

  return (
    <div className="flex shrink-0 items-center justify-between gap-3 px-3 sm:px-4 py-3">
      <p className="text-sm text-foreground">
        <span className="font-semibold">Total</span>{" "}
        <span className="tnum">{total}</span>
      </p>
      {totalPages >= 1 ? (
        <CirclePager page={page} totalPages={Math.max(1, totalPages)} onPageChange={onPageChange} />
      ) : null}
    </div>
  );
}
