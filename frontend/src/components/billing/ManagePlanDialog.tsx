import { useEffect } from "react";
import { createPortal } from "react-dom";
import { Crown, X } from "lucide-react";
import { PricingPlanCards } from "@/components/billing/PricingPlanCards";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/cn";
import type { PlanId, PricingRegion } from "@/lib/pricingPlans";

type ManagePlanDialogProps = {
  open: boolean;
  onClose: () => void;
  currentPlan: PlanId;
  currentPlanLabel: string;
  region: PricingRegion;
  canUpgradeStudio?: boolean;
  busy?: boolean;
  platformBillingEnabled?: boolean;
  onSelectPlan: (plan: PlanId) => void;
};

function workspacePortalRoot(): HTMLElement {
  return (
    document.querySelector<HTMLElement>("[data-app-workspace-portal]") ?? document.body
  );
}

export function ManagePlanDialog({
  open,
  onClose,
  currentPlan,
  currentPlanLabel,
  region,
  canUpgradeStudio = false,
  busy = false,
  platformBillingEnabled = false,
  onSelectPlan,
}: ManagePlanDialogProps) {
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKeyDown);

    const scrollEl = document.querySelector<HTMLElement>(".app-workspace__scroll");
    const prevBody = document.body.style.overflow;
    const prevScroll = scrollEl?.style.overflow;
    document.body.style.overflow = "hidden";
    if (scrollEl) scrollEl.style.overflow = "hidden";

    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = prevBody;
      if (scrollEl) scrollEl.style.overflow = prevScroll ?? "";
    };
  }, [open, onClose]);

  if (!open) return null;

  const portalRoot = workspacePortalRoot();
  const inWorkspace = portalRoot.hasAttribute("data-app-workspace-portal");

  return createPortal(
    <div
      className={cn("billing-plan-dialog", inWorkspace && "billing-plan-dialog--workspace")}
      role="dialog"
      aria-modal="true"
      aria-labelledby="billing-plan-dialog-title"
      onClick={onClose}
    >
      <div className="billing-plan-dialog__panel" onClick={(e) => e.stopPropagation()}>
        <header className="billing-plan-dialog__header">
          <div>
            <h2 id="billing-plan-dialog-title" className="billing-plan-dialog__title">
              <Crown className="h-4 w-4 text-primary" aria-hidden />
              Manage plan
            </h2>
            <p className="billing-plan-dialog__subtitle">
              Current plan: <Badge variant="outline">{currentPlanLabel}</Badge>
            </p>
          </div>
          <button
            type="button"
            className="billing-plan-dialog__close"
            onClick={onClose}
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="billing-plan-dialog__body">
          <PricingPlanCards
            region={region}
            currentPlan={currentPlan}
            canUpgradeStudio={canUpgradeStudio}
            busy={busy}
            onSelectPlan={onSelectPlan}
          />
        </div>

        <footer className="billing-plan-dialog__footer">
          <p className="billing-plan-dialog__note">
            {platformBillingEnabled
              ? "Studio upgrades use Stripe Checkout. Credits apply after payment is confirmed."
              : "Payment is simulated for now — Stripe integration coming soon."}
          </p>
        </footer>
      </div>
    </div>,
    portalRoot
  );
}
