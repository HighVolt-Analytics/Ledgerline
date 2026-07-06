import type { LucideIcon } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useNavigate } from "react-router-dom";
import { ChevronRight, CornerDownLeft, FileText, Search } from "lucide-react";
import { api } from "@/api/client";
import type { Invoice } from "@/api/types";
import { useAuth } from "@/context/AuthContext";
import { useResetOnTenantChange } from "@/hooks/useResetOnTenantChange";
import {
  canRenderTenantOwnedUi,
  captureTenantFetchScope,
  isTenantFetchAbortError,
  isTenantFetchScopeCurrent,
} from "@/lib/tenantSession";
import { filterNavItems, type FlatNavItem } from "@/lib/appNavigation";
import { documentDisplayRef } from "@/lib/format";
import { cn } from "@/lib/cn";

type GlobalSearchDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  navItems: FlatNavItem[];
};

type SearchRow =
  | { kind: "nav"; key: string; to: string; label: string; hint: string; icon: LucideIcon }
  | { kind: "invoice"; key: string; id: number; label: string; hint: string }
  | { kind: "action"; key: string; label: string; hint: string };

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

function RowLabel({ row }: { row: SearchRow }) {
  if (row.kind === "nav" && row.hint) {
    return (
      <span className="global-search-dialog__item-label">
        <span className="global-search-dialog__item-group">{row.hint}</span>
        <ChevronRight className="global-search-dialog__item-chevron" aria-hidden />
        <span className="global-search-dialog__item-name">{row.label}</span>
      </span>
    );
  }
  return <span className="global-search-dialog__item-label">{row.label}</span>;
}

export function useGlobalSearchHotkey(onOpen: () => void) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        onOpen();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onOpen]);
}

export function GlobalSearchDialog({
  open,
  onOpenChange,
  navItems,
}: GlobalSearchDialogProps) {
  const navigate = useNavigate();
  const { user } = useAuth();
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const [mounted, setMounted] = useState(false);
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const [invoiceRows, setInvoiceRows] = useState<SearchRow[]>([]);
  const [invoiceLoading, setInvoiceLoading] = useState(false);
  const [invoiceError, setInvoiceError] = useState<string | null>(null);

  useResetOnTenantChange(() => {
    setInvoiceRows([]);
    setQuery("");
    onOpenChange(false);
    setInvoiceLoading(false);
    setInvoiceError(null);
    setActiveIndex(0);
  });

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
    onOpenChange(false);
    setQuery("");
    setInvoiceRows([]);
    setInvoiceError(null);
    setActiveIndex(0);
  }, [onOpenChange]);

  const toggle = useCallback(() => {
    if (open) {
      close();
    } else {
      onOpenChange(true);
    }
  }, [close, onOpenChange, open]);

  useGlobalSearchHotkey(toggle);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    if (open) return;
    setQuery("");
    setInvoiceRows([]);
    setInvoiceError(null);
    setActiveIndex(0);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const timer = window.setTimeout(() => {
      inputRef.current?.focus();
      inputRef.current?.select();
    }, 0);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.clearTimeout(timer);
      document.body.style.overflow = prevOverflow;
    };
  }, [open]);

  const goToRow = useCallback(
    (row: SearchRow) => {
      if (row.kind === "nav") {
        navigate(row.to);
      } else if (row.kind === "invoice") {
        navigate(`/invoices/${row.id}`);
      } else {
        navigate(`/upload?q=${encodeURIComponent(trimmedQuery)}`);
      }
      close();
    },
    [close, navigate, trimmedQuery]
  );

  useEffect(() => {
    setActiveIndex(0);
  }, [query, rows.length]);

  useEffect(() => {
    if (!open || trimmedQuery.length < 2) {
      setInvoiceRows([]);
      setInvoiceLoading(false);
      setInvoiceError(null);
      return;
    }

    if (!canRenderTenantOwnedUi(user?.tenant_id)) {
      setInvoiceRows([]);
      setInvoiceLoading(false);
      return;
    }

    let cancelled = false;
    const scope = captureTenantFetchScope();
    setInvoiceLoading(true);
    setInvoiceError(null);
    const timer = window.setTimeout(() => {
      void api
        .listInvoices({ q: trimmedQuery, page_size: "8" }, { fresh: true })
        .then((data) => {
          if (cancelled || !isTenantFetchScopeCurrent(scope)) return;
          setInvoiceRows(buildInvoiceRows(data));
        })
        .catch((err: unknown) => {
          if (cancelled || !isTenantFetchScopeCurrent(scope) || isTenantFetchAbortError(err)) return;
          setInvoiceRows([]);
          setInvoiceError(err instanceof Error ? err.message : "Invoice search failed");
        })
        .finally(() => {
          if (!cancelled && isTenantFetchScopeCurrent(scope)) setInvoiceLoading(false);
        });
    }, 200);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [open, trimmedQuery, user?.tenant_id]);

  useEffect(() => {
    const list = listRef.current;
    if (!list) return;
    const active = list.querySelector<HTMLElement>('[data-active="true"]');
    active?.scrollIntoView({ block: "nearest" });
  }, [activeIndex, open]);

  const onInputKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
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
      setActiveIndex((index) =>
        rows.length ? (index - 1 + rows.length) % rows.length : 0
      );
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
        close();
      }
    }
  };

  const showEmpty = rows.length === 0 && !invoiceLoading;

  if (!mounted) return null;

  return createPortal(
    <>
      <button
        type="button"
        className="global-search-backdrop"
        data-state={open ? "open" : "closed"}
        aria-label="Close search"
        tabIndex={open ? 0 : -1}
        style={{ pointerEvents: open ? "auto" : "none" }}
        onClick={close}
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Search and navigate"
        data-state={open ? "open" : "closed"}
        data-testid="dialog-global-search"
        className="global-search-dialog"
        style={{ pointerEvents: open ? "auto" : "none" }}
      >
        <div className="global-search-dialog__input-row">
          <Search className="global-search-dialog__input-icon" aria-hidden />
          <input
            ref={inputRef}
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={onInputKeyDown}
            placeholder="Search and navigate..."
            aria-label="Search and navigate"
            aria-expanded={open}
            aria-controls="global-search-results"
            autoComplete="off"
            className="global-search-dialog__input"
            data-testid="input-global-search"
          />
        </div>

        <div
          id="global-search-results"
          ref={listRef}
          role="listbox"
          className="global-search-dialog__list"
        >
          {invoiceLoading && trimmedQuery.length >= 2 ? (
            <p className="global-search-dialog__status">Searching documents…</p>
          ) : null}
          {invoiceError ? (
            <p className="global-search-dialog__status global-search-dialog__status--error">
              {invoiceError}
            </p>
          ) : null}
          {showEmpty ? (
            <p className="global-search-dialog__empty">
              {trimmedQuery
                ? "No matches"
                : "Search pages, vendors, or invoice numbers"}
            </p>
          ) : (
            rows.map((row, index) => {
              const Icon = row.kind === "nav" ? row.icon : FileText;
              const active = activeIndex === index;
              return (
                <button
                  key={row.key}
                  type="button"
                  role="option"
                  aria-selected={active}
                  data-active={active ? "true" : "false"}
                  onMouseEnter={() => setActiveIndex(index)}
                  onClick={() => goToRow(row)}
                  className={cn(
                    "global-search-dialog__item",
                    active && "global-search-dialog__item--active"
                  )}
                  data-testid={
                    row.kind === "nav"
                      ? `global-search-nav-${row.to}`
                      : row.kind === "invoice"
                        ? `global-search-invoice-${row.id}`
                        : "global-search-action-upload"
                  }
                >
                  <Icon className="global-search-dialog__item-icon" aria-hidden />
                  <RowLabel row={row} />
                </button>
              );
            })
          )}
        </div>

        <div className="global-search-dialog__footer">
          <span className="global-search-dialog__hint">
            <kbd className="global-search-dialog__kbd">↑</kbd>
            <kbd className="global-search-dialog__kbd">↓</kbd>
            <span>to navigate</span>
          </span>
          <span className="global-search-dialog__hint">
            <kbd className="global-search-dialog__kbd">
              <CornerDownLeft className="h-3 w-3" />
            </kbd>
            <span>to select</span>
          </span>
          <span className="global-search-dialog__hint">
            <kbd className="global-search-dialog__kbd">Esc</kbd>
            <span>to close</span>
          </span>
        </div>
      </div>
    </>,
    document.body
  );
}

/** @deprecated Use GlobalSearchDialog with sidebar trigger */
export function GlobalSearchBar({
  navItems,
  className,
}: {
  navItems: FlatNavItem[];
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className={className}>
      <button
        type="button"
        className="flex h-9 w-full items-center gap-2 rounded-md border border-border bg-card px-3 text-sm text-muted-foreground hover-elevate"
        data-testid="button-global-search"
        onClick={() => setOpen(true)}
      >
        <Search className="h-4 w-4 shrink-0" />
        <span className="flex-1 text-left">Search…</span>
      </button>
      <GlobalSearchDialog open={open} onOpenChange={setOpen} navItems={navItems} />
    </div>
  );
}
