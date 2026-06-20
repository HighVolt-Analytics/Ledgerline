import {
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  Clock,
  User,
} from "lucide-react";
import { useCallback, useMemo, useRef, useState } from "react";
import { StatusPill, pillTones } from "@/components/StatusPill";
import type { DossierPipelineCheck, DossierPipelineStep, DossierPipelineStageId } from "@/lib/dossiers";
import {
  DOSSIER_PIPELINE_STAGES,
  dossierPipelineCounts,
  dossierStageDescription,
  dossierStageLabel,
  firstPipelineFailure,
  isStageBlocked,
  pipelineBlockedFromStageId,
  stageShouldDefaultOpen,
} from "@/lib/dossiers";
import { cn } from "@/lib/cn";

function stageStatusLabel(state: DossierPipelineStep["state"]): string {
  if (state === "pass") return "PASS";
  if (state === "fail") return "FAIL";
  if (state === "waived") return "WAIVED";
  return "PENDING";
}

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
  return state.toUpperCase();
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
  byStage: Map<DossierPipelineStageId, DossierPipelineStep>
): Set<DossierPipelineStageId> {
  const open = new Set<DossierPipelineStageId>();
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
}: {
  order: number;
  stageId: DossierPipelineStageId;
  step: DossierPipelineStep | undefined;
  blocked: boolean;
  open: boolean;
  onToggle: () => void;
  cardRef?: (el: HTMLElement | null) => void;
}) {
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
            <span className="dossier-pipeline-stage__name">{dossierStageLabel(stageId)}</span>
            <StatusPill className={stageStatusTone(state)}>{stageStatusLabel(state)}</StatusPill>
            {step?.exceptionCode ? (
              <span className="dossier-pipeline-stage__code tnum">{step.exceptionCode}</span>
            ) : null}
          </span>
          <span className="dossier-pipeline-stage__hint">{dossierStageDescription(stageId)}</span>
          {step?.detail && step.detail !== "—" ? (
            <span className="dossier-pipeline-stage__summary">{step.detail}</span>
          ) : step?.blockedReason ? (
            <span className="dossier-pipeline-stage__summary dossier-pipeline-stage__summary--muted">
              {step.blockedReason}
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
            <div className="dossier-pipeline-blocked-box">{step.blockedReason}</div>
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

type DossierPipelineOverviewProps = {
  pipeline: DossierPipelineStep[];
  onJumpToFailure?: () => void;
  onExpandAll?: () => void;
  onCollapseAll?: () => void;
};

export function DossierPipelineOverview({
  pipeline,
  onJumpToFailure,
  onExpandAll,
  onCollapseAll,
}: DossierPipelineOverviewProps) {
  const counts = useMemo(() => dossierPipelineCounts(pipeline), [pipeline]);
  const pending = pipeline.filter((s) => s.state === "pending").length;
  const firstFail = firstPipelineFailure(pipeline);

  return (
    <div className="dossier-pipeline-overview">
      <div className="dossier-pipeline-overview__row">
        <div className="dossier-pipeline-overview__stats">
          <span className="dossier-pipeline-overview__stat dossier-pipeline-overview__stat--pass">
            {counts.pass} pass
          </span>
          {counts.fail > 0 ? (
            <span className="dossier-pipeline-overview__stat dossier-pipeline-overview__stat--fail">
              {counts.fail} fail
            </span>
          ) : null}
          {counts.waived > 0 ? (
            <span className="dossier-pipeline-overview__stat dossier-pipeline-overview__stat--waived">
              {counts.waived} waived
            </span>
          ) : null}
          {pending > 0 ? (
            <span className="dossier-pipeline-overview__stat dossier-pipeline-overview__stat--pending">
              {pending} not run
            </span>
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
          <AlertTriangle className="h-4 w-4 shrink-0" />
          <div>
            <span className="font-semibold">
              Blocked at stage {String(
                DOSSIER_PIPELINE_STAGES.find((s) => s.id === firstFail.stageId)?.order ?? ""
              ).padStart(2, "0")}{" "}
              — {dossierStageLabel(firstFail.stageId)}
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

export function DossierPipelineTimeline({ pipeline }: { pipeline: DossierPipelineStep[] }) {
  const byStage = useMemo(
    () => new Map(pipeline.map((step) => [step.stageId, step])),
    [pipeline]
  );

  const [openStages, setOpenStages] = useState(() => defaultOpenStages(pipeline, byStage));
  const stageRefs = useRef<Partial<Record<DossierPipelineStageId, HTMLElement | null>>>({});

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

  const expandAll = useCallback(() => {
    const ids = DOSSIER_PIPELINE_STAGES.map((s) => s.id).filter((id) =>
      stageHasDetail(byStage.get(id))
    );
    setOpenStages(new Set(ids));
  }, [byStage]);

  const collapseAll = useCallback(() => {
    setOpenStages(new Set());
  }, []);

  return (
    <div className="dossier-pipeline-detail">
      <DossierPipelineOverview
        pipeline={pipeline}
        onJumpToFailure={jumpToFailure}
        onExpandAll={expandAll}
        onCollapseAll={collapseAll}
      />
      <div className="dossier-pipeline-stages">
        {DOSSIER_PIPELINE_STAGES.map((stage) => {
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
              cardRef={(el) => {
                stageRefs.current[stage.id] = el;
              }}
            />
          );
        })}
      </div>
    </div>
  );
}
