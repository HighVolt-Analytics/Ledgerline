import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

export function SectionBlock({
  label,
  description,
  actions,
  children,
  className,
}: {
  label?: string;
  description?: string;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("dossier-section", className)}>
      {label || actions ? (
        <div className="dossier-section__head">
          <div>
            {label ? <h2 className="dossier-section__label">{label}</h2> : null}
            {description ? <p className="dossier-section__desc">{description}</p> : null}
          </div>
          {actions}
        </div>
      ) : null}
      {children}
    </section>
  );
}
