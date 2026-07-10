import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

export function PageEyebrowHeader({
  eyebrow,
  title,
  description,
  actions,
  leading,
  children,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  actions?: ReactNode;
  leading?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <div className="page-top-sticky">
      <div className="dossier-page-header">
        <div className="dossier-page-header__main">
          {eyebrow ? <div className="dossier-page-eyebrow">{eyebrow}</div> : null}
          <div className={cn("dossier-page-intro", leading ? "dossier-page-intro--with-leading" : undefined)}>
            {leading}
            <div className="dossier-page-intro__content min-w-0">
              <h1 className="dossier-page-title" data-testid="text-page-title">
                {title}
              </h1>
              {description ? <p className="dossier-page-desc">{description}</p> : null}
            </div>
          </div>
        </div>
        {actions ? <div className="dossier-page-actions">{actions}</div> : null}
      </div>
      {children ? <div className="page-top-sticky__below">{children}</div> : null}
    </div>
  );
}
