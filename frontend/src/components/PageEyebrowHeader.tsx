import type { ReactNode } from "react";

export function PageEyebrowHeader({
  eyebrow,
  title,
  description,
  actions,
  children,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  actions?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <div className="page-top-sticky">
      <div className="dossier-page-header">
        <div className="dossier-page-header__main">
          {eyebrow ? <div className="dossier-page-eyebrow">{eyebrow}</div> : null}
          <div className="dossier-page-intro">
            <h1 className="dossier-page-title" data-testid="text-page-title">
              {title}
            </h1>
            {description ? <p className="dossier-page-desc">{description}</p> : null}
          </div>
        </div>
        {actions ? <div className="dossier-page-actions">{actions}</div> : null}
      </div>
      {children ? <div className="page-top-sticky__below">{children}</div> : null}
    </div>
  );
}
