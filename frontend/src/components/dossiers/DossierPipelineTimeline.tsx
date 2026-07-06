import {
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  Clock,
  User,
} from "lucide-react";
import { useCallback, useMemo, useRef, useState } from "react";
import { DossierPipelinePhaseStrip } from "@/components/dossiers/DossierPipelinePhaseStrip";
import { StatusPill, pillTones } from "@/components/StatusPill";
import type {
  DossierPipelineCheck,
  DossierPipelinePhaseId,
  DossierPipelineStep,
  DossierPipelineStageId,
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
  phaseStageSummary,
  pipelineBlockedFromStageId,
  stageShouldDefaultOpen,
} from "@/lib/dossiers";
import { cn } from "@/lib/cn";

function stageStatusTone(state: DossierPipelineStep["state"]): string {
  if (state === "pass") return pillTones.ok;
  if (state === "fail") return pillTones.bad;
  if (state === "waived") return pillTones.amber;
  return pillTones.muted;
}

function checkStatusTone(state: DossierPipelineCheck["state"]): string {
  if (state === "pass") return pillTones.ok;
  if (state === "fail") return pillTones.bad;
  if (state === "waived") return pillTones.amber;
  if (state === "skipped") return pillTones.muted;
  return pillTones.muted;
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

function defaultOpenStages(
  pipeline: DossierPipelineStep[],
  byStage: Map<DossierPipelineStageId, DossierPipelineStep>,
  focusMode: boolean
): Set<DossierPipelineStageId> {
  const open = new Set<DossierPipelineStageId>();
  const fail = firstPipelineFailure(pipeline);

  if (focusMode && fail) {
    open.add(fail.stageId);
    const failOrder =
      DOSSIER_PIPELINE_STAGES.find((stage) => stage.id === fail.stageId)?.order ?? 0;
    let downstream = 0;
    for (const stage of DOSSIER_PIPELINE_STAGES) {
      if (stage.order <= failOrder) continue;
      const step = byStage.get(stage.id);
      if (isStageBlocked(step)) {
        open.add(stage.id);
        downstream += 1;
        if (downstream >= 2) break;
      }
    }
    return open;
  }

  for (const stage of DOSSIER_PIPELINE_STAGES) {
    const step = byStage.get(stage.id);
    const blocked =
      pipelineBlockedFromStageId(pipeline, stage.id) && isStageBlocked(step);
    if (stageShouldDefaultOpen(step, blocked)) {
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
                <StatusPill className={checkStatusTone(check.state)}>
                  {checkStatusLabel(check.state)}
                </StatusPill>
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
  hiddenInFocus,
}: {
  order: number;
  stageId: DossierPipelineStageId;
  step: DossierPipelineStep | undefined;
  blocked: boolean;
  open: boolean;
  onToggle: () => void;
  cardRef?: (el: HTMLElement | null) => void;
  routeTarget?: string | null;
  hiddenInFocus?: boolean;
}) {
  if (hiddenInFocus) return null;

  const state = step?.state ?? "pending";
  const hasDetail = stageHasDetail(step);

  const cardClass = cn(
    "dossier-pipeline-stage",
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
        aria-expanded={open}
        disabled={!hasDetail}
      >
        <span className={cn("dossier-pipeline-stage__node", `dossier-pipeline-stage__node--${state}`)}>
          {String(order).padStart(2, "0")}
        </span>
        <span className="dossier-pipeline-stage__title-block">
          <span className="dossier-pipeline-stage__title-row">
            <span className="dossier-pipeline-stage__name">{dossierStageLabel(stageId, routeTarget)}</span>
            <StatusPill className={stageStatusTone(state)}>{dossierStageStateLabel(state)}</StatusPill>
            {blocked && state === "pending" ? (
              <span className="dossier-pipeline-stage__did-not-run">Did not run</span>
            ) : null}
            {step?.exceptionCode ? (
              <span className="dossier-pipeline-stage__code tnum">{step.exceptionCode}</span>
            ) : null}
          </span>
          <span className="dossier-pipeline-stage__hint">{dossierStageDescription(stageId)}</span>
          {summaryLine ? (
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
            {open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
          </span>
        ) : null}
      </button>

      {open && hasDetail ? (
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
            <div className="dossier-pipeline-failure-box">
              <div className="dossier-pipeline-failure-box__title">
                <AlertTriangle className="h-4 w-4 shrink-0" />
                Why this stage failed
              </div>
              {step?.failureReason ? (
                <p className="dossier-pipeline-failure-box__reason">{step.failureReason}</p>
              ) : null}
              {step?.remediation ? (
                <p className="dossier-pipeline-failure-box__fix">
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

function PassedStagesSummary({
  count,
  expanded,
  onToggle,
}: {
  count: number;
  expanded: boolean;
  onToggle: () => void;
}) {
  if (count <= 0) return null;
  return (
    <button
      type="button"
      className="dossier-pipeline-passed-summary"
      onClick={onToggle}
      aria-expanded={expanded}
    >
      <span className="dossier-pipeline-passed-summary__label">
        {count} stage{count === 1 ? "" : "s"} completed
      </span>
      <span className="dossier-pipeline-passed-summary__action">
        {expanded ? "Hide" : "Show"}
      </span>
    </button>
  );
}

type DossierPipelineOverviewProps = {
  pipeline: DossierPipelineStep[];
  routeTarget?: string | null;
  focusMode: boolean;
  onToggleFocusMode: () => void;
  onJumpToFailure?: () => void;
  onExpandAll?: () => void;
  onCollapseAll?: () => void;
};

export function DossierPipelineOverview({
  pipeline,
  routeTarget,
  focusMode,
  onToggleFocusMode,
  onJumpToFailure,
  onExpandAll,
  onCollapseAll,
}: DossierPipelineOverviewProps) {
  const counts = useMemo(() => dossierPipelineCounts(pipeline), [pipeline]);
  const pending = pipeline.filter((s) => s.state === "pending").length;
  const firstFail = firstPipelineFailure(pipeline);
  const hasFailure = Boolean(firstFail);

  return (
    <div className="dossier-pipeline-overview">
      <DossierPipelinePhaseStrip pipeline={pipeline} className="dossier-pipeline-overview__phases" />
      <div className="dossier-pipeline-overview__row">
        <div className="dossier-pipeline-overview__stats">
          <span className="dossier-pipeline-overview__stat dossier-pipeline-overview__stat--pass">
            {counts.pass} complete
          </span>
          {counts.fail > 0 ? (
            <span className="dossier-pipeline-overview__stat dossier-pipeline-overview__stat--fail">
              {counts.fail} failed
            </span>
          ) : null}
          {counts.waived > 0 ? (
            <span className="dossier-pipeline-overview__stat dossier-pipeline-overview__stat--waived">
              {counts.waived} skipped
            </span>
          ) : null}
          {pending > 0 ? (
            <span className="dossier-pipeline-overview__stat dossier-pipeline-overview__stat--pending">
              {pending} waiting
            </span>
          ) : null}
        </div>
        <div className="dossier-pipeline-overview__actions">
          {hasFailure ? (
            <button type="button" className="dossier-pipeline-overview__link" onClick={onToggleFocusMode}>
              {focusMode ? "Show all stages" : "Focus on problem"}
            </button>
          ) : null}
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
          <AlertTriangle className="h-4 w-4 shrink-0" />
          <div>
            <span className="font-semibold">
              Failed at stage {String(
                DOSSIER_PIPELINE_STAGES.find((s) => s.id === firstFail.stageId)?.order ?? ""
              ).padStart(2, "0")}{" "}
              — {dossierStageLabel(firstFail.stageId, routeTarget)}
            </span>
            {firstFail.exceptionCode ? (
              <span className="dossier-pipeline-stage__code tnum ml-2">{firstFail.exceptionCode}</span>
            ) : null}
            <p className="dossier-pipeline-overview__blocker-detail">
              {firstFail.failureReason ?? firstFail.detail}
            </p>
          </div>
        </div>
      ) : null}
    </div>
  );
}

export function DossierPipelineTimeline({
  pipeline,
  routeTarget,
}: {
  pipeline: DossierPipelineStep[];
  routeTarget?: string | null;
}) {
  const byStage = useMemo(
    () => new Map(pipeline.map((step) => [step.stageId, step])),
    [pipeline]
  );
  const hasFailure = Boolean(firstPipelineFailure(pipeline));

  const [focusMode, setFocusMode] = useState(hasFailure);
  const [showPassedStages, setShowPassedStages] = useState(false);
  const [openStages, setOpenStages] = useState(() =>
    defaultOpenStages(pipeline, byStage, hasFailure)
  );
  const stageRefs = useRef<Partial<Record<DossierPipelineStageId, HTMLElement | null>>>({});

  const phases = useMemo(() => dossierPipelinePhases(pipeline), [pipeline]);

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
    setOpenStages((prev) => new Set(prev).add(fail.stageId));
    requestAnimationFrame(() => {
      stageRefs.current[fail.stageId]?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    });
  }, [pipeline]);

  const toggleFocusMode = useCallback(() => {
    setFocusMode((prev) => {
      const next = !prev;
      setOpenStages(defaultOpenStages(pipeline, byStage, next));
      setShowPassedStages(false);
      return next;
    });
  }, [pipeline, byStage]);

  const expandAll = useCallback(() => {
    setFocusMode(false);
    setShowPassedStages(true);
    const ids = DOSSIER_PIPELINE_STAGES.map((s) => s.id).filter((id) =>
      stageHasDetail(byStage.get(id))
    );
    setOpenStages(new Set(ids));
  }, [byStage]);

  const collapseAll = useCallback(() => {
    setOpenStages(new Set());
  }, []);

  const passedStageIds = useMemo(() => {
    return DOSSIER_PIPELINE_STAGES.filter((stage) => byStage.get(stage.id)?.state === "pass").map(
      (stage) => stage.id
    );
  }, [byStage]);

  const shouldHidePassed = focusMode && !showPassedStages;

  return (
    <div className="dossier-pipeline-detail">
      <DossierPipelineOverview
        pipeline={pipeline}
        routeTarget={routeTarget}
        focusMode={focusMode}
        onToggleFocusMode={toggleFocusMode}
        onJumpToFailure={jumpToFailure}
        onExpandAll={expandAll}
        onCollapseAll={collapseAll}
      />
      <div className="dossier-pipeline-stages">
        {shouldHidePassed && passedStageIds.length > 0 ? (
          <PassedStagesSummary
            count={passedStageIds.length}
            expanded={showPassedStages}
            onToggle={() => setShowPassedStages((v) => !v)}
          />
        ) : null}
        {DOSSIER_PIPELINE_PHASES.map((phase) => {
          const phaseMeta = phases.find((p) => p.phaseId === phase.id);
          const phaseStages = DOSSIER_PIPELINE_STAGES.filter((s) => s.phase === phase.id);

          return (
            <section key={phase.id} className="dossier-pipeline-phase" data-testid={`phase-${phase.id}`}>
              <header className="dossier-pipeline-phase__head">
                <span className="dossier-pipeline-phase__name">{phase.label}</span>
                {phaseMeta ? (
                  <StatusPill className={stageStatusTone(phaseMeta.state)}>
                    {dossierStageStateLabel(phaseMeta.state)}
                  </StatusPill>
                ) : null}
                <span className="dossier-pipeline-phase__summary">
                  {phaseStageSummary(pipeline, phase.id as DossierPipelinePhaseId, routeTarget)}
                </span>
              </header>

              {phaseStages.map((stage) => {
                const step = byStage.get(stage.id);
                const blocked =
                  pipelineBlockedFromStageId(pipeline, stage.id) && isStageBlocked(step);
                const hidePassed =
                  shouldHidePassed && step?.state === "pass" && !showPassedStages;

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
                    hiddenInFocus={hidePassed}
                    cardRef={(el) => {
                      stageRefs.current[stage.id] = el;
                    }}
                  />
                );
              })}
            </section>
          );
        })}
      </div>
    </div>
  );
}
