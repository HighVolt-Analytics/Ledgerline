import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

export function PageTabs({
  tabs,
  value,
  onChange,
  className,
  variant = "underline",
  "data-testid": testId,
}: {
  tabs: { value: string; label: ReactNode; testid?: string; secondary?: boolean }[];
  value: string;
  onChange: (value: string) => void;
  className?: string;
  variant?: "underline" | "pill";
  "data-testid"?: string;
}) {
  if (variant === "pill") {
    return (
      <div
        data-testid={testId}
        className={cn("app-pill-tabs", className)}
        role="tablist"
      >
        {tabs.map((tab) => (
          <button
            key={tab.value}
            type="button"
            role="tab"
            aria-selected={value === tab.value}
            data-testid={tab.testid}
            onClick={() => onChange(tab.value)}
            className={cn(
              "app-pill-tabs__tab",
              tab.secondary && "app-pill-tabs__tab--secondary",
              value === tab.value && "app-pill-tabs__tab--active"
            )}
          >
            {tab.label}
          </button>
        ))}
      </div>
    );
  }

  const primaryTabs = tabs.filter((tab) => !tab.secondary);
  const secondaryTabs = tabs.filter((tab) => tab.secondary);
  const hasSecondaryRow = secondaryTabs.length > 0 && primaryTabs.length > 0;

  const renderTab = (tab: (typeof tabs)[number], secondary = false) => (
    <button
      key={tab.value}
      type="button"
      role="tab"
      aria-selected={value === tab.value}
      data-testid={tab.testid}
      onClick={() => onChange(tab.value)}
      className={cn(
        "app-underline-tabs__tab",
        secondary && "app-underline-tabs__tab--secondary",
        value === tab.value && "app-underline-tabs__tab--active"
      )}
    >
      {tab.label}
    </button>
  );

  if (!hasSecondaryRow) {
    return (
      <div
        data-testid={testId}
        className={cn("app-underline-tabs", className)}
        role="tablist"
      >
        {tabs.map((tab) => renderTab(tab, Boolean(tab.secondary)))}
      </div>
    );
  }

  return (
    <div
      data-testid={testId}
      className={cn("app-underline-tabs-stack", className)}
      role="tablist"
    >
      <div className="app-underline-tabs">{primaryTabs.map((tab) => renderTab(tab))}</div>
      <div className="app-underline-tabs app-underline-tabs--secondary">
        {secondaryTabs.map((tab) => renderTab(tab, true))}
      </div>
    </div>
  );
}

export function PageTabPanel({
  value,
  active,
  children,
  className,
}: {
  value: string;
  active: string;
  children: ReactNode;
  className?: string;
}) {
  if (value !== active) return null;
  return <div className={className}>{children}</div>;
}
