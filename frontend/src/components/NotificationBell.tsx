import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { useNavigate } from "react-router-dom";
import { Bell, CheckCheck, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useNotifications } from "@/hooks/useNotifications";
import type { NotificationItem } from "@/api/types";
import {
  formatUnreadBadge,
  groupNotificationsByDay,
  notificationSeverityIcon,
  relativeNotificationTime,
} from "@/lib/notifications";
import { cn } from "@/lib/cn";

type NotificationBellProps = {
  collapsed?: boolean;
};

function severityKpiTone(severity: NotificationItem["severity"]): "rose" | "rust" | "blue" {
  if (severity === "error") return "rose";
  if (severity === "action") return "rust";
  return "blue";
}

function NotificationCard({
  item,
  onOpen,
}: {
  item: NotificationItem;
  onOpen: (href: string | null) => void;
}) {
  const Icon = notificationSeverityIcon(item.severity);
  const tone = severityKpiTone(item.severity);

  return (
    <article
      className={cn(
        "notifications-drawer__item",
        item.is_unread && "notifications-drawer__item--unread"
      )}
      data-testid={`notification-item-${item.id}`}
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
          {item.href ? (
            <button
              type="button"
              className="notifications-drawer__link"
              onClick={() => onOpen(item.href)}
            >
              View
            </button>
          ) : null}
        </div>
      </div>
    </article>
  );
}

export function NotificationBell({ collapsed = false }: NotificationBellProps) {
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [mounted, setMounted] = useState(false);
  const { data, isLoading, markAllRead } = useNotifications();

  const unreadCount = data?.unread_count ?? 0;
  const badgeLabel = formatUnreadBadge(unreadCount);
  const items = data?.items ?? [];
  const groups = groupNotificationsByDay(items);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    if (!open) return;
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

  return (
    <>
      <button
        type="button"
        className={cn(
          "primary-sidebar__topic primary-sidebar__notifications-trigger",
          open && "primary-sidebar__topic--active"
        )}
        data-testid="button-notifications"
        aria-label={unreadCount > 0 ? `${unreadCount} unread notifications` : "Notifications"}
        aria-expanded={open}
        aria-haspopup="dialog"
        data-sidebar-tip={collapsed ? "Notifications" : undefined}
        onClick={() => setOpen(true)}
      >
        <span className="primary-sidebar__notifications-icon-wrap">
          <Bell className="primary-sidebar__topic-icon" aria-hidden />
          {badgeLabel ? (
            <span className="primary-sidebar__notifications-badge" aria-hidden>
              {badgeLabel}
            </span>
          ) : null}
        </span>
        {!collapsed && (
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
                data-testid="menu-notifications"
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
                    {unreadCount > 0 ? (
                      <span className="notifications-drawer__count">{unreadCount}</span>
                    ) : null}
                  </div>
                  <button
                    type="button"
                    className="notifications-drawer__mark-all approvals-action-chip approvals-action-chip--review"
                    disabled={unreadCount === 0 || markAllRead.isPending}
                    onClick={handleMarkAllRead}
                  >
                    <CheckCheck className="approvals-action-chip__icon" />
                    Mark all as read
                  </button>
                </header>

                <div className="notifications-drawer__body">
                  {isLoading ? (
                    <p className="notifications-drawer__empty">Loading…</p>
                  ) : items.length === 0 ? (
                    <div className="notifications-drawer__empty-state">
                      <span className="notifications-drawer__empty-icon">
                        <Bell className="h-5 w-5" />
                      </span>
                      <p className="notifications-drawer__empty-title">No notifications yet</p>
                      <p className="notifications-drawer__empty-copy">
                        Activity from documents, payments, and integrations will show up here.
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
