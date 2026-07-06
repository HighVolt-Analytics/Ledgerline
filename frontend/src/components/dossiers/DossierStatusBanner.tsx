import { AlertTriangle, Clock } from "lucide-react";
import { cn } from "@/lib/cn";

type DossierStatusBannerProps = {
  variant: "blocked" | "pending";
  label: string;
  detail?: string;
  action?: { label: string; onClick: () => void };
  className?: string;
};

export function DossierStatusBanner({
  variant,
  label,
  detail,
  action,
  className,
}: DossierStatusBannerProps) {
  const Icon = variant === "blocked" ? AlertTriangle : Clock;
  const text = detail ? `${label} · ${detail}` : label;

  return (
    <div className={cn("dossier-status-tag", className)}>
      <div className="dossier-status-tag__row">
        <span
          className="approvals-action-chip approvals-action-chip--static dossier-status-chip"
          title={text}
        >
          <Icon
            className={cn(
              "approvals-action-chip__icon",
              variant === "blocked"
                ? "dossier-status-chip__icon--blocked"
                : "dossier-status-chip__icon--pending"
            )}
          />
          <span className="dossier-status-chip__text">{text}</span>
        </span>
        {action ? (
          <button
            type="button"
            className="dossier-pipeline-overview__link"
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              action.onClick();
            }}
          >
            {action.label}
          </button>
        ) : null}
      </div>
    </div>
  );
}
