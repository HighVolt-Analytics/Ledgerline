import type { LucideIcon } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { FileText, Search } from "lucide-react";
import { api } from "@/api/client";
import type { Invoice } from "@/api/types";
import { filterNavItems, type FlatNavItem } from "@/lib/appNavigation";
import { documentDisplayRef } from "@/lib/format";
import { cn } from "@/lib/cn";

type GlobalSearchBarProps = {
  navItems: FlatNavItem[];
  className?: string;
};

type SearchRow =
  | { kind: "nav"; key: string; to: string; label: string; hint: string; icon: LucideIcon }
  | { kind: "invoice"; key: string; id: number; label: string; hint: string }
  | { kind: "action"; key: string; label: string; hint: string };

function isMacPlatform() {
  if (typeof navigator === "undefined") return false;
  return /Mac|iPhone|iPod|iPad/i.test(navigator.platform);
}

function buildNavRows(items: FlatNavItem[]): SearchRow[] {
  return items.map((item) => ({
    kind: "nav",
    key: `nav:${item.to}`,
    to: item.to,
    label: item.label,
    hint: item.group,
    icon: item.icon,
  }));
}

function buildInvoiceRows(invoices: Invoice[]): SearchRow[] {
  return invoices.map((inv) => ({
    kind: "invoice",
    key: `invoice:${inv.id}`,
    id: inv.id,
    label: documentDisplayRef(inv) || `Invoice #${inv.id}`,
    hint: [inv.vendor, inv.invoice_no, inv.route_target].filter(Boolean).join(" · "),
  }));
}

function sectionLabelForRow(row: SearchRow, index: number, rows: SearchRow[]): string | null {
  if (index > 0 && rows[index - 1]?.kind === row.kind) return null;
  if (row.kind === "nav") return "Pages";
  if (row.kind === "invoice" || row.kind === "action") return "Documents";
  return null;
}

export function useGlobalSearchHotkey(onToggle: () => void) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        onToggle();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onToggle]);
}

export function GlobalSearchBar({ navItems, className }: GlobalSearchBarProps) {
  const navigate = useNavigate();
  const rootRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const [invoiceRows, setInvoiceRows] = useState<SearchRow[]>([]);
  const [invoiceLoading, setInvoiceLoading] = useState(false);
  const [invoiceError, setInvoiceError] = useState<string | null>(null);

  const shortcutLabel = isMacPlatform() ? "⌘K" : "Ctrl+K";
  const trimmedQuery = query.trim();

  const filteredNav = useMemo(() => filterNavItems(navItems, query), [navItems, query]);
  const navRows = useMemo(() => buildNavRows(filteredNav), [filteredNav]);

  const rows = useMemo(() => {
    const items: SearchRow[] = [...navRows];
    if (trimmedQuery.length >= 2) {
      items.push(...invoiceRows);
      items.push({
        kind: "action",
        key: "action:upload-search",
        label: `Search all documents for “${trimmedQuery}”`,
        hint: "Open Upload workspace",
      });
    }
    return items;
  }, [navRows, invoiceRows, trimmedQuery]);

  const close = useCallback(() => {
    setOpen(false);
    inputRef.current?.blur();
  }, []);

  const toggle = useCallback(() => {
    setOpen((value) => {
      const next = !value;
      if (next) {
        window.setTimeout(() => {
          inputRef.current?.focus();
          inputRef.current?.select();
        }, 0);
      } else {
        inputRef.current?.blur();
      }
      return next;
    });
  }, []);

  useGlobalSearchHotkey(toggle);

  const goToRow = useCallback(
    (row: SearchRow) => {
      if (row.kind === "nav") {
        navigate(row.to);
      } else if (row.kind === "invoice") {
        navigate(`/invoices/${row.id}`);
      } else {
        navigate(`/upload?q=${encodeURIComponent(trimmedQuery)}`);
      }
      setQuery("");
      setInvoiceRows([]);
      setInvoiceError(null);
      setActiveIndex(0);
      close();
    },
    [close, navigate, trimmedQuery]
  );

  useEffect(() => {
    setActiveIndex(0);
  }, [query, rows.length]);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) {
        close();
      }
    };
    document.addEventListener("mousedown", onPointerDown);
    return () => document.removeEventListener("mousedown", onPointerDown);
  }, [close, open]);

  useEffect(() => {
    if (!open || trimmedQuery.length < 2) {
      setInvoiceRows([]);
      setInvoiceLoading(false);
      setInvoiceError(null);
      return;
    }

    let cancelled = false;
    setInvoiceLoading(true);
    setInvoiceError(null);
    const timer = window.setTimeout(() => {
      void api
        .listInvoices({ q: trimmedQuery, page_size: "8" }, { fresh: true })
        .then((data) => {
          if (cancelled) return;
          setInvoiceRows(buildInvoiceRows(data));
        })
        .catch((err: unknown) => {
          if (cancelled) return;
          setInvoiceRows([]);
          setInvoiceError(err instanceof Error ? err.message : "Invoice search failed");
        })
        .finally(() => {
          if (!cancelled) setInvoiceLoading(false);
        });
    }, 200);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [open, trimmedQuery]);

  useEffect(() => {
    const list = listRef.current;
    if (!list) return;
    const active = list.querySelector<HTMLElement>('[data-active="true"]');
    active?.scrollIntoView({ block: "nearest" });
  }, [activeIndex, open]);

  const onInputKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      setQuery("");
      close();
      return;
    }
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActiveIndex((index) => (rows.length ? (index + 1) % rows.length : 0));
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      setActiveIndex((index) => (rows.length ? (index - 1 + rows.length) % rows.length : 0));
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      const row = rows[activeIndex];
      if (row) {
        goToRow(row);
        return;
      }
      if (trimmedQuery) {
        navigate(`/upload?q=${encodeURIComponent(trimmedQuery)}`);
        setQuery("");
        close();
      }
    }
  };

  const showEmpty = rows.length === 0 && !invoiceLoading;

  return (
    <div ref={rootRef} className={cn("relative", className)} data-testid="button-global-search">
      <div
        className={cn(
          "flex items-center gap-2 h-9 px-3 rounded-md border bg-card text-sm text-muted-foreground transition-colors",
          open ? "border-primary/40 ring-1 ring-primary/20" : "border-border hover-elevate"
        )}
      >
        <Search className="h-4 w-4 shrink-0" />
        <input
          ref={inputRef}
          type="search"
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={onInputKeyDown}
          placeholder="Search…"
          aria-label="Search"
          aria-expanded={open}
          aria-controls="global-search-results"
          autoComplete="off"
          className="flex-1 min-w-0 bg-transparent text-foreground placeholder:text-muted-foreground outline-none text-sm"
          data-testid="input-global-search"
        />
        <kbd
          className="hidden lg:inline text-[10px] rounded border border-border px-1.5 py-0.5 tnum text-muted-foreground"
          onMouseDown={(event) => event.preventDefault()}
          onClick={() => toggle()}
        >
          {shortcutLabel}
        </kbd>
      </div>

      {open && (
        <div
          id="global-search-results"
          role="listbox"
          className="absolute left-0 right-0 top-[calc(100%+6px)] z-50 overflow-hidden rounded-lg border border-border bg-popover text-popover-foreground shadow-lg"
          data-testid="dialog-global-search"
        >
          <div ref={listRef} className="max-h-[min(50vh,360px)] overflow-y-auto p-1">
            {invoiceLoading && trimmedQuery.length >= 2 && (
              <p className="px-3 py-2 text-sm text-muted-foreground">Searching documents…</p>
            )}
            {invoiceError && (
              <p className="px-3 py-2 text-sm text-destructive">{invoiceError}</p>
            )}
            {showEmpty ? (
              <p className="px-3 py-5 text-sm text-center text-muted-foreground">
                {trimmedQuery ? "No matches" : "Search pages, vendors, or invoice numbers"}
              </p>
            ) : (
              rows.map((row, index) => {
                const section = sectionLabelForRow(row, index, rows);
                return (
                  <div key={row.key}>
                    {section ? (
                      <p
                        className={cn(
                          "px-3 py-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground",
                          index > 0 && "mt-1 border-t border-border pt-2"
                        )}
                      >
                        {section}
                      </p>
                    ) : null}
                    <ResultRow
                      row={row}
                      active={activeIndex === index}
                      onSelect={() => goToRow(row)}
                      onHover={() => setActiveIndex(index)}
                    />
                  </div>
                );
              })
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function ResultRow({
  row,
  active,
  onSelect,
  onHover,
}: {
  row: SearchRow;
  active: boolean;
  onSelect: () => void;
  onHover: () => void;
}) {
  const Icon = row.kind === "nav" ? row.icon : FileText;
  return (
    <button
      type="button"
      role="option"
      aria-selected={active}
      data-active={active ? "true" : "false"}
      onMouseEnter={onHover}
      onClick={onSelect}
      className={cn(
        "flex w-full items-center gap-3 rounded-md px-3 py-2 text-left text-sm transition-colors",
        active ? "bg-accent text-accent-foreground" : "hover:bg-accent/60"
      )}
      data-testid={
        row.kind === "nav"
          ? `global-search-nav-${row.to}`
          : row.kind === "invoice"
            ? `global-search-invoice-${row.id}`
            : "global-search-action-upload"
      }
    >
      <Icon className="h-4 w-4 shrink-0 text-muted-foreground" />
      <span className="flex-1 min-w-0">
        <span className="block truncate font-medium">{row.label}</span>
        {row.hint ? (
          <span className="block truncate text-xs text-muted-foreground">{row.hint}</span>
        ) : null}
      </span>
    </button>
  );
}
