import {
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  Clock,
  User,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { DossierPipelinePhaseStrip } from "@/components/dossiers/DossierPipelinePhaseStrip";
import { approvalStatusChipClass, warningStatusChipClass } from "@/lib/kpiModuleColors";
import type {
  DossierPipelineCheck,
  DossierPipelinePhaseId,
  DossierPipelineStep,
  DossierPipelineStageId,
  DossierStageState,
} from "@/lib/dossiers";
import {
  DOSSIER_PIPELINE_PHASES,
  DOSSIER_PIPELINE_STAGES,
  dossierPipelineCounts,
  dossierPipelinePhases,
  dossierStageDescription,
  dossierStageLabel,
  dossierStageStateLabel,
  firstPipelineFailure,
  isStageBlocked,
  phaseIdForStage,
  phaseStageSummary,
  pipelineBlockedFromStageId,
  stageIdsForPhase,
} from "@/lib/dossiers";
import { cn } from "@/lib/cn";

function stageStateChipClass(state: DossierPipelineStep["state"]): string {
  if (state === "pass") return approvalStatusChipClass("approve");
  if (state === "fail") return approvalStatusChipClass("reject");
  if (state === "waived") return approvalStatusChipClass("muted");
  return warningStatusChipClass();
}

function checkStateChipClass(state: DossierPipelineCheck["state"]): string {
  if (state === "pass") return approvalStatusChipClass("approve");
  if (state === "fail") return approvalStatusChipClass("reject");
  if (state === "waived" || state === "skipped") return approvalStatusChipClass("muted");
  if (state === "pending") return warningStatusChipClass();
  return approvalStatusChipClass("muted");
}

function overviewStatChipClass(kind: "pass" | "fail" | "waived" | "pending"): string {
  if (kind === "pass") return approvalStatusChipClass("approve");
  if (kind === "fail") return approvalStatusChipClass("reject");
  if (kind === "waived") return approvalStatusChipClass("muted");
  return warningStatusChipClass();
}

function checkStatusLabel(state: DossierPipelineCheck["state"]): string {
  if (state === "pass") return "Pass";
  if (state === "fail") return "Fail";
  if (state === "waived") return "Skipped";
  if (state === "skipped") return "Skipped";
  return "Waiting";
}

function formatDuration(ms?: number): string | null {
  if (ms == null) return null;
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function stageHasDetail(step: DossierPipelineStep | undefined): boolean {
  if (!step) return false;
  return (
    Boolean(step.checks?.length) ||
    Boolean(step.failureReason) ||
    Boolean(step.remediation) ||
    Boolean(step.blockedReason) ||
    Boolean(step.evidence?.length) ||
    (Boolean(step.detail) && step.detail !== "—")
  );
}

function phaseHasFailure(
  phaseId: DossierPipelinePhaseId,
  byStage: Map<DossierPipelineStageId, DossierPipelineStep>
): boolean {
  return stageIdsForPhase(phaseId).some((id) => byStage.get(id)?.state === "fail");
}

function defaultOpenPhases(
  byStage: Map<DossierPipelineStageId, DossierPipelineStep>
): Set<DossierPipelinePhaseId> {
  const open = new Set<DossierPipelinePhaseId>();
  for (const phase of DOSSIER_PIPELINE_PHASES) {
    if (phaseHasFailure(phase.id, byStage)) {
      open.add(phase.id);
    }
  }
  return open;
}

function defaultOpenStages(
  byStage: Map<DossierPipelineStageId, DossierPipelineStep>
): Set<DossierPipelineStageId> {
  const open = new Set<DossierPipelineStageId>();
  for (const stage of DOSSIER_PIPELINE_STAGES) {
    if (byStage.get(stage.id)?.state === "fail") {
      open.add(stage.id);
    }
  }
  return open;
}

function PipelineCheckTable({ checks }: { checks: DossierPipelineCheck[] }) {
  return (
    <div className="dossier-pipeline-checks-wrap">
      <table className="dossier-pipeline-checks">
        <thead>
          <tr>
            <th>Check</th>
            <th>Rule</th>
            <th>Expected</th>
            <th>Actual</th>
            <th className="text-right">Result</th>
          </tr>
        </thead>
        <tbody>
          {checks.map((check) => (
            <tr
              key={check.id}
              className={cn(
                check.state === "fail" && "dossier-pipeline-checks__row--fail"
              )}
            >
              <td>
                <div className="font-medium">{check.label}</div>
                {check.detail ? (
                  <div className="dossier-pipeline-checks__detail">{check.detail}</div>
                ) : null}
              </td>
              <td className="tnum text-muted-foreground">{check.ruleRef ?? "—"}</td>
              <td className="tnum">{check.expected ?? "—"}</td>
              <td className="tnum">{check.actual ?? "—"}</td>
              <td className="text-right">
                <span className={checkStateChipClass(check.state)}>
                  {checkStatusLabel(check.state)}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PipelineStageCard({
  order,
  stageId,
  step,
  blocked,
  open,
  onToggle,
  cardRef,
  routeTarget,
  compact = false,
}: {
  order: number;
  stageId: DossierPipelineStageId;
  step: DossierPipelineStep | undefined;
  blocked: boolean;
  open: boolean;
  onToggle: () => void;
  cardRef?: (el: HTMLElement | null) => void;
  routeTarget?: string | null;
  compact?: boolean;
}) {
  const state = step?.state ?? "pending";
  const hasDetail = stageHasDetail(step);
  const showBody = open && hasDetail;

  const cardClass = cn(
    "dossier-pipeline-stage",
    !showBody && "dossier-pipeline-stage--collapsed",
    compact && "dossier-pipeline-stage--compact",
    state === "pass" && "dossier-pipeline-stage--pass",
    state === "fail" && "dossier-pipeline-stage--fail",
    state === "waived" && "dossier-pipeline-stage--waived",
    state === "pending" && "dossier-pipeline-stage--pending",
    blocked && "dossier-pipeline-stage--blocked"
  );

  const summaryLine =
    state === "fail" && step?.failureReason
      ? step.failureReason
      : step?.detail && step.detail !== "—"
        ? step.detail
        : blocked && step?.blockedReason
          ? `Waiting — ${step.blockedReason}`
          : null;

  const showHeadDetail = showBody || (state === "fail" && Boolean(summaryLine));

  return (
    <article
      ref={cardRef}
      className={cardClass}
      data-testid={`stage-${stageId}`}
      id={`dossier-stage-${stageId}`}
    >
      <button
        type="button"
        className="dossier-pipeline-stage__head"
        onClick={() => hasDetail && onToggle()}
        aria-expanded={showBody}
        disabled={!hasDetail}
      >
        <span className={cn("dossier-pipeline-stage__node", `dossier-pipeline-stage__node--${state}`)}>
          {String(order).padStart(2, "0")}
        </span>
        <span className="dossier-pipeline-stage__title-block">
          <span className="dossier-pipeline-stage__title-row">
            <span className="dossier-pipeline-stage__name">{dossierStageLabel(stageId, routeTarget)}</span>
            <span className={stageStateChipClass(state)}>{dossierStageStateLabel(state)}</span>
            {blocked && state === "pending" ? (
              <span className="dossier-pipeline-stage__did-not-run">Did not run</span>
            ) : null}
            {step?.exceptionCode && showHeadDetail ? (
              <span className="dossier-pipeline-stage__code tnum">{step.exceptionCode}</span>
            ) : null}
          </span>
          {showHeadDetail ? (
            <span className="dossier-pipeline-stage__hint">{dossierStageDescription(stageId)}</span>
          ) : null}
          {summaryLine && showHeadDetail ? (
            <span
              className={cn(
                "dossier-pipeline-stage__summary",
                state === "fail" && "dossier-pipeline-stage__summary--fail",
                blocked && "dossier-pipeline-stage__summary--muted"
              )}
            >
              {summaryLine}
            </span>
          ) : null}
        </span>
        {hasDetail ? (
          <span className="dossier-pipeline-stage__chevron">
            {showBody ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
          </span>
        ) : null}
      </button>

      {showBody ? (
        <div className="dossier-pipeline-stage__body">
          {(step?.actor || step?.at || step?.durationMs) && (
            <div className="dossier-pipeline-stage__meta">
              {step?.actor ? (
                <span className="dossier-pipeline-stage__meta-item">
                  <User className="h-3.5 w-3.5" />
                  {step.actor}
                </span>
              ) : null}
              {step?.at ? (
                <span className="dossier-pipeline-stage__meta-item tnum">
                  <Clock className="h-3.5 w-3.5" />
                  {step.at}
                </span>
              ) : null}
              {formatDuration(step?.durationMs) ? (
                <span className="dossier-pipeline-stage__meta-item tnum">
                  {formatDuration(step?.durationMs)}
                </span>
              ) : null}
            </div>
          )}

          {state === "fail" && (step?.failureReason || step?.remediation) ? (
            <div className="dossier-pipeline-failure-plain">
              <div className="dossier-pipeline-failure-plain__title">
                <AlertTriangle className="h-4 w-4 shrink-0" aria-hidden />
                Why this stage failed
              </div>
              {step?.failureReason ? (
                <p className="dossier-pipeline-failure-plain__reason">{step.failureReason}</p>
              ) : null}
              {step?.remediation ? (
                <p className="dossier-pipeline-failure-plain__fix">
                  <span className="font-semibold">What to do: </span>
                  {step.remediation}
                </p>
              ) : null}
            </div>
          ) : null}

          {step?.blockedReason && state === "pending" ? (
            <div className="dossier-pipeline-blocked-box">Waiting — {step.blockedReason}</div>
          ) : null}

          {step?.checks && step.checks.length > 0 ? (
            <div>
              <p className="dossier-pipeline-stage__checks-label">Checks at this stage</p>
              <PipelineCheckTable checks={step.checks} />
            </div>
          ) : null}

          {step?.evidence && step.evidence.length > 0 ? (
            <div className="dossier-pipeline-evidence">
              <p className="dossier-pipeline-stage__checks-label">Evidence</p>
              <div className="dossier-pipeline-evidence__chips">
                {step.evidence.map((item) => (
                  <span key={`${item.label}-${item.ref}`} className="dossier-pipeline-evidence__chip">
                    <span className="text-muted-foreground">{item.label}:</span>{" "}
                    <span className="tnum font-medium">{item.ref}</span>
                  </span>
                ))}
              </div>
            </div>
          ) : null}
        </div>
      ) : null}
    </article>
  );
}

function CompletedStagesGroup({
  count,
  open,
  onToggle,
  children,
}: {
  count: number;
  open: boolean;
  onToggle: () => void;
  children: ReactNode;
}) {
  if (count <= 0) return null;
  return (
    <div className="dossier-pipeline-completed-group">
      <button
        type="button"
        className="dossier-pipeline-completed-group__head"
        onClick={onToggle}
        aria-expanded={open}
      >
        <span className="dossier-pipeline-completed-group__label">
          {count} completed stage{count === 1 ? "" : "s"}
        </span>
        <span className="dossier-pipeline-completed-group__chevron" aria-hidden>
          {open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
        </span>
      </button>
      {open ? <div className="dossier-pipeline-completed-group__body">{children}</div> : null}
    </div>
  );
}

function splitPhaseStages(
  phaseStages: (typeof DOSSIER_PIPELINE_STAGES)[number][],
  byStage: Map<DossierPipelineStageId, DossierPipelineStep>
) {
  const failedStage = phaseStages.find((stage) => byStage.get(stage.id)?.state === "fail");
  const failOrder = failedStage?.order ?? null;
  const completedBeforeFail: (typeof DOSSIER_PIPELINE_STAGES)[number][] = [];
  const failed: (typeof DOSSIER_PIPELINE_STAGES)[number][] = [];
  const rest: (typeof DOSSIER_PIPELINE_STAGES)[number][] = [];

  for (const stage of phaseStages) {
    const state = byStage.get(stage.id)?.state ?? "pending";
    if (state === "fail") {
      failed.push(stage);
    } else if (
      failOrder != null &&
      stage.order < failOrder &&
      (state === "pass" || state === "waived")
    ) {
      completedBeforeFail.push(stage);
    } else {
      rest.push(stage);
    }
  }

  return { completedBeforeFail, failed, rest };
}

function PipelinePhaseStep({
  index,
  phaseId,
  label,
  state,
  summary,
  open,
  onToggle,
  isLast,
  children,
}: {
  index: number;
  phaseId: DossierPipelinePhaseId;
  label: string;
  state: DossierStageState;
  summary: string;
  open: boolean;
  onToggle: () => void;
  isLast: boolean;
  children: ReactNode;
}) {
  return (
    <div
      className={cn(
        "dossier-pipeline-step",
        open && "dossier-pipeline-step--open",
        state === "fail" && "dossier-pipeline-step--fail"
      )}
      data-testid={`phase-${phaseId}`}
    >
      <div className="dossier-pipeline-step__rail" aria-hidden>
        <span className="dossier-pipeline-step__line dossier-pipeline-step__line--top" />
        <span className={cn("dossier-pipeline-step__marker", `dossier-pipeline-step__marker--${state}`)}>
          {index}
        </span>
        {!isLast ? <span className="dossier-pipeline-step__line dossier-pipeline-step__line--bottom" /> : null}
      </div>
      <div className="dossier-pipeline-step__content">
        <div className="dossier-pipeline-step__heading">
          <button
            type="button"
            className="dossier-pipeline-step__heading-toggle"
            onClick={onToggle}
            aria-expanded={open}
          >
            <div className="dossier-pipeline-step__heading-main">
              <div className="dossier-pipeline-step__title-row">
                <h3 className="dossier-pipeline-step__label">{label}</h3>
                <span className={stageStateChipClass(state)}>{dossierStageStateLabel(state)}</span>
              </div>
              {!open ? <p className="dossier-pipeline-step__summary">{summary}</p> : null}
            </div>
            <span className="dossier-pipeline-step__chevron" aria-hidden>
              {open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
            </span>
          </button>
        </div>
        {open ? <div className="dossier-pipeline-step__panel">{children}</div> : null}
      </div>
    </div>
  );
}

type DossierPipelineOverviewProps = {
  pipeline: DossierPipelineStep[];
  routeTarget?: string | null;
  onJumpToFailure?: () => void;
  onExpandAll?: () => void;
  onCollapseAll?: () => void;
};

export function DossierPipelineOverview({
  pipeline,
  routeTarget,
  onJumpToFailure,
  onExpandAll,
  onCollapseAll,
}: DossierPipelineOverviewProps) {
  const counts = useMemo(() => dossierPipelineCounts(pipeline), [pipeline]);
  const pending = pipeline.filter((s) => s.state === "pending").length;
  const firstFail = firstPipelineFailure(pipeline);

  return (
    <div className="dossier-pipeline-overview">
      <DossierPipelinePhaseStrip
        pipeline={pipeline}
        variant="connected"
        className="dossier-pipeline-overview__phases dossier-card-pipeline--detail"
      />
      <div className="dossier-pipeline-overview__row">
        <div className="dossier-pipeline-overview__stats">
          <span className={overviewStatChipClass("pass")}>{counts.pass} complete</span>
          {counts.fail > 0 ? (
            <span className={overviewStatChipClass("fail")}>{counts.fail} failed</span>
          ) : null}
          {counts.waived > 0 ? (
            <span className={overviewStatChipClass("waived")}>{counts.waived} skipped</span>
          ) : null}
          {pending > 0 ? (
            <span className={overviewStatChipClass("pending")}>{pending} waiting</span>
          ) : null}
        </div>
        <div className="dossier-pipeline-overview__actions">
          {firstFail && onJumpToFailure ? (
            <button type="button" className="dossier-pipeline-overview__link" onClick={onJumpToFailure}>
              Jump to failure
            </button>
          ) : null}
          {onExpandAll ? (
            <button type="button" className="dossier-pipeline-overview__link" onClick={onExpandAll}>
              Expand all
            </button>
          ) : null}
          {onCollapseAll ? (
            <button type="button" className="dossier-pipeline-overview__link" onClick={onCollapseAll}>
              Collapse all
            </button>
          ) : null}
        </div>
      </div>
      {firstFail ? (
        <div className="dossier-pipeline-overview__blocker">
          <AlertTriangle className="h-4 w-4 shrink-0 ds-warning-icon" aria-hidden />
          <div className="dossier-pipeline-overview__blocker-main">
            <div className="dossier-pipeline-overview__blocker-head">
              <span className="dossier-pipeline-overview__blocker-title">
                Failed at stage{" "}
                {String(
                  DOSSIER_PIPELINE_STAGES.find((s) => s.id === firstFail.stageId)?.order ?? ""
                ).padStart(2, "0")}{" "}
                — {dossierStageLabel(firstFail.stageId, routeTarget)}
              </span>
              {firstFail.exceptionCode ? (
                <span className={approvalStatusChipClass("muted")}>{firstFail.exceptionCode}</span>
              ) : null}
            </div>
            <p className="dossier-pipeline-overview__blocker-detail">
              {firstFail.failureReason ?? firstFail.detail}
            </p>
          </div>
        </div>
      ) : null}
    </div>
  );
}

export const DOSSIER_PIPELINE_FOCUS_STAGE_EVENT = "dossier-pipeline-focus-stage";
export const DOSSIER_PIPELINE_FOCUS_PHASE_EVENT = "dossier-pipeline-focus-phase";

export function DossierPipelineTimeline({
  pipeline,
  routeTarget,
  layout = "page",
}: {
  pipeline: DossierPipelineStep[];
  routeTarget?: string | null;
  layout?: "page" | "drawer";
}) {
  const byStage = useMemo(
    () => new Map(pipeline.map((step) => [step.stageId, step])),
    [pipeline]
  );

  const [openPhases, setOpenPhases] = useState(() => defaultOpenPhases(byStage));
  const [openStages, setOpenStages] = useState(() => defaultOpenStages(byStage));
  const [openCompletedGroups, setOpenCompletedGroups] = useState<Set<DossierPipelinePhaseId>>(
    () => new Set()
  );
  const stageRefs = useRef<Partial<Record<DossierPipelineStageId, HTMLElement | null>>>({});

  const phases = useMemo(() => dossierPipelinePhases(pipeline), [pipeline]);

  useEffect(() => {
    const map = new Map(pipeline.map((step) => [step.stageId, step]));
    setOpenPhases(defaultOpenPhases(map));
    setOpenStages(defaultOpenStages(map));
    setOpenCompletedGroups(new Set());
  }, [pipeline]);

  const focusPhase = useCallback((phaseId: DossierPipelinePhaseId, openPanel = true) => {
    if (openPanel) {
      setOpenPhases((prev) => new Set(prev).add(phaseId));
    }
    requestAnimationFrame(() => {
      document
        .querySelector(`[data-testid="phase-${phaseId}"]`)
        ?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    });
  }, []);

  const focusStage = useCallback(
    (stageId: DossierPipelineStageId) => {
      const phaseId = phaseIdForStage(stageId);
      focusPhase(phaseId);
      setOpenStages((prev) => new Set(prev).add(stageId));
      requestAnimationFrame(() => {
        stageRefs.current[stageId]?.scrollIntoView({ behavior: "smooth", block: "nearest" });
      });
    },
    [focusPhase]
  );

  useEffect(() => {
    const handler = (event: Event) => {
      const stageId = (event as CustomEvent<{ stageId: DossierPipelineStageId }>).detail?.stageId;
      if (!stageId) return;
      focusStage(stageId);
    };
    window.addEventListener(DOSSIER_PIPELINE_FOCUS_STAGE_EVENT, handler);
    return () => window.removeEventListener(DOSSIER_PIPELINE_FOCUS_STAGE_EVENT, handler);
  }, [focusStage]);

  useEffect(() => {
    const handler = (event: Event) => {
      const phaseId = (event as CustomEvent<{ phaseId: DossierPipelinePhaseId }>).detail?.phaseId;
      if (!phaseId) return;
      focusPhase(phaseId);
    };
    window.addEventListener(DOSSIER_PIPELINE_FOCUS_PHASE_EVENT, handler);
    return () => window.removeEventListener(DOSSIER_PIPELINE_FOCUS_PHASE_EVENT, handler);
  }, [focusPhase]);

  const togglePhase = useCallback((phaseId: DossierPipelinePhaseId) => {
    setOpenPhases((prev) => {
      const next = new Set(prev);
      if (next.has(phaseId)) next.delete(phaseId);
      else next.add(phaseId);
      return next;
    });
  }, []);

  const toggleStage = useCallback((stageId: DossierPipelineStageId) => {
    setOpenStages((prev) => {
      const next = new Set(prev);
      if (next.has(stageId)) next.delete(stageId);
      else next.add(stageId);
      return next;
    });
  }, []);

  const jumpToFailure = useCallback(() => {
    const fail = firstPipelineFailure(pipeline);
    if (!fail) return;
    focusStage(fail.stageId);
  }, [pipeline, focusStage]);

  const expandAll = useCallback(() => {
    setOpenPhases(new Set(DOSSIER_PIPELINE_PHASES.map((phase) => phase.id)));
    setOpenCompletedGroups(new Set(DOSSIER_PIPELINE_PHASES.map((phase) => phase.id)));
    const ids = DOSSIER_PIPELINE_STAGES.map((stage) => stage.id).filter((id) =>
      stageHasDetail(byStage.get(id))
    );
    setOpenStages(new Set(ids));
  }, [byStage]);

  const collapseAll = useCallback(() => {
    const map = new Map(pipeline.map((step) => [step.stageId, step]));
    setOpenPhases(defaultOpenPhases(map));
    setOpenStages(defaultOpenStages(map));
    setOpenCompletedGroups(new Set());
  }, [pipeline]);

  return (
    <div
      className={cn(
        "dossier-pipeline-detail",
        layout === "drawer" && "invoice-drawer-dossier-pipeline"
      )}
      data-testid={layout === "drawer" ? "invoice-drawer-dossier-pipeline" : undefined}
    >
      {layout === "page" ? (
        <DossierPipelineOverview
          pipeline={pipeline}
          routeTarget={routeTarget}
          onJumpToFailure={jumpToFailure}
          onExpandAll={expandAll}
          onCollapseAll={collapseAll}
        />
      ) : null}
      <div className="dossier-pipeline-stepper" data-testid="pipeline-phase-stepper">
        {DOSSIER_PIPELINE_PHASES.map((phase, index) => {
          const phaseMeta = phases.find((row) => row.phaseId === phase.id);
          const state = phaseMeta?.state ?? "pending";
          const phaseStages = DOSSIER_PIPELINE_STAGES.filter((stage) => stage.phase === phase.id);
          const open = openPhases.has(phase.id);
          const { completedBeforeFail, failed, rest } = splitPhaseStages(phaseStages, byStage);

          const renderStageCard = (stage: (typeof DOSSIER_PIPELINE_STAGES)[number], compact = false) => {
            const step = byStage.get(stage.id);
            const blocked =
              pipelineBlockedFromStageId(pipeline, stage.id) && isStageBlocked(step);
            return (
              <PipelineStageCard
                key={stage.id}
                order={stage.order}
                stageId={stage.id}
                step={step}
                blocked={blocked}
                open={openStages.has(stage.id)}
                onToggle={() => toggleStage(stage.id)}
                routeTarget={routeTarget}
                compact={compact}
                cardRef={(el) => {
                  stageRefs.current[stage.id] = el;
                }}
              />
            );
          };

          return (
            <PipelinePhaseStep
              key={phase.id}
              index={index + 1}
              phaseId={phase.id}
              label={phase.label}
              state={state}
              summary={phaseStageSummary(pipeline, phase.id, routeTarget)}
              open={open}
              onToggle={() => togglePhase(phase.id)}
              isLast={index === DOSSIER_PIPELINE_PHASES.length - 1}
            >
              <div className="dossier-pipeline-step__stages">
                {completedBeforeFail.length > 0 ? (
                  <CompletedStagesGroup
                    count={completedBeforeFail.length}
                    open={openCompletedGroups.has(phase.id)}
                    onToggle={() =>
                      setOpenCompletedGroups((prev) => {
                        const next = new Set(prev);
                        if (next.has(phase.id)) next.delete(phase.id);
                        else next.add(phase.id);
                        return next;
                      })
                    }
                  >
                    {completedBeforeFail.map((stage) => renderStageCard(stage, true))}
                  </CompletedStagesGroup>
                ) : null}
                {failed.map((stage) => renderStageCard(stage))}
                {rest.map((stage) => renderStageCard(stage, true))}
              </div>
            </PipelinePhaseStep>
          );
        })}
      </div>
    </div>
  );
}
