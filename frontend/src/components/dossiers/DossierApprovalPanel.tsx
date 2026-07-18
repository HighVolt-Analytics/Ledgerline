import { Check, CircleDashed, Lock, Minus, Shield, X } from "lucide-react";
import { SectionBlock } from "@/components/SectionBlock";
import { StatusPill, pillTones } from "@/components/StatusPill";
import type { DossierApprovalChain, DossierApprovalStepState } from "@/lib/dossierApproval";
import {
  approvalChainProgress,
  approvalStepDetailHuman,
  approvalStepStateLabel,
  formatApprovalTimestamp,
} from "@/lib/dossierApproval";
import type { DossierPipelinePath } from "@/lib/dossiers";
import { cn } from "@/lib/cn";

function stepIcon(state: DossierApprovalStepState) {
  if (state === "done") return <Check className="h-4 w-4 dossier-row__icon--ok shrink-0" />;
  if (state === "fail") return <X className="h-4 w-4 dossier-row__icon--bad shrink-0" />;
  if (state === "waived" || state === "not_required" || state === "skipped") {
    return <Minus className="h-4 w-4 dossier-row__icon--muted shrink-0" />;
  }
  if (state === "blocked") return <Lock className="h-4 w-4 dossier-row__icon--muted shrink-0" />;
  return <CircleDashed className="h-4 w-4 dossier-row__icon--pending shrink-0" />;
}

function stepTone(state: DossierApprovalStepState): string {
  if (state === "done") return pillTones.ok;
  if (state === "fail" || state === "blocked") return pillTones.bad;
  if (state === "pending") return pillTones.amber;
  return pillTones.muted;
}

function actorLabel(actor: string): string | null {
  const token = actor.trim();
  if (!token || token === "—") return null;
  if (token === "Policy engine") return "Automatic (policy)";
  if (token === "System") return "System";
  return token;
}

export function DossierApprovalPanel({
  chain,
  pipelinePath,
}: {
  chain: DossierApprovalChain;
  pipelinePath?: DossierPipelinePath | null;
}) {
  const understood = pipelinePath === "understood";
  const { complete, total } = approvalChainProgress(chain);

  return (
    <SectionBlock
      label="Approval chain"
      description={
        understood
          ? "Understood path ends at vault — no Approvals queue, ledger post, or payment."
          : "Policy checks, manual approvals, ledger posting, and payment."
      }
    >
      <div className="dossier-panel">
        <div className="dossier-approval-policy">
          <Shield className="h-3.5 w-3.5 text-primary shrink-0" aria-hidden />
          <span className="dossier-approval-policy__label">Policy</span>
          <StatusPill className={pillTones.muted}>{chain.policyLabel}</StatusPill>
          <span className="dossier-approval-policy__progress tnum">
            {complete}/{total} complete
          </span>
        </div>

        <ol className="dossier-approval-chain">
          {chain.steps.map((step, index) => {
            const detail = approvalStepDetailHuman(step.detail);
            const actor = actorLabel(step.actor);
            const at = formatApprovalTimestamp(step.at);

            return (
              <li
                key={step.id}
                className={cn(
                  "dossier-approval-chain__item",
                  (step.state === "blocked" || step.state === "fail") &&
                    "dossier-approval-chain__item--blocked",
                  step.state === "pending" && "dossier-approval-chain__item--pending"
                )}
                data-testid={`approval-step-${step.id}`}
              >
                {index < chain.steps.length - 1 ? (
                  <span className="dossier-approval-chain__connector" aria-hidden />
                ) : null}
                <span className="dossier-approval-chain__node">{stepIcon(step.state)}</span>
                <div className="dossier-approval-chain__body">
                  <div className="dossier-approval-chain__head">
                    <span className="dossier-approval-chain__title">{step.label}</span>
                    <StatusPill className={stepTone(step.state)}>
                      {approvalStepStateLabel(step.state)}
                    </StatusPill>
                  </div>
                  {detail ? (
                    <p className="dossier-approval-chain__detail">{detail}</p>
                  ) : null}
                  {(actor || at) && (
                    <div className="dossier-approval-chain__meta">
                      {actor ? (
                        <span className="dossier-approval-chain__actor">{actor}</span>
                      ) : null}
                      {actor && at ? (
                        <span className="dossier-approval-chain__sep">·</span>
                      ) : null}
                      {at ? <span className="dossier-approval-chain__at tnum">{at}</span> : null}
                    </div>
                  )}
                  {step.policyRef ? (
                    <span className="dossier-approval-chain__ref">{step.policyRef}</span>
                  ) : null}
                  {step.sodNote ? (
                    <p className="dossier-approval-chain__sod">{step.sodNote}</p>
                  ) : null}
                </div>
              </li>
            );
          })}
        </ol>
      </div>
    </SectionBlock>
  );
}
