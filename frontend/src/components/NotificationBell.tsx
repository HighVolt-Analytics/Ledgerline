import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { useNavigate } from "react-router-dom";
import { AlertTriangle, Bell, CheckCheck, Copy, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useNotifications } from "@/hooks/useNotifications";
import { useTenantQuery } from "@/hooks/useTenantQuery";
import type { MatrixRow, NotificationItem } from "@/api/types";
import {
  formatUnreadBadge,
  groupNotificationsByDay,
  isDuplicateFileNotificationEvent,
  notificationSeverityIcon,
  relativeNotificationTime,
} from "@/lib/notifications";
import { duplicateNotificationCopy } from "@/lib/allDocumentsDetailed";
import { documentDisplayRef } from "@/lib/format";
import { counterpartyName } from "@/lib/invoice";
import { fetchMatrixPage } from "@/lib/matrixApi";
import { queryKeys } from "@/lib/queryClient";
import { cn } from "@/lib/cn";
import { kpiModuleIconClass } from "@/lib/kpiModuleColors";

type NotificationBellProps = {
  collapsed?: boolean;
  /** Compact icon for page headers. Sidebar is the default. */
  variant?: "sidebar" | "header";
};

function severityKpiTone(severity: NotificationItem["severity"]): "rose" | "rust" | "blue" {
  if (severity === "error") return "rose";
  if (severity === "action") return "rust";
  return "blue";
}

function duplicateRowToNotification(row: MatrixRow): NotificationItem {
  const inv = row.invoice;
  const copy = duplicateNotificationCopy(row);
  const party = counterpartyName(inv);
  const ref = documentDisplayRef(inv);
  const title =
    party && party !== "—"
      ? `${ref} · ${party} — ${copy.title}`
      : `${ref} — ${copy.title}`;
  return {
    id: `dup-${inv.id}`,
    source: "system",
    audit_log_id: null,
    event: inv.status === "duplicate_skipped" ? "duplicate_skipped" : "duplicate_review_suggested",
    title,
    summary: copy.detail,
    severity: "action",
    href: `/upload?invoice=${inv.id}`,
    created_at: inv.created_at ?? new Date().toISOString(),
    is_unread: true,
  };
}

function NotificationCard({
  item,
  onOpen,
}: {
  item: NotificationItem;
  onOpen: (href: string | null) => void;
}) {
  const Icon =
    isDuplicateFileNotificationEvent(item.event) || item.event === "duplicate_review_suggested"
      ? AlertTriangle
      : notificationSeverityIcon(item.severity);
  const tone = severityKpiTone(item.severity);
  const clickable = Boolean(item.href);
  const Tag = clickable ? "button" : "article";

  return (
    <Tag
      type={clickable ? "button" : undefined}
      className={cn(
        "notifications-drawer__item",
        item.is_unread && "notifications-drawer__item--unread",
        clickable && "notifications-drawer__item--clickable"
      )}
      data-testid={`notification-item-${item.id}`}
      onClick={clickable ? () => onOpen(item.href) : undefined}
      aria-label={clickable ? `Open notification: ${item.title}` : undefined}
    >
      {item.is_unread ? (
        <span
          className={cn(
            "notifications-drawer__item-rail",
            `notifications-drawer__item-rail--${tone}`
          )}
          aria-hidden
        />
      ) : null}

      <div className={cn("notifications-drawer__item-icon", `kpi-module-icon--${tone}`)}>
        <Icon className="h-4 w-4" />
      </div>

      <div className="notifications-drawer__item-body">
        <div className="notifications-drawer__item-top">
          <h3 className="notifications-drawer__item-title">{item.title}</h3>
        </div>
        {item.summary ? (
          <p className="notifications-drawer__item-summary">{item.summary}</p>
        ) : null}
        <div className="notifications-drawer__item-meta">
          <span className="notifications-drawer__item-time">
            {relativeNotificationTime(item.created_at)}
          </span>
        </div>
      </div>
    </Tag>
  );
}

export function NotificationBell({ collapsed = false, variant = "sidebar" }: NotificationBellProps) {
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [mounted, setMounted] = useState(false);
  const [showDuplicateFiles, setShowDuplicateFiles] = useState(false);
  const { data, isLoading, markAllRead } = useNotifications();
  const isHeader = variant === "header";

  const unreadCount = data?.unread_count ?? 0;
  const badgeLabel = formatUnreadBadge(unreadCount);
  const items = data?.items ?? [];

  const duplicateQuery = useTenantQuery({
    queryKey: queryKeys.duplicateFileNotifications(),
    queryFn: () =>
      fetchMatrixPage(1, { matrix_filter: "duplicates", page_size: "50" }, true),
    enabled: open,
    staleTime: 30_000,
  });

  const duplicateItems = useMemo(
    () => (duplicateQuery.data?.rows ?? []).map(duplicateRowToNotification),
    [duplicateQuery.data?.rows]
  );
  const duplicateTotal = duplicateQuery.data?.total ?? duplicateItems.length;

  const visibleItems = useMemo(() => {
    if (showDuplicateFiles) return duplicateItems;
    return items.filter((item) => !isDuplicateFileNotificationEvent(item.event));
  }, [showDuplicateFiles, duplicateItems, items]);

  const groups = groupNotificationsByDay(visibleItems);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    if (!open) {
      setShowDuplicateFiles(false);
      return;
    }
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("keydown", onKeyDown);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = prevOverflow;
    };
  }, [open]);

  function handleItemOpen(href: string | null) {
    setOpen(false);
    if (href) navigate(href);
  }

  function handleMarkAllRead() {
    if (unreadCount === 0) return;
    markAllRead.mutate();
  }

  const listLoading = showDuplicateFiles
    ? duplicateQuery.isLoading || duplicateQuery.isFetching
    : isLoading;

  return (
    <>
      <button
        type="button"
        className={cn(
          isHeader
            ? "page-notifications-trigger"
            : "primary-sidebar__topic primary-sidebar__notifications-trigger",
          open && (isHeader ? "page-notifications-trigger--active" : "primary-sidebar__topic--active")
        )}
        data-testid={isHeader ? "button-notifications-page" : "button-notifications"}
        aria-label={unreadCount > 0 ? `${unreadCount} unread notifications` : "Notifications"}
        aria-expanded={open}
        aria-haspopup="dialog"
        data-sidebar-tip={!isHeader && collapsed ? "Notifications" : undefined}
        onClick={() => setOpen(true)}
      >
        <span
          className={
            isHeader
              ? "page-notifications-trigger__icon-wrap"
              : "primary-sidebar__notifications-icon-wrap"
          }
        >
          {isHeader ? (
            <Bell className="page-notifications-trigger__icon" aria-hidden />
          ) : (
            <span className={cn("sidebar-icon-tile", kpiModuleIconClass("rose"))} aria-hidden>
              <Bell className="primary-sidebar__topic-icon" />
            </span>
          )}
          {badgeLabel ? (
            <span
              className={
                isHeader
                  ? "page-notifications-trigger__badge"
                  : "primary-sidebar__notifications-badge"
              }
              aria-hidden
            >
              {badgeLabel}
            </span>
          ) : null}
        </span>
        {!isHeader && !collapsed && (
          <span className="primary-sidebar__topic-label">Notifications</span>
        )}
      </button>

      {mounted
        ? createPortal(
            <>
              <button
                type="button"
                className="invoice-drawer-backdrop"
                data-state={open ? "open" : "closed"}
                aria-label="Close notifications"
                tabIndex={open ? 0 : -1}
                style={{ pointerEvents: open ? "auto" : "none" }}
                onClick={() => setOpen(false)}
              />
              <aside
                role="dialog"
                aria-modal="true"
                aria-label="Notifications"
                data-testid={isHeader ? "menu-notifications-page" : "menu-notifications"}
                data-state={open ? "open" : "closed"}
                className={cn(
                  "invoice-drawer-panel invoice-drawer-panel--sheet notifications-drawer",
                  "flex h-full flex-col gap-0 border-l border-border bg-card p-0 shadow-lg"
                )}
                style={{ pointerEvents: open ? "auto" : "none" }}
              >
                <header className="notifications-drawer__header">
                  <div className="notifications-drawer__header-main">
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="notifications-drawer__close"
                      aria-label="Close notifications"
                      onClick={() => setOpen(false)}
                    >
                      <X className="h-4 w-4" />
                    </Button>
                    <h2 className="notifications-drawer__title">Notifications</h2>
                    {unreadCount > 0 && !showDuplicateFiles ? (
                      <span className="notifications-drawer__count">{unreadCount}</span>
                    ) : null}
                    {showDuplicateFiles && duplicateTotal > 0 ? (
                      <span className="notifications-drawer__count">{duplicateTotal}</span>
                    ) : null}
                  </div>
                  <button
                    type="button"
                    className="notifications-drawer__mark-all approvals-action-chip approvals-action-chip--review"
                    disabled={unreadCount === 0 || markAllRead.isPending || showDuplicateFiles}
                    onClick={handleMarkAllRead}
                  >
                    <CheckCheck className="approvals-action-chip__icon" />
                    Mark all as read
                  </button>
                </header>

                <div className="notifications-drawer__toolbar">
                  <button
                    type="button"
                    className={cn(
                      "notifications-drawer__toggle",
                      showDuplicateFiles && "notifications-drawer__toggle--active"
                    )}
                    aria-pressed={showDuplicateFiles}
                    data-testid="notifications-duplicate-files-toggle"
                    onClick={() => setShowDuplicateFiles((prev) => !prev)}
                  >
                    <Copy className="h-3.5 w-3.5" aria-hidden />
                    Duplicate files
                    {duplicateTotal > 0 ? (
                      <span className="notifications-drawer__toggle-count">{duplicateTotal}</span>
                    ) : null}
                  </button>
                </div>

                <div className="notifications-drawer__body">
                  {listLoading ? (
                    <p className="notifications-drawer__empty">Loading…</p>
                  ) : visibleItems.length === 0 ? (
                    <div className="notifications-drawer__empty-state">
                      <span className="notifications-drawer__empty-icon">
                        {showDuplicateFiles ? (
                          <Copy className="h-5 w-5" />
                        ) : (
                          <Bell className="h-5 w-5" />
                        )}
                      </span>
                      <p className="notifications-drawer__empty-title">
                        {showDuplicateFiles
                          ? "No duplicate files"
                          : "No notifications yet"}
                      </p>
                      <p className="notifications-drawer__empty-copy">
                        {showDuplicateFiles
                          ? "When a file is detected as a duplicate, it appears here instead of the documents table."
                          : "Activity from documents, payments, and integrations will show up here."}
                      </p>
                    </div>
                  ) : (
                    groups.map((group) => (
                      <section key={group.label} className="notifications-drawer__group">
                        <h3 className="notifications-drawer__group-label">{group.label}</h3>
                        <div className="notifications-drawer__list">
                          {group.items.map((item) => (
                            <NotificationCard
                              key={item.id}
                              item={item}
                              onOpen={handleItemOpen}
                            />
                          ))}
                        </div>
                      </section>
                    ))
                  )}
                </div>
              </aside>
            </>,
            document.body
          )
        : null}
    </>
  );
}
