import { AlertTriangle, ArrowDown, CheckCircle2, Clock, Loader2, PauseCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { DossierSummary } from "@/lib/dossiers";
import {
  dossierBlockerFromSummary,
  dossierOutcomeLabel,
  dossierStageLabel,
  pipelineActiveStage,
  pipelineProgressSummary,
} from "@/lib/dossiers";
import { cn } from "@/lib/cn";

type Props = {
  dossier: DossierSummary;
  onOpenInvoice?: () => void;
  onJumpToFailure?: () => void;
};

export function DossierStatusHero({ dossier, onOpenInvoice, onJumpToFailure }: Props) {
  const blocker = dossierBlockerFromSummary(dossier);
  const active = pipelineActiveStage(dossier.pipeline);
  const progress = pipelineProgressSummary(dossier.pipeline, dossier.routeTarget);

  if (blocker) {
    const stageLabel = dossierStageLabel(blocker.stageId, dossier.routeTarget);
    return (
      <div
        className="dossier-status-hero dossier-status-hero--fail"
        data-testid="dossier-status-hero"
      >
        <div className="dossier-status-hero__icon">
          <AlertTriangle className="h-5 w-5" aria-hidden />
        </div>
        <div className="dossier-status-hero__body">
          <p className="dossier-status-hero__title">Failed at {stageLabel}</p>
          <p className="dossier-status-hero__message">{blocker.reason}</p>
          {blocker.remediation ? (
            <p className="dossier-status-hero__remediation">
              <span className="font-semibold">What to do: </span>
              {blocker.remediation}
            </p>
          ) : null}
          <div className="dossier-status-hero__meta">
            {blocker.exceptionCode ? (
              <span className="dossier-pipeline-stage__code tnum">{blocker.exceptionCode}</span>
            ) : null}
            <span className="dossier-status-hero__progress">{progress}</span>
          </div>
          <div className="dossier-status-hero__actions">
            {onJumpToFailure ? (
              <Button type="button" variant="outline" size="sm" className="h-8 text-xs" onClick={onJumpToFailure}>
                <ArrowDown className="h-3.5 w-3.5 mr-1.5" />
                Jump to failed stage
              </Button>
            ) : null}
            {dossier.invoiceId && onOpenInvoice ? (
              <Button type="button" variant="default" size="sm" className="h-8 text-xs" onClick={onOpenInvoice}>
                Open invoice
              </Button>
            ) : null}
          </div>
        </div>
      </div>
    );
  }

  if (dossier.outcome === "parked") {
    return (
      <div className="dossier-status-hero dossier-status-hero--parked" data-testid="dossier-status-hero">
        <div className="dossier-status-hero__icon">
          <PauseCircle className="h-5 w-5" aria-hidden />
        </div>
        <div className="dossier-status-hero__body">
          <p className="dossier-status-hero__title">Parked</p>
          {dossier.outcomeBanner ? (
            <p className="dossier-status-hero__message">{dossier.outcomeBanner}</p>
          ) : null}
          <p className="dossier-status-hero__progress">{progress}</p>
        </div>
      </div>
    );
  }

  if (dossier.outcome === "auto_posted" || dossier.outcome === "manual_posted") {
    return (
      <div className="dossier-status-hero dossier-status-hero--success" data-testid="dossier-status-hero">
        <div className="dossier-status-hero__icon">
          <CheckCircle2 className="h-5 w-5" aria-hidden />
        </div>
        <div className="dossier-status-hero__body">
          <p className="dossier-status-hero__title">{dossierOutcomeLabel(dossier.outcome)}</p>
          {dossier.outcomeBanner ? (
            <p className="dossier-status-hero__message">{dossier.outcomeBanner}</p>
          ) : (
            <p className="dossier-status-hero__message">All pipeline stages completed successfully.</p>
          )}
          <p className="dossier-status-hero__progress">{progress}</p>
        </div>
      </div>
    );
  }

  const activeLabel = active
    ? dossierStageLabel(active.stageId, dossier.routeTarget)
    : "starting";

  return (
    <div className="dossier-status-hero dossier-status-hero--progress" data-testid="dossier-status-hero">
      <div className="dossier-status-hero__icon">
        {active?.step.state === "pass" ? (
          <Loader2 className="h-5 w-5 animate-spin" aria-hidden />
        ) : (
          <Clock className="h-5 w-5" aria-hidden />
        )}
      </div>
      <div className="dossier-status-hero__body">
        <p className="dossier-status-hero__title">Processing — currently at {activeLabel}</p>
        {dossier.outcomeBanner ? (
          <p className={cn("dossier-status-hero__message", "text-muted-foreground")}>
            {dossier.outcomeBanner}
          </p>
        ) : null}
        <p className="dossier-status-hero__progress">{progress}</p>
        {dossier.invoiceId && onOpenInvoice ? (
          <div className="dossier-status-hero__actions">
            <Button type="button" variant="outline" size="sm" className="h-8 text-xs" onClick={onOpenInvoice}>
              Open invoice
            </Button>
          </div>
        ) : null}
      </div>
    </div>
  );
}
