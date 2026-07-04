import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Bell } from "lucide-react";
import { useNotifications } from "@/hooks/useNotifications";
import {
  formatUnreadBadge,
  notificationSeverityClass,
  notificationSeverityIcon,
  relativeNotificationTime,
} from "@/lib/notifications";
import { cn } from "@/lib/cn";

export function NotificationBell() {
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const { data, isLoading, markAllRead } = useNotifications();

  const unreadCount = data?.unread_count ?? 0;
  const badgeLabel = formatUnreadBadge(unreadCount);
  const items = data?.items ?? [];

  function handleItemClick(href: string | null) {
    setOpen(false);
    if (href) navigate(href);
  }

  function handleMarkAllRead() {
    if (unreadCount === 0) return;
    markAllRead.mutate();
  }

  return (
    <div className="relative shrink-0 overflow-visible">
      <button
        type="button"
        data-testid="button-notifications"
        aria-label={unreadCount > 0 ? `${unreadCount} unread notifications` : "Notifications"}
        aria-expanded={open}
        className="flex h-9 w-9 items-center justify-center rounded-md border border-border bg-card text-foreground hover-elevate shrink-0"
        onClick={() => setOpen((value) => !value)}
      >
        <Bell className="h-[18px] w-[18px] shrink-0" strokeWidth={2} aria-hidden />
      </button>
      {badgeLabel ? (
        <span
          className="pointer-events-none absolute right-0 top-0 z-10 flex h-3.5 min-w-[1.125rem] -translate-y-1/2 translate-x-1/2 items-center justify-center rounded-full bg-destructive px-1 text-[8px] font-bold leading-none text-destructive-foreground ring-2 ring-background"
          aria-hidden
        >
          {badgeLabel}
        </span>
      ) : null}

      {open ? (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} aria-hidden />
          <div className="absolute right-0 top-full z-50 mt-1 w-[min(22rem,calc(100vw-1.5rem))] overflow-hidden rounded-md border border-border bg-popover shadow-md">
            <div className="flex items-center justify-between gap-2 border-b border-border px-3 py-2">
              <p className="text-sm font-semibold">Notifications</p>
              <button
                type="button"
                className="text-xs text-primary hover:underline disabled:opacity-50"
                disabled={unreadCount === 0 || markAllRead.isPending}
                onClick={handleMarkAllRead}
              >
                Mark all read
              </button>
            </div>

            <div className="max-h-80 overflow-y-auto">
              {isLoading ? (
                <p className="px-3 py-6 text-center text-sm text-muted-foreground">Loading…</p>
              ) : items.length === 0 ? (
                <p className="px-3 py-6 text-center text-sm text-muted-foreground">
                  No notifications yet
                </p>
              ) : (
                <ul className="divide-y divide-border">
                  {items.map((item) => {
                    const Icon = notificationSeverityIcon(item.severity);
                    return (
                      <li key={item.id}>
                        <button
                          type="button"
                          data-testid={`notification-item-${item.id}`}
                          className={cn(
                            "flex w-full gap-2.5 px-3 py-2.5 text-left hover:bg-accent/60 transition-colors",
                            item.is_unread && "bg-accent/20"
                          )}
                          onClick={() => handleItemClick(item.href)}
                        >
                          <Icon
                            className={cn(
                              "mt-0.5 h-4 w-4 shrink-0",
                              notificationSeverityClass(item.severity)
                            )}
                          />
                          <span className="min-w-0 flex-1">
                            <span className="block text-sm font-medium leading-snug line-clamp-2">
                              {item.title}
                            </span>
                            {item.summary ? (
                              <span className="mt-0.5 block text-xs text-muted-foreground line-clamp-2">
                                {item.summary}
                              </span>
                            ) : null}
                            <span className="mt-1 block text-[11px] text-muted-foreground">
                              {relativeNotificationTime(item.created_at)}
                            </span>
                          </span>
                          {item.is_unread ? (
                            <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-primary" />
                          ) : null}
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          </div>
        </>
      ) : null}
    </div>
  );
}
