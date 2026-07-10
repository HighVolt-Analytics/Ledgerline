import { AlertTriangle, CheckCircle2, Clock, Loader2, PauseCircle } from "lucide-react";

import { Button } from "@/components/ui/button";

import type { DossierSummary } from "@/lib/dossiers";

import {

  DOSSIER_PIPELINE_STAGES,

  dossierBlockerFromSummary,

  dossierOutcomeLabel,

  dossierStageLabel,

  pipelineActiveStage,

  pipelineProgressSummary,

} from "@/lib/dossiers";

import { cn } from "@/lib/cn";



type PipelineStatusKpiProps = {

  dossier: DossierSummary;

  onOpenInvoice?: () => void;

  onJumpToFailure?: () => void;

};



const KPI_ACTION_CLASS =

  "h-6 px-2 text-[10px] font-medium leading-none shadow-none";



export function DossierPipelineStatusKpi({

  dossier,

  onOpenInvoice,

  onJumpToFailure,

}: PipelineStatusKpiProps) {

  const blocker = dossierBlockerFromSummary(dossier);

  const active = pipelineActiveStage(dossier.pipeline);

  const progress = pipelineProgressSummary(dossier.pipeline, dossier.routeTarget);



  if (blocker) {

    const stageLabel = dossierStageLabel(blocker.stageId, dossier.routeTarget);

    const stageOrder = DOSSIER_PIPELINE_STAGES.find((s) => s.id === blocker.stageId)?.order;

    const stageRef = String(stageOrder ?? "").padStart(2, "0");

    const isFailed = blocker.step.state === "fail";

    const title = isFailed

      ? `Failed at stage ${stageRef} — ${stageLabel}`

      : `Blocked at stage ${stageRef} — ${stageLabel}`;

    const jumpLabel = isFailed ? "Failed stage" : "Blocked stage";



    return (
      <div
        className={cn("dossier-kpi-card", isFailed && "dossier-kpi-card--fail")}
        data-testid="dossier-pipeline-status-kpi"
      >
        <div className="dossier-kpi-fail-head">
          <AlertTriangle
            className={cn(
              "h-3.5 w-3.5 shrink-0 mt-0.5",
              isFailed ? "text-destructive" : "ds-warning-icon"
            )}
            aria-hidden
          />
          <div className="min-w-0">
            <p
              className={cn(
                "dossier-kpi-fail-head__title",
                !isFailed && "dossier-kpi-fail-head__title--plain"
              )}
            >
              {title}
            </p>
            <p className="dossier-kpi-fail-head__detail dossier-kpi-sub--clamp">{blocker.reason}</p>
          </div>
        </div>

        {blocker.remediation ? (

          <p className="dossier-kpi-sub dossier-kpi-sub--clamp">

            <span className="font-medium text-foreground/90">What to do: </span>

            {blocker.remediation}

          </p>

        ) : null}

        <div className="dossier-kpi-actions dossier-kpi-actions--parallel">

          {onJumpToFailure ? (

            <Button

              type="button"

              variant="outline"

              size="sm"

              className={cn(

                KPI_ACTION_CLASS,

                "dossier-kpi-action-btn border-border bg-card text-foreground hover:bg-muted/40"

              )}

              onClick={onJumpToFailure}

            >

              {jumpLabel}

            </Button>

          ) : null}

          {dossier.invoiceId && onOpenInvoice ? (

            <Button

              type="button"

              variant="default"

              size="sm"

              className={cn(KPI_ACTION_CLASS, "dossier-kpi-action-btn")}

              onClick={onOpenInvoice}

            >

              Open invoice

            </Button>

          ) : null}

        </div>

      </div>

    );

  }



  if (dossier.outcome === "parked") {

    return (

      <div className="dossier-kpi-card dossier-kpi-card--parked" data-testid="dossier-pipeline-status-kpi">

        <div className="dossier-kpi-value dossier-kpi-value--compact dossier-kpi-value--lead">

          <PauseCircle className="h-3.5 w-3.5 shrink-0" aria-hidden />

          <span>Parked</span>

        </div>

        {dossier.outcomeBanner ? (

          <p className="dossier-kpi-sub dossier-kpi-sub--clamp">{dossier.outcomeBanner}</p>

        ) : null}

        <p className="dossier-kpi-sub tnum">{progress}</p>

      </div>

    );

  }



  if (dossier.outcome === "auto_posted" || dossier.outcome === "manual_posted") {

    return (

      <div className="dossier-kpi-card dossier-kpi-card--success" data-testid="dossier-pipeline-status-kpi">

        <div className="dossier-kpi-value dossier-kpi-value--compact dossier-kpi-value--lead">

          <CheckCircle2 className="h-3.5 w-3.5 shrink-0" aria-hidden />

          <span>{dossierOutcomeLabel(dossier.outcome)}</span>

        </div>

        <p className="dossier-kpi-sub dossier-kpi-sub--clamp">

          {dossier.outcomeBanner ?? "All pipeline stages completed successfully."}

        </p>

        <p className="dossier-kpi-sub tnum">{progress}</p>

      </div>

    );

  }



  const activeLabel = active

    ? dossierStageLabel(active.stageId, dossier.routeTarget)

    : "starting";



  return (

    <div className="dossier-kpi-card" data-testid="dossier-pipeline-status-kpi">

      <div className="dossier-kpi-value dossier-kpi-value--compact dossier-kpi-value--lead">

        {active?.step.state === "pass" ? (

          <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin" aria-hidden />

        ) : (

          <Clock className="h-3.5 w-3.5 shrink-0" aria-hidden />

        )}

        <span>Processing — {activeLabel}</span>

      </div>

      {dossier.outcomeBanner ? (

        <p className={cn("dossier-kpi-sub dossier-kpi-sub--clamp")}>{dossier.outcomeBanner}</p>

      ) : null}

      <p className="dossier-kpi-sub tnum">{progress}</p>

      {dossier.invoiceId && onOpenInvoice ? (

        <div className="dossier-kpi-actions">

          <Button

            type="button"

            variant="outline"

            size="sm"

            className={cn(

              KPI_ACTION_CLASS,

              "border-border bg-card text-foreground hover:bg-muted/40"

            )}

            onClick={onOpenInvoice}

          >

            Open invoice

          </Button>

        </div>

      ) : null}

    </div>

  );

}

