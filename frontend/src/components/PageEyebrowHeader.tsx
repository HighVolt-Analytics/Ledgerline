import type { ReactNode } from "react";

export function PageEyebrowHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="dossier-page-header">
      <div className="dossier-page-header__main">
        {eyebrow ? <div className="dossier-page-eyebrow">{eyebrow}</div> : null}
        <h1 className="dossier-page-title" data-testid="text-page-title">
          {title}
        </h1>
        {description ? <p className="dossier-page-desc">{description}</p> : null}
      </div>
      {actions ? <div className="dossier-page-actions">{actions}</div> : null}
    </div>
  );
}
