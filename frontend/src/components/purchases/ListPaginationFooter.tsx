import { Button } from "@/components/ui/button";

const MAX_PAGE_BUTTONS = 7;

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
