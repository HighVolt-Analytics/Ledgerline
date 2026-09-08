import type { LucideIcon } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useNavigate } from "react-router-dom";
import {
  ArrowUpRight,
  Building2,
  CircleUser,
  CornerDownLeft,
  FileText,
  HandCoins,
  Search,
  Users,
  Wallet,
} from "lucide-react";
import { api } from "@/api/client";
import type { CollectionApi, Invoice, PaymentApi } from "@/api/types";
import { useAuth } from "@/context/AuthContext";
import { useResetOnTenantChange } from "@/hooks/useResetOnTenantChange";
import {
  canRenderTenantOwnedUi,
  captureTenantFetchScope,
  isTenantFetchAbortError,
  isTenantFetchScopeCurrent,
} from "@/lib/tenantSession";
import { filterNavItems, type FlatNavItem } from "@/lib/appNavigation";
import {
  customerMasterFromApi,
  employeeMasterFromApi,
  vendorMasterFromApi,
} from "@/lib/masterDataApi";
import { matchesListSearch } from "@/lib/listSearch";
import { documentDisplayRef, money, statusLabel } from "@/lib/format";
import type { CustomerMaster, EmployeeMaster, VendorMaster } from "@/lib/v4RuleBookTypes";
import { cn } from "@/lib/cn";

type GlobalSearchDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  navItems: FlatNavItem[];
};

type SearchSectionId =
  | "pages"
  | "documents"
  | "contacts"
  | "payments"
  | "collections"
  | "actions";

type SearchRow =
  | {
      kind: "nav";
      section: "pages";
      key: string;
      to: string;
      label: string;
      hint: string;
      icon: LucideIcon;
    }
  | {
      kind: "document";
      section: "documents";
      key: string;
      id: number;
      label: string;
      party: string;
      meta: string;
      amount: string;
      status: string;
    }
  | {
      kind: "contact";
      section: "contacts";
      key: string;
      to: string;
      label: string;
      contactType: "Vendor" | "Customer" | "Employee";
      hint: string;
      icon: LucideIcon;
    }
  | {
      kind: "payment";
      section: "payments";
      key: string;
      to: string;
      label: string;
      meta: string;
      amount: string;
      status: string;
    }
  | {
      kind: "collection";
      section: "collections";
      key: string;
      to: string;
      label: string;
      meta: string;
      amount: string;
      status: string;
    }
  | {
      kind: "action";
      section: "actions";
      key: string;
      to: string;
      label: string;
      hint: string;
    };

const SECTION_ORDER: SearchSectionId[] = [
  "pages",
  "documents",
  "contacts",
  "payments",
  "collections",
  "actions",
];

const SECTION_LABELS: Record<SearchSectionId, string> = {
  pages: "Pages",
  documents: "Documents",
  contacts: "Contacts",
  payments: "Payments",
  collections: "Collections",
  actions: "Actions",
};

const DOC_LIMIT = 8;
const CONTACT_LIMIT = 5;
const PAYMENT_LIMIT = 5;

function buildNavRows(items: FlatNavItem[]): SearchRow[] {
  return items.map((item) => ({
    kind: "nav",
    section: "pages",
    key: `nav:${item.to}`,
    to: item.to,
    label: item.label,
    hint: item.group,
    icon: item.icon,
  }));
}

function buildDocumentRows(invoices: Invoice[]): SearchRow[] {
  return invoices.map((inv) => {
    const party = (inv.vendor || inv.employee_email || "").trim();
    const bits = [
      inv.invoice_no?.trim() || null,
      inv.document_type_code?.trim() || null,
      inv.route_target?.trim() || null,
      inv.invoice_date?.trim() || null,
    ].filter(Boolean);
    return {
      kind: "document",
      section: "documents",
      key: `document:${inv.id}`,
      id: inv.id,
      label: documentDisplayRef(inv),
      party: party || "Unknown party",
      meta: bits.join(" · "),
      amount: money(inv.total, inv.currency),
      status: statusLabel(inv.current_stage || inv.status || "unknown"),
    };
  });
}

function buildVendorRows(vendors: VendorMaster[], query: string): SearchRow[] {
  return vendors
    .filter((v) => matchesListSearch(query, v.name, v.abn, v.contactEmail, v.contactPhone, ...v.aliases))
    .slice(0, CONTACT_LIMIT)
    .map((v) => ({
      kind: "contact" as const,
      section: "contacts" as const,
      key: `vendor:${v.id}`,
      to: `/creations?tab=vendors&mastersQ=${encodeURIComponent(v.name)}`,
      label: v.name,
      contactType: "Vendor" as const,
      hint: [v.abn, v.status].filter(Boolean).join(" · "),
      icon: Building2,
    }));
}

function buildCustomerRows(customers: CustomerMaster[], query: string): SearchRow[] {
  return customers
    .filter((c) => matchesListSearch(query, c.name, c.abn, ...c.aliases))
    .slice(0, CONTACT_LIMIT)
    .map((c) => ({
      kind: "contact" as const,
      section: "contacts" as const,
      key: `customer:${c.id}`,
      to: `/creations?tab=customers&mastersQ=${encodeURIComponent(c.name)}`,
      label: c.name,
      contactType: "Customer" as const,
      hint: [c.abn, c.status].filter(Boolean).join(" · "),
      icon: Users,
    }));
}

function buildEmployeeRows(employees: EmployeeMaster[], query: string): SearchRow[] {
  return employees
    .filter((e) =>
      matchesListSearch(query, e.name, e.email, e.role, e.department, e.location)
    )
    .slice(0, CONTACT_LIMIT)
    .map((e) => ({
      kind: "contact" as const,
      section: "contacts" as const,
      key: `employee:${e.id}`,
      to: `/creations?tab=employees&mastersQ=${encodeURIComponent(e.name)}`,
      label: e.name,
      contactType: "Employee" as const,
      hint: [e.role || e.department, e.email].filter(Boolean).join(" · "),
      icon: CircleUser,
    }));
}

function buildPaymentRows(payments: PaymentApi[], query: string): SearchRow[] {
  return payments
    .filter((p) =>
      matchesListSearch(query, p.id, p.invoice_id, p.vendor, p.status, p.amount, p.currency)
    )
    .slice(0, PAYMENT_LIMIT)
    .map((p) => ({
      kind: "payment" as const,
      section: "payments" as const,
      key: `payment:${p.id}`,
      to: `/invoices/${p.invoice_id}`,
      label: p.vendor?.trim() || `Payment #${p.id}`,
      meta: [`Invoice #${p.invoice_id}`, p.due_date].filter(Boolean).join(" · "),
      amount: money(p.amount, p.currency),
      status: statusLabel(p.status),
    }));
}

function buildCollectionRows(collections: CollectionApi[], query: string): SearchRow[] {
  return collections
    .filter((c) =>
      matchesListSearch(query, c.id, c.invoice_id, c.customer, c.status, c.amount, c.currency)
    )
    .slice(0, PAYMENT_LIMIT)
    .map((c) => ({
      kind: "collection" as const,
      section: "collections" as const,
      key: `collection:${c.id}`,
      to: `/invoices/${c.invoice_id}`,
      label: c.customer?.trim() || `Collection #${c.id}`,
      meta: [`Invoice #${c.invoice_id}`, c.due_date].filter(Boolean).join(" · "),
      amount: money(c.amount, c.currency),
      status: statusLabel(c.status),
    }));
}

function rowIcon(row: SearchRow): LucideIcon {
  if (row.kind === "nav") return row.icon;
  if (row.kind === "contact") return row.icon;
  if (row.kind === "payment") return Wallet;
  if (row.kind === "collection") return HandCoins;
  if (row.kind === "action") return ArrowUpRight;
  return FileText;
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
  const [documentRows, setDocumentRows] = useState<SearchRow[]>([]);
  const [contactRows, setContactRows] = useState<SearchRow[]>([]);
  const [paymentRows, setPaymentRows] = useState<SearchRow[]>([]);
  const [collectionRows, setCollectionRows] = useState<SearchRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const catalogRef = useRef<{
    vendors: VendorMaster[];
    customers: CustomerMaster[];
    employees: EmployeeMaster[];
    payments: PaymentApi[];
    collections: CollectionApi[];
  } | null>(null);

  const resetResults = useCallback(() => {
    setDocumentRows([]);
    setContactRows([]);
    setPaymentRows([]);
    setCollectionRows([]);
    setLoading(false);
    setSearchError(null);
    setActiveIndex(0);
    catalogRef.current = null;
  }, []);

  useResetOnTenantChange(() => {
    setQuery("");
    onOpenChange(false);
    resetResults();
  });

  const trimmedQuery = query.trim();

  const filteredNav = useMemo(() => filterNavItems(navItems, query), [navItems, query]);
  const navRows = useMemo(() => buildNavRows(filteredNav), [filteredNav]);

  const actionRows = useMemo((): SearchRow[] => {
    if (trimmedQuery.length < 2) return [];
    return [
      {
        kind: "action",
        section: "actions",
        key: "action:upload-search",
        to: `/upload?q=${encodeURIComponent(trimmedQuery)}`,
        label: `Search all documents for “${trimmedQuery}”`,
        hint: "Open Upload workspace",
      },
      {
        kind: "action",
        section: "actions",
        key: "action:contacts-search",
        to: `/creations?tab=vendors&mastersQ=${encodeURIComponent(trimmedQuery)}`,
        label: `Search contacts for “${trimmedQuery}”`,
        hint: "Open Contacts",
      },
    ];
  }, [trimmedQuery]);

  const rows = useMemo(() => {
    return [
      ...navRows,
      ...(trimmedQuery.length >= 2 ? documentRows : []),
      ...(trimmedQuery.length >= 2 ? contactRows : []),
      ...(trimmedQuery.length >= 2 ? paymentRows : []),
      ...(trimmedQuery.length >= 2 ? collectionRows : []),
      ...actionRows,
    ];
  }, [
    navRows,
    documentRows,
    contactRows,
    paymentRows,
    collectionRows,
    actionRows,
    trimmedQuery.length,
  ]);

  const sections = useMemo(() => {
    return SECTION_ORDER.map((id) => ({
      id,
      label: SECTION_LABELS[id],
      rows: rows.filter((row) => row.section === id),
    })).filter((section) => section.rows.length > 0);
  }, [rows]);

  const flatIndexByKey = useMemo(() => {
    const map = new Map<string, number>();
    rows.forEach((row, index) => map.set(row.key, index));
    return map;
  }, [rows]);

  const close = useCallback(() => {
    onOpenChange(false);
    setQuery("");
    resetResults();
  }, [onOpenChange, resetResults]);

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
    resetResults();
  }, [open, resetResults]);

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
      if (row.kind === "document") {
        navigate(`/invoices/${row.id}`);
      } else {
        navigate(row.to);
      }
      close();
    },
    [close, navigate]
  );

  useEffect(() => {
    setActiveIndex(0);
  }, [query, rows.length]);

  useEffect(() => {
    if (!open || trimmedQuery.length < 2) {
      setDocumentRows([]);
      setContactRows([]);
      setPaymentRows([]);
      setCollectionRows([]);
      setLoading(false);
      setSearchError(null);
      return;
    }

    if (!canRenderTenantOwnedUi(user?.tenant_id)) {
      setDocumentRows([]);
      setContactRows([]);
      setPaymentRows([]);
      setCollectionRows([]);
      setLoading(false);
      return;
    }

    let cancelled = false;
    const scope = captureTenantFetchScope();
    setLoading(true);
    setSearchError(null);

    const timer = window.setTimeout(() => {
      void (async () => {
        try {
          const catalogPromise = catalogRef.current
            ? Promise.resolve(catalogRef.current)
            : Promise.all([
                api.listVendorMasters({ fresh: true }),
                api.listCustomerMasters({ fresh: true }),
                api.listEmployeeMasters({ fresh: true }),
                api.listPayments(undefined, { fresh: true, limit: 200 }),
                api.listCollections({ fresh: true, limit: 200 }),
              ]).then(([vendorsRaw, customersRaw, employeesRaw, payments, collections]) => {
                const catalog = {
                  vendors: vendorsRaw.map(vendorMasterFromApi),
                  customers: customersRaw.map(customerMasterFromApi),
                  employees: employeesRaw.map(employeeMasterFromApi),
                  payments,
                  collections,
                };
                catalogRef.current = catalog;
                return catalog;
              });

          const [invoices, catalog] = await Promise.all([
            api.listInvoices({ q: trimmedQuery, page_size: String(DOC_LIMIT) }, { fresh: true }),
            catalogPromise,
          ]);

          if (cancelled || !isTenantFetchScopeCurrent(scope)) return;

          setDocumentRows(buildDocumentRows(invoices));
          setContactRows([
            ...buildVendorRows(catalog.vendors, trimmedQuery),
            ...buildCustomerRows(catalog.customers, trimmedQuery),
            ...buildEmployeeRows(catalog.employees, trimmedQuery),
          ]);
          setPaymentRows(buildPaymentRows(catalog.payments, trimmedQuery));
          setCollectionRows(buildCollectionRows(catalog.collections, trimmedQuery));
        } catch (err: unknown) {
          if (cancelled || !isTenantFetchScopeCurrent(scope) || isTenantFetchAbortError(err)) {
            return;
          }
          setDocumentRows([]);
          setContactRows([]);
          setPaymentRows([]);
          setCollectionRows([]);
          setSearchError(err instanceof Error ? err.message : "Search failed");
        } finally {
          if (!cancelled) setLoading(false);
        }
      })();
    }, 220);

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

  const showEmpty = rows.length === 0 && !loading;

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
        aria-label="Search application"
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
            placeholder="Search pages, documents, contacts, payments…"
            aria-label="Search application"
            aria-expanded={open}
            aria-controls="global-search-results"
            autoComplete="off"
            className="global-search-dialog__input"
            data-testid="input-global-search"
          />
          {loading ? (
            <span className="global-search-dialog__spinner" aria-label="Searching" />
          ) : null}
        </div>

        <div
          id="global-search-results"
          ref={listRef}
          role="listbox"
          className="global-search-dialog__list"
        >
          {searchError ? (
            <p className="global-search-dialog__status global-search-dialog__status--error">
              {searchError}
            </p>
          ) : null}
          {showEmpty ? (
            <div className="global-search-dialog__empty">
              <p className="global-search-dialog__empty-title">
                {trimmedQuery ? "No matches" : "Search the application"}
              </p>
              <p className="global-search-dialog__empty-hint">
                {trimmedQuery
                  ? "Try another term, or open Upload / Contacts from Actions when available."
                  : "Pages, documents, vendors, customers, employees, payments, and collections."}
              </p>
            </div>
          ) : (
            sections.map((section) => (
              <section
                key={section.id}
                className="global-search-dialog__section"
                aria-label={section.label}
              >
                <h2 className="global-search-dialog__section-label">{section.label}</h2>
                {section.rows.map((row) => {
                  const index = flatIndexByKey.get(row.key) ?? 0;
                  const active = activeIndex === index;
                  const Icon = rowIcon(row);
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
                          : row.kind === "document"
                            ? `global-search-invoice-${row.id}`
                            : `global-search-${row.key}`
                      }
                    >
                      <span className="global-search-dialog__item-icon-wrap">
                        <Icon className="global-search-dialog__item-icon" aria-hidden />
                      </span>
                      <span className="global-search-dialog__item-body">
                        {row.kind === "nav" ? (
                          <>
                            <span className="global-search-dialog__item-title">{row.label}</span>
                            {row.hint ? (
                              <span className="global-search-dialog__item-sub">{row.hint}</span>
                            ) : null}
                          </>
                        ) : null}
                        {row.kind === "document" ? (
                          <>
                            <span className="global-search-dialog__item-title-row">
                              <span className="global-search-dialog__item-title">{row.label}</span>
                              <span className="global-search-dialog__item-amount">{row.amount}</span>
                            </span>
                            <span className="global-search-dialog__item-sub">
                              {row.party}
                              {row.meta ? ` · ${row.meta}` : ""}
                            </span>
                            <span className="global-search-dialog__item-status">{row.status}</span>
                          </>
                        ) : null}
                        {row.kind === "contact" ? (
                          <>
                            <span className="global-search-dialog__item-title-row">
                              <span className="global-search-dialog__item-title">{row.label}</span>
                              <span className="global-search-dialog__item-type">
                                {row.contactType}
                              </span>
                            </span>
                            {row.hint ? (
                              <span className="global-search-dialog__item-sub">{row.hint}</span>
                            ) : null}
                          </>
                        ) : null}
                        {row.kind === "payment" || row.kind === "collection" ? (
                          <>
                            <span className="global-search-dialog__item-title-row">
                              <span className="global-search-dialog__item-title">{row.label}</span>
                              <span className="global-search-dialog__item-amount">{row.amount}</span>
                            </span>
                            <span className="global-search-dialog__item-sub">
                              {row.meta}
                              {row.meta ? " · " : ""}
                              {row.status}
                            </span>
                          </>
                        ) : null}
                        {row.kind === "action" ? (
                          <>
                            <span className="global-search-dialog__item-title">{row.label}</span>
                            <span className="global-search-dialog__item-sub">{row.hint}</span>
                          </>
                        ) : null}
                      </span>
                    </button>
                  );
                })}
              </section>
            ))
          )}
        </div>

        <div className="global-search-dialog__footer">
          <span className="global-search-dialog__hint">
            <kbd className="global-search-dialog__kbd">↑</kbd>
            <kbd className="global-search-dialog__kbd">↓</kbd>
            <span>navigate</span>
          </span>
          <span className="global-search-dialog__hint">
            <kbd className="global-search-dialog__kbd">
              <CornerDownLeft className="h-3 w-3" />
            </kbd>
            <span>open</span>
          </span>
          <span className="global-search-dialog__hint">
            <kbd className="global-search-dialog__kbd">Esc</kbd>
            <span>close</span>
          </span>
        </div>
      </div>
    </>,
    document.body
  );
}

/** Centered workspace search trigger; opens GlobalSearchDialog (also ⌘/Ctrl+K). */
export function GlobalSearchBar({
  navItems,
  className,
}: {
  navItems: FlatNavItem[];
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const isMac =
    typeof navigator !== "undefined" &&
    /Mac|iPhone|iPad|iPod/i.test(navigator.platform || navigator.userAgent || "");

  return (
    <div className={cn("global-search-trigger-wrap", className)}>
      <button
        type="button"
        className="global-search-trigger"
        data-testid="button-global-search"
        aria-label="Search"
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => setOpen(true)}
      >
        <Search className="global-search-trigger__icon" aria-hidden />
        <span className="global-search-trigger__label">Search…</span>
        <kbd className="global-search-trigger__kbd">{isMac ? "⌘K" : "Ctrl+K"}</kbd>
      </button>
      <GlobalSearchDialog open={open} onOpenChange={setOpen} navItems={navItems} />
    </div>
  );
}
