import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

export function PageHeader({
  title,
  subtitle,
  eyebrow,
  actions,
  headline,
  children,
}: {
  title?: string;
  subtitle?: string;
  eyebrow?: string;
  actions?: ReactNode;
  /** Replaces title/subtitle in the headline row (e.g. page-level tabs). */
  headline?: ReactNode;
  /** Tabs or toolbar rendered inside the sticky page header region */
  children?: ReactNode;
}) {
  const hasIntro = Boolean(title || eyebrow || subtitle || headline);
  const hasHeaderRow = hasIntro || actions;

  return (
    <div className="page-top-sticky">
      {hasHeaderRow ? (
        <div
          className={cn(
            "page-header flex flex-wrap justify-between gap-4",
            headline ? "items-end" : "items-start"
          )}
        >
          {hasIntro ? (
            <div className="page-header__main min-w-0 flex-1">
              {eyebrow ? (
                <p className={cn("type-caption font-medium text-muted-foreground mb-1.5")}>{eyebrow}</p>
              ) : null}
              {headline ? (
                <div className="page-header__headline-tabs">{headline}</div>
              ) : (
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
              )}
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
