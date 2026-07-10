import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

export function PageHeader({
  title,
  subtitle,
  eyebrow,
  actions,
  children,
}: {
  title?: string;
  subtitle?: string;
  eyebrow?: string;
  actions?: ReactNode;
  /** Tabs or toolbar rendered inside the sticky page header region */
  children?: ReactNode;
}) {
  const hasIntro = Boolean(title || eyebrow || subtitle);
  const hasHeaderRow = hasIntro || actions;

  return (
    <div className="page-top-sticky">
      {hasHeaderRow ? (
        <div className="page-header flex flex-wrap items-start justify-between gap-4">
          {hasIntro ? (
            <div className="page-header__main min-w-0 flex-1">
              {eyebrow ? (
                <p className={cn("type-caption font-medium text-muted-foreground mb-1.5")}>{eyebrow}</p>
              ) : null}
              <div className="page-header__intro">
                {title ? (
                  <h1 className="page-header__headline type-headline text-foreground">{title}</h1>
                ) : null}
                {subtitle ? (
                  <p className={cn("page-header__subline text-muted-foreground max-w-3xl")}>
                    {subtitle}
                  </p>
                ) : null}
              </div>
            </div>
          ) : (
            <div className="min-w-0 flex-1" aria-hidden />
          )}
          {actions ? <div className="flex items-center gap-2 flex-wrap shrink-0">{actions}</div> : null}
        </div>
      ) : null}
      {children ? <div className="page-top-sticky__below">{children}</div> : null}
    </div>
  );
}
